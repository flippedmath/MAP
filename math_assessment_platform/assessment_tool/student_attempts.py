"""
Frozen student assessment attempts: generate, folders, takeability, grade-once.
"""

from __future__ import annotations

import copy
import json
import logging
import threading

from django.db import close_old_connections, transaction
from django.utils import timezone

from .folder_roots import FOLDER_STUDENT_PROVIDED
from .util import assemble_practice_test, grade_entities_payload

logger = logging.getLogger(__name__)

# Client render needs JSON manifests for these; strip secrets separately.
_CLIENT_JSON_ARCHETYPES = frozenset(
    {
        "graph",
        "graphBetweenPoints",
        "slopeFieldGraph",
        "canvas",
    }
)

_SECRET_INPUT_KEYS = frozenset(
    {
        "correct_answer",
        "correctAnswer",
        "answer",
        "expected",
        "solution",
    }
)


def _models():
    from . import models as m
    return m


def _aware(dt):
    """Normalize DB datetimes for comparison with timezone.now()."""
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt


# Teacher-selectable assessment lifecycle statuses (course Assessments page).
ASSESSMENT_STATUSES = frozenset({"closed", "open", "upcoming", "hidden"})
# Legacy values still read for compatibility; not offered in the UI.
_ASSESSMENT_STATUS_ALIASES = {
    "inactive": "hidden",
    "locked": "closed",
    "submitted": "closed",
    "active": "open",
    "retake_available": "open",
    "retake available": "open",
}


def normalize_assessment_status(status) -> str:
    """Map legacy assessment status strings onto the current set."""
    raw = (status or "").strip().lower().replace(" ", "_")
    if not raw:
        return "hidden"
    if raw in ASSESSMENT_STATUSES:
        return raw
    return _ASSESSMENT_STATUS_ALIASES.get(raw, raw)


def assessment_window_bounds(assessment):
    """Return (start, end) as aware datetimes, or (None, None) if incomplete."""
    if assessment is None:
        return None, None
    start = _aware(getattr(assessment, "start_time", None))
    end = _aware(getattr(assessment, "end_time", None))
    if start is None or end is None:
        return None, None
    return start, end


def upcoming_window_contains(assessment, *, now=None) -> bool:
    """True when status is upcoming and now is inside [start_time, end_time]."""
    if normalize_assessment_status(getattr(assessment, "status", None)) != "upcoming":
        return False
    start, end = assessment_window_bounds(assessment)
    if start is None or end is None:
        return False
    now = _aware(now) or timezone.now()
    return start <= now <= end


def upcoming_window_expired(assessment, *, now=None) -> bool:
    """True when status is upcoming and end_time is strictly in the past."""
    if normalize_assessment_status(getattr(assessment, "status", None)) != "upcoming":
        return False
    _start, end = assessment_window_bounds(assessment)
    if end is None:
        return False
    now = _aware(now) or timezone.now()
    return now > end


def student_facing_assessment_status(assessment, *, now=None) -> str:
    """
    Status string shown to students.

    Teacher-side `upcoming` appears as `open` while the auto-open window is
    active; after the window ends (before cron flips DB) it appears closed.
    """
    status = normalize_assessment_status(getattr(assessment, "status", None))
    if status != "upcoming":
        return status
    now = _aware(now) or timezone.now()
    if upcoming_window_expired(assessment, now=now):
        return "closed"
    if upcoming_window_contains(assessment, now=now):
        return "open"
    return "upcoming"


def assessment_is_takeable(assessment, *, now=None) -> bool:
    """Parent assessment is currently available for students to start/continue."""
    if assessment is None:
        return False
    if assessment_taking_ended(assessment, now=now):
        return False
    if assessment_is_hidden_from_students(assessment):
        return False
    now = _aware(now) or timezone.now()
    status = normalize_assessment_status(assessment.status)
    if status == "open":
        return True
    if status == "upcoming":
        return upcoming_window_contains(assessment, now=now)
    return False


def assessment_is_hidden_from_students(assessment) -> bool:
    """True when students must not see this assessment on the course list."""
    if assessment is None:
        return True
    return normalize_assessment_status(assessment.status) == "hidden"


def assessment_has_submissions(assessment) -> bool:
    """True when any student has a submitted attempt for this template."""
    m = _models()
    template = course_template_assessment(assessment) or assessment
    return attempts_qs_for_template(template).filter(
        status=m.StudentAssessmentAttempt.STATUS_SUBMITTED,
    ).exists()


def assessment_taking_ended(assessment, *, now=None) -> bool:
    """
    True when students must stop taking this assessment.

    Closed status, or an upcoming auto-open window whose end_time has passed.
    """
    if assessment is None:
        return True
    status = normalize_assessment_status(assessment.status)
    if status == "closed":
        return True
    return upcoming_window_expired(assessment, now=now)


def force_submit_unsubmitted_attempts(template, *, reason: str = "closed") -> dict:
    """
    Compile saved answers for every ready/in_progress attempt on this template
    into graded submissions.

    Per-student retakes are left alone — those end only via Close retake.
    """
    m = _models()
    template = course_template_assessment(template) or template
    open_attempts = list(
        attempts_qs_for_template(template)
        .filter(
            status__in=(
                m.StudentAssessmentAttempt.STATUS_READY,
                m.StudentAssessmentAttempt.STATUS_IN_PROGRESS,
            )
        )
        .select_related("user", "assessment")
        .order_by("id")
    )
    submitted_ids = []
    skipped_retake_ids = []
    errors = []
    for attempt in open_attempts:
        if attempt_may_continue_while_closed(attempt, template, attempt.user):
            skipped_retake_ids.append(attempt.id)
            continue
        try:
            submit_and_grade_attempt(attempt)
            submitted_ids.append(attempt.id)
        except ValueError:
            # Already graded concurrently — treat as done.
            if attempt.status != m.StudentAssessmentAttempt.STATUS_SUBMITTED:
                attempt.refresh_from_db()
            if attempt.auto_graded_at is not None or (
                attempt.status == m.StudentAssessmentAttempt.STATUS_SUBMITTED
            ):
                submitted_ids.append(attempt.id)
            else:
                errors.append(
                    {
                        "attempt_id": attempt.id,
                        "error": "Could not submit attempt.",
                    }
                )
        except Exception as exc:
            logger.exception(
                "Force-submit failed for attempt %s (%s): %s",
                attempt.id,
                reason,
                exc,
            )
            errors.append({"attempt_id": attempt.id, "error": str(exc)})
    return {
        "reason": reason,
        "submitted_count": len(submitted_ids),
        "submitted_attempt_ids": submitted_ids,
        "skipped_retake_ids": skipped_retake_ids,
        "errors": errors,
    }


