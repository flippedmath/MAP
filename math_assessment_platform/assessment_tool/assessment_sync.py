"""Canonical, ordinal-based forms for the Synchronize tests delivery option."""

from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from .assessment_options import (
    CHOICE_SYNC_ON,
    GROUP_SYNC_TESTS,
    resolved_assessment_option,
)


def synchronized_tests_enabled(assessment) -> bool:
    return (
        resolved_assessment_option(assessment, GROUP_SYNC_TESTS)
        == CHOICE_SYNC_ON
    )


def assessment_blueprint_hash(assessment) -> str:
    """Hash all source rows that can change generated question selection/content."""
    from . import models as m

    aqgs = list(
        m.AssessmentQuestionGroup.objects.filter(assessment=assessment)
        .order_by("order", "id")
        .values("id", "order", "name", "branch_location_id")
    )
    source = {"assessment_id": assessment.pk, "groups": aqgs}
    group_branch_ids = [row["branch_location_id"] for row in aqgs if row["branch_location_id"]]
    children = list(
        m.BranchGroup.objects.filter(parent_id__in=group_branch_ids)
        .order_by("parent_id", "order", "id")
        .values("id", "parent_id", "order", "name", "folder_type")
    )
    source["children"] = children

    cqd_branch_ids = [row["id"] for row in children if row["folder_type"] == "cqd"]
    pool_branches = list(
        m.BranchGroup.objects.filter(parent_id__in=cqd_branch_ids)
        .order_by("parent_id", "order", "id")
        .values("id", "parent_id", "order", "name", "folder_type")
    )
    source["pool_branches"] = pool_branches
    cqd_rows = list(
        m.CustomQuestionDistribution.objects.filter(
            assigned_folder_id__in=cqd_branch_ids
        )
        .order_by("id")
        .values("id", "assigned_folder_id", "suggested_count", "name")
    )
    source["distributions"] = cqd_rows

    problem_branch_ids = [
        row["id"] for row in children if row["folder_type"] == "problem"
    ] + [row["id"] for row in pool_branches if row["folder_type"] == "problem"]
    problems = list(
        m.Problem.objects.filter(branch_location_id__in=problem_branch_ids)
        .order_by("branch_location_id", "id")
        .values(
            "id",
            "aqg_id",
            "cqd_id",
            "branch_location_id",
            "problem_status",
            "title",
        )
    )
    source["problems"] = problems
    problem_ids = [row["id"] for row in problems]
    source["question_blocks"] = list(
        m.QuestionBlock.objects.filter(problem_id__in=problem_ids)
        .order_by("problem_id", "id")
        .values("id", "problem_id", "content", "space_allocation")
    )
    source["entity_segments"] = list(
        m.EntitySegment.objects.filter(problem_id__in=problem_ids)
        .order_by("problem_id", "id")
        .values(
            "id",
            "problem_id",
            "problem_type_id_originator_id",
            "content",
            "parent_entity_id",
            "default_answer",
            "is_answer_to_multi_choice",
            "points",
            "space_allocation",
        )
    )
    encoded = json.dumps(
        source,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def current_synchronized_form(assessment, attempt_number: int):
    from . import models as m

    return (
        m.AssessmentSynchronizedForm.objects.filter(
            assessment=assessment,
            attempt_number=int(attempt_number),
            is_current=True,
        )
        .order_by("-cohort_number", "-id")
        .first()
    )


@transaction.atomic
def ensure_synchronized_form(assessment, attempt_number: int, *, created_by=None):
    """
    Return the current cohort for this ordinal, creating one if needed.

    Under the assessment lock, unused current forms are refreshed when the
    live blueprint hash changed so late enrollments / upcoming windows do not
    clone a stale unused form. Forms already referenced by attempts are left
    alone (teacher preflight decides reuse vs regenerate).
    """
    from . import models as m

    attempt_number = max(1, int(attempt_number))
    m.Assessment.objects.select_for_update().get(pk=assessment.pk)
    current = current_synchronized_form(assessment, attempt_number)
    if current is not None:
        current_hash = assessment_blueprint_hash(assessment)
        if current.blueprint_hash == current_hash:
            return current
        was_used = m.StudentAssessmentAttempt.objects.filter(
            synchronized_form_id=current.id
        ).exists()
        if was_used:
            return current
    return create_synchronized_form(
        assessment,
        attempt_number,
        created_by=created_by,
        _already_locked=True,
    )


@transaction.atomic
def create_synchronized_form(
    assessment,
    attempt_number: int,
    *,
    created_by=None,
    _already_locked: bool = False,
):
    """Generate and persist a new current cohort without deleting older cohorts."""
    from . import models as m
    from .student_attempts import _freeze_instance
    from .util import assemble_practice_test

    attempt_number = max(1, int(attempt_number))
    # Serialize cohort allocation and current-form switching per assessment.
    if not _already_locked:
        m.Assessment.objects.select_for_update().get(pk=assessment.pk)
    forms = m.AssessmentSynchronizedForm.objects.filter(
        assessment=assessment,
        attempt_number=attempt_number,
    )
    last = forms.order_by("-cohort_number").first()
    cohort_number = int(last.cohort_number or 0) + 1 if last else 1
    forms.filter(is_current=True).update(is_current=False)

    existing_hashes = set(
        m.AssessmentSynchronizedForm.objects.filter(assessment=assessment)
        .exclude(content_hash="")
        .values_list("content_hash", flat=True)
    )
    frozen_rows = []
    content_hash = ""
    max_generation_attempts = 12 if attempt_number > 1 or existing_hashes else 1
    for _ in range(max_generation_attempts):
        assembled = assemble_practice_test(
            assessment,
            actor_user=None,
            allow_status_mutation=False,
        )
        frozen_rows = []
        for instance in assembled.get("problems") or []:
            answer_key, render_payload, answer_fields, body_html = _freeze_instance(instance)
            max_points = 0.0
            for field in answer_key.get("answer_fields") or []:
                try:
                    max_points += float(field.get("points") or 0)
                except (TypeError, ValueError):
                    pass
            slot = int(instance.get("slot_index") or 0)
            frozen_rows.append(
                {
                    "slot_index": slot,
                    "section_name": instance.get("section_name"),
                    "title": instance.get("title") or f"Question {slot}",
                    "source_problem_id": instance.get("problem_id"),
                    "body_html": body_html,
                    "render_payload": render_payload,
                    "answer_key": answer_key,
                    "answer_fields": answer_fields,
                    "max_points": max_points,
                }
            )
        content_hash = hashlib.sha256(
            json.dumps(
                frozen_rows,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        if content_hash not in existing_hashes:
            break
    else:
        raise RuntimeError(
            f"Could not generate a distinct synchronized form for attempt "
            f"{attempt_number} after {max_generation_attempts} tries. Add more "
            "question-pool choices or randomized problem values."
        )

    form = m.AssessmentSynchronizedForm.objects.create(
        assessment=assessment,
        attempt_number=attempt_number,
        cohort_number=cohort_number,
        blueprint_hash=assessment_blueprint_hash(assessment),
        content_hash=content_hash,
        is_current=True,
        unsynchronized_history_acknowledged_at=timezone.now(),
        created_by=created_by,
    )
    frozen = [
        m.AssessmentSynchronizedProblem(
            synchronized_form=form,
            **row,
        )
        for row in frozen_rows
    ]
    m.AssessmentSynchronizedProblem.objects.bulk_create(frozen)
    return form


def synchronization_preflight(
    assessment,
    attempt_number: int,
    *,
    decision: str = "",
    created_by=None,
) -> dict:
    """
    Resolve the canonical form before opening a class assessment or retake.
    A required decision never mutates state.
    """
    if not synchronized_tests_enabled(assessment):
        return {"ready": True, "enabled": False, "form": None}

    from . import models as m
    from .student_attempts import attempts_qs_for_template

    attempt_number = max(1, int(attempt_number))
    decision = str(decision or "").strip().lower()
    current = current_synchronized_form(assessment, attempt_number)
    latest_acknowledgement = m.AssessmentSynchronizedForm.objects.filter(
        assessment=assessment
    ).order_by("-unsynchronized_history_acknowledged_at", "-id").first()
    attempts = attempts_qs_for_template(assessment)
    legacy_attempts = attempts.filter(synchronized_form__isnull=True)
    if latest_acknowledgement is not None:
        legacy_attempts = legacy_attempts.filter(
            creation_date__gt=(
                latest_acknowledgement.unsynchronized_history_acknowledged_at
            )
        )
    needs_history_confirmation = legacy_attempts.exists()

    current_hash = assessment_blueprint_hash(assessment)
    current_was_used = bool(
        current
        and attempts.filter(synchronized_form_id=current.id).exists()
    )
    blueprint_changed = bool(
        current
        and current.blueprint_hash != current_hash
        and current_was_used
    )

    if blueprint_changed and decision not in ("reuse_existing", "generate_new"):
        return {
            "ready": False,
            "enabled": True,
            "code": "synchronization_decision_required",
            "kind": "blueprint_changed",
            "title": f"Choose the form for attempt {attempt_number}",
            "message": (
                "This assessment changed after students used its synchronized form. "
                "Reuse the preserved form for consistency, or generate a new cohort "
                "from the current assessment."
            ),
            "history_warning": needs_history_confirmation,
            "attempt_number": attempt_number,
            "decisions": ["reuse_existing", "generate_new", "cancel"],
        }

    if needs_history_confirmation and decision not in (
        "proceed",
        "reuse_existing",
        "generate_new",
    ):
        return {
            "ready": False,
            "enabled": True,
            "code": "synchronization_decision_required",
            "kind": "unsynchronized_history",
            "title": "Start synchronized tests?",
            "message": (
                "Students previously took this assessment with different generated "
                "tests. Continuing will synchronize new tests by attempt number; "
                "existing attempts will remain unchanged."
            ),
            "attempt_number": attempt_number,
            "decisions": ["proceed", "cancel"],
            "settings_hint": (
                "You can turn Synchronize tests off from this assessment's Settings "
                "on the Course Assessments page."
            ),
        }

    if blueprint_changed and decision == "reuse_existing":
        if needs_history_confirmation:
            current.unsynchronized_history_acknowledged_at = timezone.now()
            current.save(update_fields=["unsynchronized_history_acknowledged_at"])
        return {"ready": True, "enabled": True, "form": current}

    if (
        current is None
        or decision == "generate_new"
        or (decision == "proceed" and needs_history_confirmation)
        or (
            current.blueprint_hash != current_hash and not current_was_used
        )
    ):
        try:
            if decision == "generate_new" or (
                decision == "proceed" and needs_history_confirmation
            ):
                current = create_synchronized_form(
                    assessment,
                    attempt_number,
                    created_by=created_by,
                )
            else:
                current = ensure_synchronized_form(
                    assessment,
                    attempt_number,
                    created_by=created_by,
                )
        except RuntimeError as exc:
            return {
                "ready": False,
                "enabled": True,
                "code": "synchronization_generation_failed",
                "error": str(exc),
            }
    return {"ready": True, "enabled": True, "form": current}