def close_assessment_and_finalize_attempts(
    assessment, *, reason: str = "teacher_closed", set_status: bool = True
) -> dict:
    """
    Mark the course assessment closed (optional) and finalize open takes.

    If nobody has started or submitted, discard generated ready attempts and
    write no grade rows (throws an experimental open→close with no student work).
    Otherwise force-submit open non-retake attempts as usual (absentees → 0).
    """
    from .course_enrollment import record_zeros_on_assessment_close

    template = course_template_assessment(assessment) or assessment
    status_changed = False
    if set_status:
        current = (template.status or "").lower().replace(" ", "_")
        if current != "closed":
            template.status = "closed"
            template.modified_date = timezone.now()
            template.save(update_fields=["status", "modified_date"])
            status_changed = True

    if not assessment_has_student_engagement(template):
        discard_result = discard_all_unstarted_attempts(template)
        # Defensive: drop any accidental grade rows for this unused assessment.
        m = _models()
        m.FinalGradeCalculation.objects.filter(assessment_id=template.id).delete()
        return {
            "reason": reason,
            "thrown": True,
            "status_changed": status_changed,
            "assessment_status": template.status,
            "submitted_count": 0,
            "submitted_attempt_ids": [],
            "skipped_retake_ids": [],
            "errors": [],
            "zeros_recorded": 0,
            **discard_result,
        }

    result = force_submit_unsubmitted_attempts(template, reason=reason)
    result["thrown"] = False
    result["status_changed"] = status_changed
    result["assessment_status"] = template.status
    result["zeros_recorded"] = record_zeros_on_assessment_close(assessment=template)
    return result


def assessment_has_student_engagement(template) -> bool:
    """
    True when any student has actually started or submitted a take for this
    course assessment (ready/generated-only attempts do not count).
    """
    from django.db.models import Q

    m = _models()
    template = course_template_assessment(template) or template
    return (
        attempts_qs_for_template(template)
        .filter(
            Q(status=m.StudentAssessmentAttempt.STATUS_IN_PROGRESS)
            | Q(status=m.StudentAssessmentAttempt.STATUS_SUBMITTED)
            | Q(started_at__isnull=False)
            | Q(auto_graded_at__isnull=False)
        )
        .exists()
    )


def discard_all_unstarted_attempts(template) -> dict:
    """Remove every READY attempt (and take artifacts) for a course assessment."""
    m = _models()
    template = course_template_assessment(template) or template
    ready = list(
        attempts_qs_for_template(template)
        .filter(status=m.StudentAssessmentAttempt.STATUS_READY)
        .select_related("assessment", "branch", "user")
        .order_by("id")
    )
    discarded_ids = []
    for attempt in ready:
        if discard_unstarted_attempt(attempt):
            discarded_ids.append(attempt.id)
    return {
        "discarded_count": len(discarded_ids),
        "discarded_attempt_ids": discarded_ids,
    }

def close_expired_upcoming_assessments(*, now=None) -> dict:
    """
    Flip upcoming assessments whose auto-open window has ended to closed and
    force-submit open (non-retake) attempts. Intended for cron, not request handlers.
    """
    m = _models()
    now = _aware(now) or timezone.now()
    expired = list(
        m.Assessment.objects.filter(
            parent_assessment__isnull=True,
            user__isnull=True,
            status="upcoming",
            end_time__isnull=False,
            end_time__lt=now,
        ).order_by("id")
    )
    closed_ids = []
    results = []
    for assessment in expired:
        payload = close_assessment_and_finalize_attempts(
            assessment,
            reason="upcoming_window_ended",
            set_status=True,
        )
        closed_ids.append(assessment.id)
        results.append({"assessment_id": assessment.id, **payload})
    return {
        "closed_count": len(closed_ids),
        "closed_assessment_ids": closed_ids,
        "results": results,
    }


def finalize_student_attempt_if_open(attempt) -> dict | None:
    """Submit+grade a single open attempt; no-op if already submitted."""
    m = _models()
    if attempt is None:
        return None
    if (
        attempt.status == m.StudentAssessmentAttempt.STATUS_SUBMITTED
        or attempt.auto_graded_at is not None
    ):
        return None
    try:
        return submit_and_grade_attempt(attempt)
    except ValueError:
        return None


def assessment_available_to_student(assessment, student, *, now=None) -> bool:
    """
    Class-wide open/upcoming window, class retake_available, or a teacher
    per-student open-retake overwrite (allowed even when the class assessment
    is closed).
    """
    template = course_template_assessment(assessment) or assessment
    if assessment_is_hidden_from_students(template):
        return False
    if assessment_is_takeable(template, now=now):
        return True
    status = (template.status or "").lower().replace(" ", "_")
    if status == "retake_available":
        return True
    from .student_assessment_actions import student_has_open_retake

    return student_has_open_retake(template, student)


def student_may_start_attempt(assessment, student, attempts=None, *, now=None) -> bool:
    """Whether the student may start or continue an attempt right now."""
    m = _models()
    template = course_template_assessment(assessment) or assessment
    now = _aware(now) or timezone.now()
    if attempts is None:
        attempts = list(
            attempts_qs_for_template(template)
            .filter(user=student)
            .order_by("id")
        )
    in_progress = next(
        (
            a
            for a in reversed(attempts)
            if a.status == m.StudentAssessmentAttempt.STATUS_IN_PROGRESS
        ),
        None,
    )
    ready = next(
        (
            a
            for a in reversed(attempts)
            if a.status == m.StudentAssessmentAttempt.STATUS_READY
        ),
        None,
    )
    open_attempt = in_progress or ready
    if open_attempt is not None:
        # Class/window ended: only an in-flight retake (or open retake grant) may continue.
        if assessment_taking_ended(template, now=now):
            return attempt_may_continue_while_closed(open_attempt, template, student)
        return True

    # Closed class assessment: only a retake grant may start a new take.
    if assessment_taking_ended(template, now=now):
        submitted = [
            a
            for a in attempts
            if a.status == m.StudentAssessmentAttempt.STATUS_SUBMITTED
            or a.auto_graded_at is not None
        ]
        if not submitted:
            return False
        return assessment_available_to_student(template, student, now=now)

    if not assessment_available_to_student(template, student, now=now):
        return False

    submitted = [
        a
        for a in attempts
        if a.status == m.StudentAssessmentAttempt.STATUS_SUBMITTED
        or a.auto_graded_at is not None
    ]
    if not submitted:
        return True

    status = (template.status or "").lower().replace(" ", "_")
    if status == "retake_available":
        return True
    from .student_assessment_actions import student_has_open_retake

    return student_has_open_retake(template, student)

def generation_job_blocks_edits(assessment) -> bool:
    m = _models()
    return m.AssessmentGenerationJob.objects.filter(
        assessment=assessment,
        status__in=(
            m.AssessmentGenerationJob.STATUS_PENDING,
            m.AssessmentGenerationJob.STATUS_RUNNING,
        ),
    ).exists()


def latest_generation_job(assessment):
    m = _models()
    return (
        m.AssessmentGenerationJob.objects.filter(assessment=assessment)
        .order_by("-started_at", "-id")
        .first()
    )


def _base_archetype(seg_or_token) -> str:
    if isinstance(seg_or_token, dict):
        raw = seg_or_token.get("archetype") or seg_or_token.get("token") or ""
    else:
        raw = seg_or_token or ""
    text = str(raw).strip()
    # Tokens like graph1 / graphBetweenPoints2 → strip trailing digits
    i = len(text)
    while i > 0 and text[i - 1].isdigit():
        i -= 1
    return text[:i] if i < len(text) else text


def _strip_mc_correct_flags(options):
    if not isinstance(options, list):
        return options
    cleaned = []
    for opt in options:
        if not isinstance(opt, dict):
            cleaned.append(opt)
            continue
        row = {k: v for k, v in opt.items() if k != "is_correct"}
        cleaned.append(row)
    return cleaned


def _sanitize_client_inputs(inputs) -> dict:
    if not isinstance(inputs, dict):
        return {}
    out = {}
    for key, value in inputs.items():
        if key in _SECRET_INPUT_KEYS:
            continue
        if key == "options":
            out[key] = _strip_mc_correct_flags(value)
        else:
            out[key] = value
    return out


def _parse_jsonish(raw):
    if raw is None or raw == "":
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text.startswith("{"):
            return None
        try:
            return json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    return None


def _client_safe_evaluated_output(archetype: str, raw) -> str:
    """
    Return evaluated_output safe to send to the student take client.
    Graphs need their JSON manifest; interactive widgets need sanitized config
    without expected answers.
    """
    arch = _base_archetype(archetype)
    if arch not in _CLIENT_JSON_ARCHETYPES:
        return ""

    if arch == "graph":
        if isinstance(raw, dict):
            return json.dumps(raw)
        text = str(raw or "").strip()
        return text if text.startswith("{") else ""

    cfg = _parse_jsonish(raw)
    if not cfg:
        return ""

    if arch == "graphBetweenPoints":
        targets = []
        for t in cfg.get("student_targets") or []:
            if not isinstance(t, dict):
                continue
            # Keep slot metadata only — start/end are the graded answer.
            targets.append({"id": t.get("id"), "type": t.get("type")})
        safe = {
            "archetype": "graphBetweenPoints",
            "bounds": cfg.get("bounds"),
            "visualization": cfg.get("visualization") or {},
            "let_student_draw": bool(cfg.get("let_student_draw")),
            "author_visible": cfg.get("author_visible") or [],
            "student_targets": targets,
        }
        return json.dumps(safe)

    if arch == "slopeFieldGraph":
        safe = {
            "archetype": "slopeFieldGraph",
            "equation": cfg.get("equation"),
            "equation_display": cfg.get("equation_display"),
            "bounds": cfg.get("bounds"),
            "lattice": cfg.get("lattice") or [],
            # Keep selected lattice points — student mode only allows clicks on
            # those marked dots; angles/undefined marks are the graded answer.
            "selected_points": cfg.get("selected_points") or [],
            "show_instructions": bool(cfg.get("show_instructions", False)),
        }
        return json.dumps(safe)

    if arch == "canvas":
        # Canvas config is usually empty-ish; avoid shipping stroke answer keys.
        safe = {k: v for k, v in cfg.items() if k not in ("strokes", "png", "answer", "expected")}
        safe.setdefault("archetype", "canvas")
        return json.dumps(safe)

    return ""


def _client_safe_field(field: dict) -> dict:
    out = {
        "token": field.get("token"),
        "archetype": field.get("archetype"),
        "sequence_token": field.get("sequence_token"),
        "points": field.get("points"),
        "label": field.get("label"),
        "is_answer_field": field.get("is_answer_field", True),
        "shuffle_seed": field.get("shuffle_seed"),
        "output_types": field.get("output_types"),
    }
    inputs = field.get("inputs")
    if isinstance(inputs, dict):
        out["inputs"] = _sanitize_client_inputs(inputs)
    return out


def _client_safe_segment(seg: dict) -> dict:
    arch = _base_archetype(seg)
    out = {
        "id": seg.get("id"),
        "token": seg.get("token"),
        "archetype": seg.get("archetype"),
        "sequence_token": seg.get("sequence_token"),
        "points": seg.get("points"),
        "label": seg.get("label"),
        "is_answer_field": seg.get("is_answer_field"),
        "shuffle_seed": seg.get("shuffle_seed"),
        "output_types": seg.get("output_types"),
        "latex_output": seg.get("latex_output") or "",
        "simulated_value": "",
        "evaluated_output": "",
    }
    # Display / interactive JSON manifests (graphs, slope fields, GBP, canvas).
    # Never send MC/shortAnswer evaluated_output (that is the correct answer).
    raw_eval = seg.get("evaluated_output") or seg.get("simulated_value") or ""
    out["evaluated_output"] = _client_safe_evaluated_output(arch, raw_eval)
    if out["evaluated_output"]:
        # Stub cards read data-simulated-value for graph/GBP mounts.
        out["simulated_value"] = out["evaluated_output"]

    inputs = seg.get("inputs")
    if isinstance(inputs, dict):
        out["inputs"] = _sanitize_client_inputs(inputs)
    return out


def _freeze_instance(instance: dict) -> tuple[dict, dict, list, str]:
    """
    Split an assemble_practice_test problem instance into:
    answer_key (server), render_payload (client), answer_fields (client), body_html.
    """
    body_html = instance.get("body_html") or ""
    loaded = instance.get("loaded_segments") or []
    answer_fields_raw = instance.get("answer_fields") or []
    all_entities = instance.get("all_entities") or []

    answer_key = {
        "answer_fields": copy.deepcopy(answer_fields_raw),
        "all_entities": copy.deepcopy(all_entities),
        "loaded_segments": copy.deepcopy(loaded),
    }
    render_payload = {
        "loaded_segments": [_client_safe_segment(s) for s in loaded if isinstance(s, dict)],
        "section_name": instance.get("section_name"),
        "from_problem_set": instance.get("from_problem_set"),
    }
    answer_fields = [
        _client_safe_field(f) for f in answer_fields_raw if isinstance(f, dict)
    ]
    return answer_key, render_payload, answer_fields, body_html


def _client_segments_from_problem(problem) -> list[dict]:
    """
    Always rebuild client segments from answer_key so older attempts frozen
    with over-stripped render_payload still render graphs correctly.
    """
    key = problem.answer_key or {}
    loaded = key.get("loaded_segments") or []
    if not loaded:
        loaded = (problem.render_payload or {}).get("loaded_segments") or []
    return [_client_safe_segment(s) for s in loaded if isinstance(s, dict)]


def _client_fields_from_problem(problem) -> list[dict]:
    raw = problem.answer_fields or []
    if not raw:
        raw = (problem.answer_key or {}).get("answer_fields") or []
    return [_client_safe_field(f) for f in raw if isinstance(f, dict)]

def _ensure_spa_course_folder(student, course):
    m = _models()
    root = m.BranchGroup.objects.filter(owner=student, parent__isnull=True).first()
    if not root:
        raise RuntimeError(f"Student {student.username} has no root folder.")
    spa = m.BranchGroup.objects.filter(
        owner=student, parent=root, name=FOLDER_STUDENT_PROVIDED
    ).first()
    if not spa:
        spa = m.BranchGroup.objects.create(
            name=FOLDER_STUDENT_PROVIDED,
            owner=student,
            parent=root,
            folder_type="folder",
            order=FOLDER_STUDENT_PROVIDED,
        )
    course_folder = m.BranchGroup.objects.filter(
        owner=student, parent=spa, name=course.name
    ).first()
    if not course_folder:
        course_folder = m.BranchGroup.objects.create(
            name=course.name,
            owner=student,
            parent=spa,
            folder_type="folder",
            order=course.name,
        )
    return course_folder


def _ensure_assessment_folder(student, course_folder, assessment_name: str):
    m = _models()
    existing = m.BranchGroup.objects.filter(
        owner=student, parent=course_folder, name=assessment_name
    ).first()
    if existing:
        return existing
    return m.BranchGroup.objects.create(
        name=assessment_name,
        owner=student,
        parent=course_folder,
        folder_type="assessment",
        order=assessment_name,
    )


def _create_take_folder(student, course, template_name: str, take_index: int):
    """Unique SPA folder for each generated take / retake."""
    course_folder = _ensure_spa_course_folder(student, course)
    if take_index <= 1:
        name = template_name
    else:
        name = f"{template_name} (retake {take_index - 1})"
    name = name[:255]
    m = _models()
    # Avoid colliding with an existing folder name from a prior take.
    base = name
    n = 2
    while m.BranchGroup.objects.filter(
        owner=student, parent=course_folder, name=name
    ).exists():
        name = f"{base} [{n}]"[:255]
        n += 1
    return m.BranchGroup.objects.create(
        name=name,
        owner=student,
        parent=course_folder,
        folder_type="assessment",
        order=name,
    )


def course_template_assessment(assessment):
    """Walk parent_assessment to the course template (user is null / root)."""
    if assessment is None:
        return None
    cur = assessment
    seen = set()
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        if cur.parent_assessment_id is None and cur.user_id is None:
            return cur
        if cur.parent_assessment_id is None:
            return cur
        cur = cur.parent_assessment
    return assessment


def assessment_ids_for_template(template) -> list[int]:
    """Template id plus all student take / retake Assessment rows under it."""
    if template is None:
        return []
    m = _models()
    ids = [template.id]
    frontier = [template.id]
    while frontier:
        children = list(
            m.Assessment.objects.filter(parent_assessment_id__in=frontier).values_list(
                "id", flat=True
            )
        )
        frontier = [c for c in children if c not in ids]
        ids.extend(frontier)
    return ids


def attempts_qs_for_template(template):
    """Attempts for a course assessment template, including retake take rows."""
    m = _models()
    return m.StudentAssessmentAttempt.objects.filter(
        assessment_id__in=assessment_ids_for_template(template)
    )


def current_attempt_for_student(template, student, *, enrollment=None):
    """
    Active take for the student on this template: prefer ready/in_progress,
    else the latest attempt.
    """
    m = _models()
    qs = attempts_qs_for_template(template).filter(user=student)
    if enrollment is not None:
        qs = qs.filter(enrollment=enrollment)
    qs = qs.order_by("-id")
    active = qs.exclude(status=m.StudentAssessmentAttempt.STATUS_SUBMITTED).first()
    if active:
        return active
    return qs.first()


def get_attempt_for_template(template, attempt_id):
    """Fetch an attempt id that belongs to this course template (incl. retakes)."""
    return (
        attempts_qs_for_template(template)
        .filter(id=attempt_id)
        .select_related("assessment", "user")
        .first()
    )


def attempt_is_retake(attempt, template=None) -> bool:
    """
    True when this open/submitted attempt is a retake.

    Prefer structure (historic take parented under a prior student take) over a
    prior-submission scan, so in-flight retakes on a closed class assessment are
    not mistaken for first takes and force-submitted.
    """
    if attempt is None or not attempt.user_id:
        return False
    m = _models()
    template = course_template_assessment(
        template or getattr(attempt, "assessment", None)
    )
    if template is None:
        return False

    take = getattr(attempt, "assessment", None)
    if take is not None and take.user_id and take.parent_assessment_id:
        # First take parents to the course template; retakes parent to a prior take.
        if int(take.parent_assessment_id) != int(template.id):
            return True

    return (
        attempts_qs_for_template(template)
        .filter(
            user_id=attempt.user_id,
            status=m.StudentAssessmentAttempt.STATUS_SUBMITTED,
        )
        .exclude(pk=attempt.pk)
        .exists()
    )


def attempt_may_continue_while_closed(attempt, template, student) -> bool:
    """Allow an in-flight take on a closed class assessment (retake / grant)."""
    if attempt is None:
        return False
    if attempt_is_retake(attempt, template):
        return True
    from .student_assessment_actions import student_has_open_retake

    return student_has_open_retake(template, student)


def discard_unstarted_attempt(attempt) -> bool:
    """
    Delete a ready attempt that was never started (in_progress).
    Returns True if deleted.
    """
    m = _models()
    if attempt is None:
        return False
    if attempt.status != m.StudentAssessmentAttempt.STATUS_READY:
        return False

    take = attempt.assessment
    branch = attempt.branch
    owner = attempt.user
    attempt_pk = attempt.pk
    # Problems/answers may lack ON DELETE CASCADE (unmanaged schema).
    problem_ids = list(
        m.StudentAssessmentProblem.objects.filter(attempt_id=attempt_pk).values_list(
            "id", flat=True
        )
    )
    if problem_ids:
        m.StudentAssessmentAnswer.objects.filter(problem_id__in=problem_ids).delete()
        m.StudentAssessmentProblem.objects.filter(id__in=problem_ids).delete()
    m.StudentAssessmentAttempt.objects.filter(pk=attempt_pk).delete()

    if take is not None and take.user_id and getattr(take, "is_historic", False):
        still_used = m.StudentAssessmentAttempt.objects.filter(
            assessment_id=take.id
        ).exists()
        if not still_used:
            m.Assessment.objects.filter(pk=take.id).delete()

    if branch is not None:
        try:
            from .util import send_to_trash

            send_to_trash(branch, owner)
        except Exception:
            logger.exception(
                "Could not trash branch %s for discarded attempt %s",
                getattr(branch, "pk", None),
                attempt_pk,
            )
    return True


def _create_question_folder(student, assessment_folder, slot_index: int, title: str):
    m = _models()
    safe_title = (title or "Question").strip() or "Question"
    name = f"Q{slot_index} - {safe_title}"[:255]
    return m.BranchGroup.objects.create(
        name=name,
        owner=student,
        parent=assessment_folder,
        folder_type="folder",
        order=f"{slot_index:04d}_{safe_title}"[:255],
    )


def _create_student_take_assessment(template, student, *, parent_take, branch):
    """
    Historic Assessment row for one student take.
    parent_take is the previous take Assessment (retake) or the course template
    (first take).
    """
    m = _models()
    parent = parent_take if parent_take is not None else template
    grade_weight = getattr(template, "grade_weight", None)
    if grade_weight is None:
        grade_weight = 1
    return m.Assessment.objects.create(
        course=template.course,
        name=template.name,
        order=None,
        parent_assessment=parent,
        user=student,
        points_weight=template.points_weight,
        grade_weight=grade_weight,
        curve_max_points=getattr(template, "curve_max_points", None),
        time_limit_minutes=getattr(template, "time_limit_minutes", None),
        status=None,
        is_historic=True,
        branch_location=branch,
        scores_released=bool(getattr(template, "scores_released", False)),
        student_release_mode=getattr(template, "student_release_mode", None)
        or "hidden",
        counts_toward_grade=bool(getattr(template, "counts_toward_grade", True)),
    )


def _ensure_take_assessment_for_attempt(template, student, attempt):
    """
    Ensure a legacy attempt (assessment_id = course template) has a historic
    take Assessment row, and point the attempt at it.
    """
    m = _models()
    current = attempt.assessment
    if current is not None and current.user_id:
        return current

    folder = attempt.branch
    if folder is None:
        folder = _create_take_folder(student, template.course, template.name, 1)

    existing = m.Assessment.objects.filter(branch_location=folder).first()
    if existing is not None:
        if attempt.assessment_id != existing.id:
            attempt.assessment = existing
            attempt.save(update_fields=["assessment"])
        return existing

    take = _create_student_take_assessment(
        template,
        student,
        parent_take=template,
        branch=folder,
    )
    attempt.assessment = take
    attempt.save(update_fields=["assessment"])
    return take


@transaction.atomic
def generate_attempt_for_student(parent_assessment, student, enrollment, *, force_new=False):
    """
    Assemble + freeze a unique attempt for one student.
    Each take gets its own historic Assessment row:
      - first take: parent_assessment → course template
      - retake: parent_assessment → previous take Assessment
    Problems are freshly generated for every new take.
    """
    m = _models()
    template = course_template_assessment(parent_assessment) or parent_assessment

    prior_attempts = list(
        attempts_qs_for_template(template)
        .filter(enrollment=enrollment)
        .select_related("assessment")
        .order_by("id")
    )
    if not force_new and prior_attempts:
        latest = prior_attempts[-1]
        if latest.status != m.StudentAssessmentAttempt.STATUS_SUBMITTED:
            return latest, False
        # Submitted and not forcing a retake → reuse
        return latest, False

    previous_take = None
    if prior_attempts:
        prev_attempt = prior_attempts[-1]
        prev_a = prev_attempt.assessment
        if prev_a is not None and prev_a.user_id:
            previous_take = prev_a
        else:
            # Legacy attempts pointed at the course template. Promote them to a
            # historic take row so the next retake can parent to that take.
            previous_take = _ensure_take_assessment_for_attempt(
                template, student, prev_attempt
            )

    take_index = len(prior_attempts) + 1
    course = template.course
    assembled = assemble_practice_test(
        template,
        actor_user=None,
        allow_status_mutation=False,
    )
    problems = assembled.get("problems") or []

    assessment_folder = _create_take_folder(
        student, course, template.name, take_index
    )
    take_assessment = _create_student_take_assessment(
        template,
        student,
        parent_take=previous_take if previous_take is not None else template,
        branch=assessment_folder,
    )

    now = timezone.now()
    attempt = m.StudentAssessmentAttempt.objects.create(
        user=student,
        enrollment=enrollment,
        assessment=take_assessment,
        course=course,
        status=m.StudentAssessmentAttempt.STATUS_READY,
        branch=assessment_folder,
        creation_date=now,
    )

    for inst in problems:
        answer_key, render_payload, answer_fields, body_html = _freeze_instance(inst)
        slot = int(inst.get("slot_index") or 0)
        title = inst.get("title") or f"Question {slot}"
        q_folder = _create_question_folder(student, assessment_folder, slot, title)
        max_pts = 0.0
        for f in answer_key.get("answer_fields") or []:
            try:
                max_pts += float(f.get("points") or 0)
            except (TypeError, ValueError):
                pass
        m.StudentAssessmentProblem.objects.create(
            attempt=attempt,
            slot_index=slot,
            section_name=inst.get("section_name"),
            title=title,
            source_problem_id=inst.get("problem_id"),
            body_html=body_html,
            render_payload=render_payload,
            answer_key=answer_key,
            answer_fields=answer_fields,
            max_points=max_pts,
            branch=q_folder,
        )

    return attempt, True


def begin_attempt_for_student(attempt) -> object:
    """
    Mark a ready attempt in_progress.
    Per-student retake grants stay open until the student submits or the
    teacher explicitly closes the retake.
    """
    m = _models()
    if attempt.status != m.StudentAssessmentAttempt.STATUS_READY:
        return attempt

    attempt.status = m.StudentAssessmentAttempt.STATUS_IN_PROGRESS
    if attempt.started_at is None:
        attempt.started_at = timezone.now()
    attempt.save(update_fields=["status", "started_at"])
    return attempt


def get_or_create_attempt_for_student(parent_assessment, student):
    """Ensure attempt exists (sync fallback for late enrollments / retakes)."""
    m = _models()
    from .course_enrollment import get_active_enrollment
    from .student_assessment_actions import student_has_open_retake

    template = course_template_assessment(parent_assessment) or parent_assessment
    enrollment = get_active_enrollment(course=template.course, user=student)
    if enrollment is None:
        raise PermissionError("Student is not actively enrolled in this course.")

    latest = (
        attempts_qs_for_template(template)
        .filter(enrollment=enrollment)
        .order_by("-id")
        .first()
    )
    if latest and latest.status != m.StudentAssessmentAttempt.STATUS_SUBMITTED:
        return latest

    needs_retake = False
    if latest and latest.status == m.StudentAssessmentAttempt.STATUS_SUBMITTED:
        status = (template.status or "").lower().replace(" ", "_")
        needs_retake = status == "retake_available" or student_has_open_retake(
            template, student
        )
        if not needs_retake:
            return latest
    elif assessment_taking_ended(template):
        # No attempt yet and class is closed — cannot start.
        raise PermissionError("This assessment is closed.")

    attempt, _created = generate_attempt_for_student(
        template,
        student,
        enrollment,
        force_new=bool(needs_retake),
    )
    # Retake overwrite stays open until the student actually starts (→ in_progress).
    return attempt


def run_generation_job(job_id: int):
    """Worker body: generate attempts for all active enrollments."""
    close_old_connections()
    m = _models()
    try:
        job = m.AssessmentGenerationJob.objects.select_related(
            "assessment", "assessment__course"
        ).get(pk=job_id)
    except m.AssessmentGenerationJob.DoesNotExist:
        return

    assessment = job.assessment
    if assessment is None:
        job.status = m.AssessmentGenerationJob.STATUS_FAILED
        job.error_message = "Assessment missing."
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at"])
        return

    job.status = m.AssessmentGenerationJob.STATUS_RUNNING
    job.save(update_fields=["status"])

    enrollments = _active_enrollments_for_course(assessment.course)
    job.total_students = len(enrollments)
    job.completed_students = 0
    job.save(update_fields=["total_students", "completed_students"])

    errors = []
    for enrollment in enrollments:
        try:
            generate_attempt_for_student(assessment, enrollment.user, enrollment)
        except Exception as exc:
            logger.exception(
                "Failed generating attempt assessment=%s student=%s",
                assessment.id,
                enrollment.user_id,
            )
            errors.append(f"user {enrollment.user_id}: {exc}")
        job.completed_students = (job.completed_students or 0) + 1
        job.save(update_fields=["completed_students"])

    job.finished_at = timezone.now()
    if errors:
        job.status = m.AssessmentGenerationJob.STATUS_FAILED
        job.error_message = "; ".join(errors)[:4000]
    else:
        job.status = m.AssessmentGenerationJob.STATUS_COMPLETE
        job.error_message = None
    job.save(update_fields=["status", "error_message", "finished_at"])


def start_generation_job(parent_assessment):
    """Create a job row and kick an async worker after commit."""
    m = _models()
    if generation_job_blocks_edits(parent_assessment):
        return latest_generation_job(parent_assessment)

    enrollments = _active_enrollments_for_course(parent_assessment.course)
    job = m.AssessmentGenerationJob.objects.create(
        assessment=parent_assessment,
        status=m.AssessmentGenerationJob.STATUS_PENDING,
        started_at=timezone.now(),
        total_students=len(enrollments),
        completed_students=0,
    )
    job_id = job.id

    def _spawn():
        t = threading.Thread(
            target=run_generation_job,
            args=(job_id,),
            name=f"assessment-gen-{job_id}",
            daemon=True,
        )
        t.start()

    transaction.on_commit(_spawn)
    return job


def _active_enrollments_for_course(course):
    m = _models()
    return list(
        m.StudentCourseEnrollment.objects.filter(
            course=course,
            status=m.StudentCourseEnrollment.STATUS_ACTIVE,
            user__user_type="Student",
        ).select_related("user")
    )


def client_problems_for_attempt(attempt, *, include_saved_answers: bool = True) -> list[dict]:
    m = _models()
    problems = list(
        m.StudentAssessmentProblem.objects.filter(attempt=attempt).order_by(
            "slot_index", "id"
        )
    )
    answers_by_problem = {}
    if include_saved_answers:
        for ans in m.StudentAssessmentAnswer.objects.filter(
            problem_id__in=[p.id for p in problems]
        ):
            answers_by_problem.setdefault(ans.problem_id, {})[ans.field_token] = ans.content

    out = []
    for p in problems:
        payload = p.render_payload or {}
        out.append(
            {
                "problem_row_id": p.id,
                "slot_index": p.slot_index,
                "section_name": p.section_name,
                "title": p.title,
                "source_problem_id": p.source_problem_id,
                "body_html": p.body_html,
                "answer_fields": _client_fields_from_problem(p),
                "loaded_segments": _client_segments_from_problem(p),
                "from_problem_set": payload.get("from_problem_set"),
                "student_answers": answers_by_problem.get(p.id) or {},
            }
        )
    return out


def upsert_answers(attempt, answers_payload: list[dict] | dict):
    """
    answers_payload: list of {problem_row_id, student_answers: {token: value}}
    or map problem_row_id -> student_answers.
    """
    m = _models()
    if isinstance(answers_payload, dict) and "problems" in answers_payload:
        items = answers_payload["problems"]
    elif isinstance(answers_payload, list):
        items = answers_payload
    else:
        items = [
            {"problem_row_id": int(k), "student_answers": v}
            for k, v in (answers_payload or {}).items()
        ]

    problem_ids = {
        p.id: p
        for p in m.StudentAssessmentProblem.objects.filter(attempt=attempt)
    }
    for item in items:
        if not isinstance(item, dict):
            continue
        pid = item.get("problem_row_id") or item.get("problem_id")
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        problem = problem_ids.get(pid)
        if not problem:
            continue
        student_answers = item.get("student_answers") or {}
        if not isinstance(student_answers, dict):
            continue
        for token, content in student_answers.items():
            token = str(token or "").strip()
            if not token:
                continue
            existing = m.StudentAssessmentAnswer.objects.filter(
                problem=problem, field_token=token
            ).first()
            payload = content if content is not None else None
            if isinstance(payload, (dict, list)):
                pass
            else:
                payload = {"value": payload}
            if existing:
                existing.content = payload
                existing.save(update_fields=["content"])
            else:
                m.StudentAssessmentAnswer.objects.create(
                    problem=problem,
                    field_token=token,
                    content=payload,
                )


@transaction.atomic
def submit_and_grade_attempt(attempt):
    """
    One-shot auto-grade. Raises ValueError if already graded.
    Returns summary dict.
    """
    m = _models()
    attempt = m.StudentAssessmentAttempt.objects.select_for_update().get(pk=attempt.pk)
    if attempt.auto_graded_at is not None:
        raise ValueError("This assessment has already been graded and cannot be re-scored automatically.")

    problems = list(
        m.StudentAssessmentProblem.objects.filter(attempt=attempt)
        .order_by("slot_index", "id")
        .select_for_update()
    )
    answers = {
        (a.problem_id, a.field_token): a
        for a in m.StudentAssessmentAnswer.objects.filter(
            problem_id__in=[p.id for p in problems]
        )
    }

    earned_total = 0.0
    max_total = 0.0
    any_manual = False
    problem_results = []

    for problem in problems:
        key = problem.answer_key or {}
        entities = key.get("answer_fields") or []
        context = key.get("all_entities") or key.get("loaded_segments") or []
        student_answers = {}
        for f in entities:
            if not isinstance(f, dict):
                continue
            token = str(f.get("sequence_token") or f.get("token") or "").strip()
            if not token:
                continue
            ans = answers.get((problem.id, token))
            if ans and ans.content is not None:
                content = ans.content
                if isinstance(content, dict) and set(content.keys()) == {"value"}:
                    student_answers[token] = content["value"]
                else:
                    student_answers[token] = content

        graded = grade_entities_payload(entities, context, student_answers)
        p_earned = float(graded.get("earned_total") or 0)
        p_max = float(graded.get("max_total") or 0)
        earned_total += p_earned
        max_total += p_max
        requires_manual = False
        for item in graded.get("items") or []:
            token = str(item.get("sequence_token") or item.get("token") or "").strip()
            if not token:
                continue
            if item.get("requires_manual_grading"):
                requires_manual = True
                any_manual = True
            ans = answers.get((problem.id, token))
            detail = {
                k: item.get(k)
                for k in (
                    "earned",
                    "auto_earned",
                    "max",
                    "detail",
                    "fully_correct",
                    "requires_manual_grading",
                    "archetype",
                    "label",
                )
            }
            # Never persist expected_answers into student-visible detail stores for take UI;
            # teacher review can re-read answer_key later.
            auto_pts = item.get("auto_earned")
            if auto_pts is None:
                auto_pts = item.get("earned")
            try:
                auto_pts_f = float(auto_pts) if auto_pts is not None else None
            except (TypeError, ValueError):
                auto_pts_f = None
            try:
                pts_f = float(item.get("earned")) if item.get("earned") is not None else None
            except (TypeError, ValueError):
                pts_f = None
            if ans:
                ans.points_score = pts_f
                ans.auto_points_score = auto_pts_f
                ans.detail = detail
                ans.save(update_fields=["points_score", "auto_points_score", "detail"])
            else:
                m.StudentAssessmentAnswer.objects.create(
                    problem=problem,
                    field_token=token,
                    content=None,
                    points_score=pts_f,
                    auto_points_score=auto_pts_f,
                    detail=detail,
                )

        problem.earned_points = p_earned
        problem.max_points = p_max
        problem.requires_manual_grading = requires_manual
        problem.save(
            update_fields=["earned_points", "max_points", "requires_manual_grading"]
        )
        problem_results.append(
            {
                "problem_row_id": problem.id,
                "slot_index": problem.slot_index,
                "title": problem.title,
                "earned": p_earned,
                "max": p_max,
                "requires_manual_grading": requires_manual,
            }
        )

    now = timezone.now()
    attempt.earned_points = earned_total
    attempt.max_points = max_total
    attempt.auto_graded_at = now
    attempt.submitted_at = now
    attempt.status = m.StudentAssessmentAttempt.STATUS_SUBMITTED
    if attempt.started_at is None:
        attempt.started_at = now
    attempt.save(
        update_fields=[
            "earned_points",
            "max_points",
            "auto_graded_at",
            "submitted_at",
            "status",
            "started_at",
        ]
    )

    _upsert_final_grade(attempt)

    if attempt.user_id and attempt.assessment_id:
        from .student_assessment_actions import clear_student_open_retake

        template = course_template_assessment(attempt.assessment)
        if template is not None:
            clear_student_open_retake(template, attempt.user)

    if any_manual and attempt.assessment_id:
        _notify_teacher_manual_grading(attempt)

    return {
        "earned_total": earned_total,
        "max_total": max_total,
        "problems": problem_results,
        "requires_manual_grading": any_manual,
    }


def _upsert_final_grade(attempt):
    """
    Persist FinalGradeCalculation for this enrollment+template using the
    attempt that counts under Retake assessment scoring. Voided attempts are
    ignored (e.g. "latest" falls back to the prior non-voided take).
    """
    m = _models()
    if not attempt.enrollment_id or not attempt.assessment_id:
        return
    take = attempt.assessment
    template = course_template_assessment(take) or take
    weight = 1
    if template is not None:
        raw = getattr(template, "grade_weight", None)
        if raw is None:
            raw = getattr(template, "points_weight", None)
        if raw is not None:
            try:
                weight = int(round(float(raw)))
            except (TypeError, ValueError):
                weight = 1
    if weight < 0:
        weight = 0

    template_id = template.id if template is not None else attempt.assessment_id

    from .assessment_options import select_counting_attempt

    siblings = list(
        attempts_qs_for_template(template)
        .filter(
            enrollment_id=attempt.enrollment_id,
            status=m.StudentAssessmentAttempt.STATUS_SUBMITTED,
            score_voided=False,
        )
        .order_by("id")
    )
    counting = select_counting_attempt(siblings, template)
    if counting is None:
        m.FinalGradeCalculation.objects.filter(
            enrollment_id=attempt.enrollment_id,
            assessment_id=template_id,
        ).delete()
        return

    existing = m.FinalGradeCalculation.objects.filter(
        enrollment_id=attempt.enrollment_id,
        assessment_id=template_id,
    ).first()
    if existing:
        existing.assessment_grade_points = counting.earned_points
        existing.assessment_grade_max_points = counting.max_points
        existing.weight = weight
        existing.course_id = counting.course_id
        existing.user_id = counting.user_id
        existing.save(
            update_fields=[
                "assessment_grade_points",
                "assessment_grade_max_points",
                "weight",
                "course",
                "user",
            ]
        )
    else:
        m.FinalGradeCalculation.objects.create(
            course_id=counting.course_id,
            user_id=counting.user_id,
            assessment_id=template_id,
            enrollment_id=counting.enrollment_id,
            weight=weight,
            assessment_grade_points=counting.earned_points,
            assessment_grade_max_points=counting.max_points,
        )


def _notify_teacher_manual_grading(attempt):
    from .notifications import create_notification

    m = _models()
    course = attempt.course
    teachers = m.UsersInCourse.objects.filter(
        course=course, user__user_type="Teacher", user__isnull=False
    ).select_related("user")
    student = attempt.user
    title = (
        f"Manual grading needed: {student.username} — "
        f"{attempt.assessment.name if attempt.assessment else 'assessment'}"
    )
    content = {
        "course_id": course.id if course else None,
        "assessment_id": attempt.assessment_id,
        "attempt_id": attempt.id,
        "student_id": student.user_id,
        "message": "Some answers require teacher review (e.g. long answer / canvas).",
    }
    for row in teachers:
        create_notification(
            row.user,
            title=title,
            content=content,
            reason="assessment",
            sender=student,
        )


def open_takeable_assessments_for_student(student) -> list[dict]:
    """Dashboard rows: assessments the student may start or continue."""
    m = _models()

    enrollments = list(
        m.StudentCourseEnrollment.objects.filter(
            user=student,
            status=m.StudentCourseEnrollment.STATUS_ACTIVE,
        ).select_related("course")
    )
    rows = []
    now = timezone.now()
    for enr in enrollments:
        assessments = m.Assessment.objects.filter(
            course=enr.course,
            parent_assessment__isnull=True,
            user__isnull=True,
        ).exclude(status__in=("deleted", "hidden"))
        for assessment in assessments:
            attempts = list(
                m.StudentAssessmentAttempt.objects.filter(
                    enrollment=enr, assessment=assessment
                ).order_by("id")
            )
            if not student_may_start_attempt(
                assessment, student, attempts, now=now
            ):
                continue
            attempt = attempts[-1] if attempts else None
            _start, end = assessment_window_bounds(assessment)
            window_open = upcoming_window_contains(assessment, now=now)
            remaining_seconds = None
            window_ends_at = None
            if window_open and end is not None:
                remaining_seconds = max(0, int((end - now).total_seconds()))
                window_ends_at = end.isoformat()
            rows.append(
                {
                    "course_id": enr.course_id,
                    "course_name": enr.course.name if enr.course else "",
                    "assessment_id": assessment.id,
                    "assessment_name": assessment.name,
                    "attempt_status": attempt.status if attempt else None,
                    "display_status": student_facing_assessment_status(
                        assessment, now=now
                    ),
                    "window_ends_at": window_ends_at,
                    "remaining_seconds": remaining_seconds,
                }
            )
    return rows


def job_status_payload(assessment) -> dict | None:
    job = latest_generation_job(assessment)
    if not job:
        return None
    return {
        "id": job.id,
        "status": job.status,
        "total_students": job.total_students,
        "completed_students": job.completed_students,
        "error_message": job.error_message,
        "blocks_edits": job.status
        in (
            _models().AssessmentGenerationJob.STATUS_PENDING,
            _models().AssessmentGenerationJob.STATUS_RUNNING,
        ),
    }
