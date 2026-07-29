"""
Teacher grades: score visibility, release, unfinished manual grading, rescore.
"""

from __future__ import annotations

import json
import re

from django.utils import timezone

from .student_attempts import _aware, _upsert_final_grade


def _models():
    from . import models as m
    return m


def assessment_window_ended(assessment, *, now=None) -> bool:
    """True when the assessment has a window that has passed, or no window and status closed."""
    now = _aware(now) or timezone.now()
    end = _aware(getattr(assessment, "end_time", None))
    if end is not None:
        return now > end
    status = (assessment.status or "").lower()
    return status in ("closed", "submitted")


def attempt_duration_seconds(attempt, *, now=None) -> int | None:
    """
    Elapsed take time in whole seconds from started_at to submitted_at
    (or now if still in progress). None if not started.
    """
    started = _aware(getattr(attempt, "started_at", None))
    if started is None:
        return None
    end = _aware(getattr(attempt, "submitted_at", None))
    if end is None:
        end = _aware(now) or timezone.now()
    secs = int((end - started).total_seconds())
    return max(0, secs)


def format_duration_seconds(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if total < 0:
        total = 0
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def student_submission_counts_for_assessment(assessment) -> tuple[int, int]:
    """
    Returns (submitted_count, student_count) for the grades overview.

    student_count: unique students with any attempt on this assessment.
    submitted_count: students who have ≥1 submitted attempt and are not
    currently working on a ready/in_progress retake (those count as 0 until done).
    """
    from .student_attempts import attempts_qs_for_template

    m = _models()
    attempts = list(
        attempts_qs_for_template(assessment).values("user_id", "status")
    )
    by_user: dict[int, set[str]] = {}
    for row in attempts:
        uid = row.get("user_id")
        if uid is None:
            continue
        by_user.setdefault(uid, set()).add(str(row.get("status") or ""))

    student_count = len(by_user)
    submitted_count = 0
    for statuses in by_user.values():
        has_submitted = m.StudentAssessmentAttempt.STATUS_SUBMITTED in statuses
        actively_retaking = (
            m.StudentAssessmentAttempt.STATUS_READY in statuses
            or m.StudentAssessmentAttempt.STATUS_IN_PROGRESS in statuses
        )
        if has_submitted and not actively_retaking:
            submitted_count += 1
    return submitted_count, student_count


def unfinished_manual_grading(assessment) -> list[dict]:
    """
    Submitted attempts that still need teacher scoring on manual fields.
    Returns [{attempt_id, student_id, username, formal_name, questions: [...]}]
    Voided attempts are ignored.
    """
    from .dashboard import user_roster_formal_name
    from .student_attempts import attempts_qs_for_template

    m = _models()
    attempts = (
        attempts_qs_for_template(assessment)
        .filter(
            status=m.StudentAssessmentAttempt.STATUS_SUBMITTED,
            score_voided=False,
        )
        .select_related("user")
        .order_by(
            "user__user_last_name",
            "user__user_first_name",
            "user__username",
            "id",
        )
    )
    rows = []
    for attempt in attempts:
        pending = list(
            m.StudentAssessmentProblem.objects.filter(
                attempt=attempt,
                requires_manual_grading=True,
            ).order_by("slot_index", "id")
        )
        if not pending:
            continue
        user = attempt.user
        rows.append(
            {
                "attempt_id": attempt.id,
                "student_id": attempt.user_id,
                "username": user.username if user else "?",
                "formal_name": user_roster_formal_name(user),
                "first_name": (getattr(user, "user_first_name", None) or "").strip()
                if user
                else "",
                "last_name": (getattr(user, "user_last_name", None) or "").strip()
                if user
                else "",
                "display_name": (getattr(user, "user_display_name", None) or "").strip()
                if user
                else "",
                "questions": [
                    {
                        "problem_id": p.id,
                        "slot_index": p.slot_index,
                        "title": p.title or f"Question {p.slot_index}",
                    }
                    for p in pending
                ],
            }
        )
    return rows


def manual_batch_review_payload(assessment) -> dict:
    """
    Questions that still need manual grading across students, ordered by
    question number then student (last, first, username).
    Each item is one (student, problem) pair for the batch review page.
    """
    from .student_attempts import get_attempt_for_template

    unfinished = unfinished_manual_grading(assessment)
    items = []
    for row in unfinished:
        attempt = get_attempt_for_template(assessment, row["attempt_id"])
        if attempt is None:
            continue
        pending_ids = {q["problem_id"] for q in row["questions"]}
        if not pending_ids:
            continue
        payload = teacher_review_payload(attempt)
        student = {
            "username": row.get("username") or "?",
            "first_name": row.get("first_name") or "",
            "last_name": row.get("last_name") or "",
            "display_name": row.get("display_name") or "",
            "formal_name": row.get("formal_name") or "",
        }
        for problem in payload.get("problems") or []:
            if problem.get("problem_row_id") not in pending_ids:
                continue
            items.append(
                {
                    "attempt_id": attempt.id,
                    "student_id": row.get("student_id"),
                    "student": student,
                    "problem": problem,
                }
            )

    items.sort(
        key=lambda it: (
            int(it.get("problem", {}).get("slot_index") or 0),
            (it.get("student", {}).get("last_name") or "").lower(),
            (it.get("student", {}).get("first_name") or "").lower(),
            (it.get("student", {}).get("username") or "").lower(),
            int(it.get("attempt_id") or 0),
        )
    )
    return {
        "assessment_id": assessment.id,
        "item_count": len(items),
        "items": items,
    }


def assessment_grade_question_choices(assessment) -> list[dict]:
    """
    Distinct question slots/titles seen on submitted attempts for this assessment.
    Used by the grades roster dropdown and the question-batch switcher.
    """
    from .student_attempts import attempts_qs_for_template

    m = _models()
    attempt_ids = list(
        attempts_qs_for_template(assessment)
        .filter(
            status=m.StudentAssessmentAttempt.STATUS_SUBMITTED,
            score_voided=False,
        )
        .values_list("id", flat=True)
    )
    if not attempt_ids:
        return []
    by_slot: dict[int, str] = {}
    for slot, title in (
        m.StudentAssessmentProblem.objects.filter(attempt_id__in=attempt_ids)
        .order_by("slot_index", "id")
        .values_list("slot_index", "title")
    ):
        try:
            slot_i = int(slot)
        except (TypeError, ValueError):
            continue
        if slot_i in by_slot:
            continue
        by_slot[slot_i] = (title or "").strip() or f"Question {slot_i}"
    return [
        {"slot_index": slot, "title": by_slot[slot]}
        for slot in sorted(by_slot.keys())
    ]


def question_batch_review_payload(assessment, slot_index: int) -> dict:
    """
    One question slot for each student, using only the attempt that counts
    toward the grade (highest or latest per Retake assessment scoring;
    voided attempts ignored). Ordered by student name.
    """
    from .assessment_options import select_counting_attempt
    from .dashboard import user_roster_formal_name
    from .student_attempts import attempts_qs_for_template, get_attempt_for_template

    m = _models()
    try:
        slot_i = int(slot_index)
    except (TypeError, ValueError):
        return {
            "assessment_id": assessment.id,
            "slot_index": None,
            "title": "",
            "item_count": 0,
            "items": [],
            "question_choices": assessment_grade_question_choices(assessment),
        }

    attempts = list(
        attempts_qs_for_template(assessment)
        .select_related("user")
        .order_by(
            "user__user_last_name",
            "user__user_first_name",
            "user__username",
            "id",
        )
    )
    by_user: dict[int, list] = {}
    for attempt in attempts:
        uid = attempt.user_id
        if uid is None:
            continue
        by_user.setdefault(uid, []).append(attempt)

    items = []
    current_title = ""
    for uid, group in by_user.items():
        attempt = select_counting_attempt(group, assessment)
        if attempt is None:
            continue
        problem_row = (
            m.StudentAssessmentProblem.objects.filter(
                attempt=attempt,
                slot_index=slot_i,
            )
            .order_by("id")
            .first()
        )
        if problem_row is None:
            continue
        # "Received a score" — graded problem row (0 is still a score).
        if problem_row.earned_points is None and problem_row.max_points is None:
            continue
        live = get_attempt_for_template(assessment, attempt.id)
        if live is None:
            continue
        payload = teacher_review_payload(live)
        problem = next(
            (
                p
                for p in (payload.get("problems") or [])
                if p.get("problem_row_id") == problem_row.id
            ),
            None,
        )
        if problem is None:
            continue
        if not current_title:
            current_title = (
                str(problem.get("title") or "").strip()
                or problem_row.title
                or f"Question {slot_i}"
            )
        user = attempt.user
        items.append(
            {
                "attempt_id": attempt.id,
                "student_id": uid,
                "student": {
                    "username": user.username if user else "?",
                    "first_name": (getattr(user, "user_first_name", None) or "").strip()
                    if user
                    else "",
                    "last_name": (getattr(user, "user_last_name", None) or "").strip()
                    if user
                    else "",
                    "display_name": (
                        getattr(user, "user_display_name", None) or ""
                    ).strip()
                    if user
                    else "",
                    "formal_name": user_roster_formal_name(user),
                },
                "problem": problem,
            }
        )

    items.sort(
        key=lambda it: (
            (it.get("student", {}).get("last_name") or "").lower(),
            (it.get("student", {}).get("first_name") or "").lower(),
            (it.get("student", {}).get("username") or "").lower(),
            int(it.get("attempt_id") or 0),
        )
    )

    choices = assessment_grade_question_choices(assessment)
    return {
        "assessment_id": assessment.id,
        "slot_index": slot_i,
        "title": current_title or next(
            (c["title"] for c in choices if c["slot_index"] == slot_i),
            f"Question {slot_i}",
        ),
        "item_count": len(items),
        "items": items,
        "question_choices": choices,
    }


def assessment_manual_grading_complete(assessment) -> bool:
    return not unfinished_manual_grading(assessment)


def scores_auto_visible(assessment, *, now=None) -> bool:
    """
    Scores become visible without an explicit release when the teacher has closed
    the assessment, the window has timed out, and all manual grading is done.
    """
    status = (assessment.status or "").lower()
    if status not in ("closed", "submitted"):
        return False
    if not assessment_window_ended(assessment, now=now):
        return False
    return assessment_manual_grading_complete(assessment)


RELEASE_MODE_HIDDEN = "hidden"
RELEASE_MODE_SCORES_ONLY = "scores_only"
RELEASE_MODE_FULL_REVIEW = "full_review"
RELEASE_MODES = frozenset(
    {RELEASE_MODE_HIDDEN, RELEASE_MODE_SCORES_ONLY, RELEASE_MODE_FULL_REVIEW}
)

AGGREGATION_EQUAL_WEIGHT = "equal_weight"
AGGREGATION_SUM_POINTS = "sum_points"
AGGREGATION_MODES = frozenset({AGGREGATION_EQUAL_WEIGHT, AGGREGATION_SUM_POINTS})


def assessment_release_mode(assessment) -> str:
    """
    Student visibility is driven by the 'Student view of graded assessments' option
    (course default or assessment override): scores_only | full_review.
    """
    from .assessment_options import (
        CHOICE_VIEW_FULL_REVIEW,
        GROUP_STUDENT_VIEW,
        resolved_assessment_option,
    )

    choice = resolved_assessment_option(assessment, GROUP_STUDENT_VIEW)
    if choice == CHOICE_VIEW_FULL_REVIEW:
        return RELEASE_MODE_FULL_REVIEW
    return RELEASE_MODE_SCORES_ONLY


def student_view_label(assessment) -> str:
    if assessment_release_mode(assessment) == RELEASE_MODE_FULL_REVIEW:
        return "Student Answers Review Enabled"
    return "Scores Only"


def sync_assessment_release_mode_from_options(assessment) -> str:
    """Persist student_release_mode / scores_released to match the active option."""
    mode = assessment_release_mode(assessment)
    assessment.student_release_mode = mode
    assessment.scores_released = True
    if getattr(assessment, "scores_released_at", None) is None:
        assessment.scores_released_at = timezone.now()
    assessment.save(
        update_fields=["student_release_mode", "scores_released", "scores_released_at"]
    )
    return mode


def assessment_counts_toward_grade(assessment) -> bool:
    if hasattr(assessment, "counts_toward_grade"):
        return bool(assessment.counts_toward_grade)
    return True


def scores_released_flag(assessment) -> bool:
    return assessment_release_mode(assessment) != RELEASE_MODE_HIDDEN


def scores_visible_for_assessment(assessment, *, now=None) -> bool:
    mode = assessment_release_mode(assessment)
    if mode in (RELEASE_MODE_SCORES_ONLY, RELEASE_MODE_FULL_REVIEW):
        return True
    return scores_auto_visible(assessment, now=now)


def student_may_review_attempt(assessment, attempt=None, *, now=None) -> bool:
    """True when student can open a read-only questions+answers review."""
    from .assessment_options import student_may_view_submissions

    if not student_may_view_submissions(assessment):
        return False
    if attempt is None:
        return scores_visible_for_assessment(assessment, now=now)
    # Must be the student's own submitted attempt
    if getattr(attempt, "status", None) not in ("submitted",) and not getattr(
        attempt, "auto_graded_at", None
    ):
        return False
    return scores_visible_to_student(assessment, attempt, now=now)


def scores_visible_to_student(assessment, attempt=None, *, now=None) -> bool:
    if not scores_visible_for_assessment(assessment, now=now):
        return False
    if attempt is None:
        return True
    # Per-attempt: hide scores/review while any question still needs manual points,
    # even when the assessment release option is already scores_only / full_review.
    m = _models()
    if m.StudentAssessmentProblem.objects.filter(
        attempt=attempt, requires_manual_grading=True
    ).exists():
        return False
    return True


def apply_assessment_release(
    assessment,
    *,
    mode: str,
    counts_toward_grade: bool = True,
    close_assessment: bool = False,
    force: bool = False,
) -> dict:
    """
    Set student release mode for a parent assessment.
    mode: hidden | scores_only | full_review
    When releasing (not hidden) while unfinished manual grading and force is False,
    return a blocked payload.
    Optionally close the assessment if it is still open/upcoming/active.
    """
    mode = str(mode or "").strip().lower()
    if mode not in RELEASE_MODES:
        return {"success": False, "error": f"Invalid release mode: {mode}"}

    unfinished = unfinished_manual_grading(assessment) if mode != RELEASE_MODE_HIDDEN else []
    if unfinished and mode != RELEASE_MODE_HIDDEN and not force:
        return {
            "success": False,
            "blocked": True,
            "unfinished": unfinished,
            "error": (
                "Manual grading is unfinished for some students. "
                "Confirm force-release to publish partial scores."
            ),
        }

    assessment.student_release_mode = mode
    assessment.counts_toward_grade = bool(counts_toward_grade)
    assessment.scores_released = mode != RELEASE_MODE_HIDDEN
    assessment.scores_released_at = timezone.now() if mode != RELEASE_MODE_HIDDEN else None
    update_fields = [
        "student_release_mode",
        "counts_toward_grade",
        "scores_released",
        "scores_released_at",
    ]

    closed = False
    if close_assessment and mode != RELEASE_MODE_HIDDEN:
        status = (assessment.status or "").lower()
        if status in ("open", "upcoming", "active", "retake available"):
            assessment.status = "closed"
            assessment.modified_date = timezone.now()
            update_fields.extend(["status", "modified_date"])
            closed = True

    assessment.save(update_fields=update_fields)
    finalize_payload = None
    if closed:
        from .student_attempts import close_assessment_and_finalize_attempts

        finalize_payload = close_assessment_and_finalize_attempts(
            assessment,
            reason="release_close",
            set_status=False,  # already saved above
        )
    return {
        "success": True,
        "blocked": False,
        "unfinished": unfinished,
        "student_release_mode": mode,
        "counts_toward_grade": assessment.counts_toward_grade,
        "scores_released": assessment.scores_released,
        "scores_released_at": assessment.scores_released_at.isoformat()
        if assessment.scores_released_at
        else None,
        "closed_assessment": closed,
        "assessment_status": assessment.status,
        "finalize": finalize_payload,
    }


def release_assessment_scores(assessment, *, force: bool = False) -> dict:
    """Backward-compatible wrapper: release scores only."""
    return apply_assessment_release(
        assessment,
        mode=RELEASE_MODE_SCORES_ONLY,
        counts_toward_grade=assessment_counts_toward_grade(assessment),
        force=force,
    )


def unrelease_assessment_scores(assessment) -> dict:
    return apply_assessment_release(
        assessment,
        mode=RELEASE_MODE_HIDDEN,
        counts_toward_grade=assessment_counts_toward_grade(assessment),
        force=True,
    )


def course_grade_aggregation_mode(course) -> str:
    mode = str(getattr(course, "grade_aggregation_mode", "") or "").strip().lower()
    if mode in AGGREGATION_MODES:
        return mode
    return AGGREGATION_EQUAL_WEIGHT


def set_course_grade_aggregation_mode(course, mode: str) -> dict:
    mode = str(mode or "").strip().lower()
    if mode not in AGGREGATION_MODES:
        return {"success": False, "error": f"Invalid aggregation mode: {mode}"}
    course.grade_aggregation_mode = mode
    course.save(update_fields=["grade_aggregation_mode"])
    return {"success": True, "grade_aggregation_mode": mode}


def compute_course_total(rows: list[dict], aggregation_mode: str) -> dict:
    """
    rows: items with scores_visible, earned_points, max_points, counts_toward_grade,
    and optional grade_weight (for equal_weight / percent-of-final-grade mode).
    equal_weight: weighted average of (earned/max) using grade_weight (0 excluded).
    sum_points: sum earned / sum max for counting visible assessments.
    """
    counting = [
        r
        for r in rows
        if r.get("scores_visible")
        and r.get("counts_toward_grade", True)
        and r.get("earned_points") is not None
        and r.get("max_points") is not None
        and float(r.get("max_points") or 0) > 0
    ]
    if not counting:
        return {
            "aggregation_mode": aggregation_mode,
            "percent": None,
            "earned_sum": None,
            "max_sum": None,
            "counted": 0,
        }

    if aggregation_mode == AGGREGATION_SUM_POINTS:
        earned_sum = sum(float(r["earned_points"]) for r in counting)
        max_sum = sum(float(r["max_points"]) for r in counting)
        percent = (earned_sum / max_sum * 100.0) if max_sum else None
        return {
            "aggregation_mode": aggregation_mode,
            "percent": round(percent, 1) if percent is not None else None,
            "earned_sum": earned_sum,
            "max_sum": max_sum,
            "counted": len(counting),
        }

    # Percent-of-final-grade: relative grade_weight (default 1; 0 excluded)
    weighted = []
    for r in counting:
        try:
            w = float(r.get("grade_weight") if r.get("grade_weight") is not None else 1)
        except (TypeError, ValueError):
            w = 1.0
        if w <= 0:
            continue
        ratio = float(r["earned_points"]) / float(r["max_points"])
        weighted.append((w, ratio))
    if not weighted:
        return {
            "aggregation_mode": AGGREGATION_EQUAL_WEIGHT,
            "percent": None,
            "earned_sum": None,
            "max_sum": None,
            "counted": 0,
        }
    w_sum = sum(w for w, _ in weighted)
    avg = sum(w * ratio for w, ratio in weighted) / w_sum
    return {
        "aggregation_mode": AGGREGATION_EQUAL_WEIGHT,
        "percent": round(avg * 100.0, 1),
        "earned_sum": None,
        "max_sum": None,
        "counted": len(weighted),
    }


def assessment_template_total_points(assessment) -> float:
    """
    Best-effort total points for a parent assessment template.
    Prefers the max observed submitted attempt max_points across all takes
    (including retake historic rows); otherwise 0.
    """
    from .student_attempts import attempts_qs_for_template

    m = _models()
    agg = (
        attempts_qs_for_template(assessment)
        .filter(
            status=m.StudentAssessmentAttempt.STATUS_SUBMITTED,
            max_points__isnull=False,
            score_voided=False,
        )
        .order_by("-max_points")
        .values_list("max_points", flat=True)
        .first()
    )
    if agg is not None:
        try:
            return float(agg)
        except (TypeError, ValueError):
            pass
    return 0.0


def assessment_grade_weight(assessment) -> float:
    raw = getattr(assessment, "grade_weight", None)
    if raw is None:
        return 1.0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 1.0


def resolve_curve_max_points(assessment, *, live_total: float | None = None) -> float | None:
    """
    Curve denominator for display/edit.
    Auto-follows live total while assessment is not open and has no submissions;
    otherwise keeps stored curve_max_points (or live total if never set).
    """
    from .assessment_options import curve_allowed_for_assessment

    if not curve_allowed_for_assessment(assessment):
        return None
    if live_total is None:
        live_total = assessment_template_total_points(assessment)
    try:
        live_total = float(live_total or 0)
    except (TypeError, ValueError):
        live_total = 0.0

    m = _models()
    from .student_attempts import attempts_qs_for_template

    is_open = (assessment.status or "").lower() in (
        "open",
        "upcoming",
        "active",
        "retake available",
    )
    has_subs = attempts_qs_for_template(assessment).filter(
        status=m.StudentAssessmentAttempt.STATUS_SUBMITTED,
        score_voided=False,
    ).exists()
    locked = is_open or has_subs
    stored = getattr(assessment, "curve_max_points", None)

    if not locked:
        # Keep stored in sync with live total while unlocked
        if stored is None or abs(float(stored) - live_total) > 1e-9:
            assessment.curve_max_points = live_total
            assessment.save(update_fields=["curve_max_points"])
        return live_total

    if stored is not None:
        try:
            return float(stored)
        except (TypeError, ValueError):
            return live_total
    assessment.curve_max_points = live_total
    assessment.save(update_fields=["curve_max_points"])
    return live_total


def grades_overview_for_course(course) -> list[dict]:
    """One row per parent assessment with aggregate attempt stats."""
    m = _models()
    from .assessment_options import (
        ASSESSMENT_GRADES_OPTION_GROUPS,
        any_assessment_allows_curve,
        curve_allowed_for_assessment,
    )

    assessments = list(
        m.Assessment.objects.filter(
            course=course,
            parent_assessment__isnull=True,
            user__isnull=True,
        )
        .exclude(status="deleted")
        .order_by("order", "id")
    )
    custom_option_ids = set(
        m.AssessmentOptions.objects.filter(
            assessment_id__in=[a.id for a in assessments],
            option_type_id__in=ASSESSMENT_GRADES_OPTION_GROUPS,
        )
        .values_list("assessment_id", flat=True)
        .distinct()
    )
    show_curve_column = any_assessment_allows_curve(course)
    weight_total = sum(assessment_grade_weight(a) for a in assessments)
    points_totals = {a.id: assessment_template_total_points(a) for a in assessments}
    points_course_total = sum(points_totals.values())

    rows = []
    for a in assessments:
        submitted_count, student_count = student_submission_counts_for_assessment(a)
        unfinished = unfinished_manual_grading(a)
        mode = assessment_release_mode(a)
        weight = assessment_grade_weight(a)
        live_pts = points_totals.get(a.id, 0.0)
        curve_on = curve_allowed_for_assessment(a)
        curve_val = (
            resolve_curve_max_points(a, live_total=live_pts) if curve_on else None
        )
        weight_pct = (
            round((weight / weight_total) * 100.0, 1) if weight_total > 0 else 0.0
        )
        points_pct = (
            round((live_pts / points_course_total) * 100.0, 1)
            if points_course_total > 0
            else 0.0
        )
        rows.append(
            {
                "assessment_id": a.id,
                "name": a.name,
                "status": a.status,
                "attempt_count": student_count,
                "submitted_count": submitted_count,
                "unfinished_manual_count": len(unfinished),
                "student_release_mode": mode,
                "student_view_label": student_view_label(a),
                "counts_toward_grade": assessment_counts_toward_grade(a) and weight > 0,
                "scores_released": True,
                "scores_visible": scores_visible_for_assessment(a),
                "is_open": (a.status or "").lower() in (
                    "open",
                    "upcoming",
                    "active",
                    "retake available",
                ),
                "has_custom_options": a.id in custom_option_ids,
                "grade_weight": weight,
                "weight_percent": weight_pct,
                "assessment_total_points": live_pts,
                "points_percent": points_pct,
                "curve_allowed": curve_on,
                "curve_max_points": curve_val,
                "curve_live_total": live_pts,
            }
        )
    return rows


def grades_overview_meta(course, grade_rows: list[dict] | None = None) -> dict:
    aggregation = course_grade_aggregation_mode(course)
    from .assessment_options import any_assessment_allows_curve

    if grade_rows is None:
        grade_rows = grades_overview_for_course(course)
    show_manual = any(
        int(r.get("unfinished_manual_count") or 0) > 0 for r in grade_rows
    )
    return {
        "grade_aggregation_mode": aggregation,
        "show_weight_column": aggregation == AGGREGATION_EQUAL_WEIGHT,
        "show_points_column": aggregation == AGGREGATION_SUM_POINTS,
        "show_curve_column": any_assessment_allows_curve(course),
        "show_manual_pending_column": show_manual,
    }


def set_assessment_grade_weight(assessment, weight) -> dict:
    try:
        w = float(weight)
    except (TypeError, ValueError):
        return {"success": False, "error": "Invalid weight."}
    if w < 0:
        return {"success": False, "error": "Weight must be 0 or greater."}
    assessment.grade_weight = w
    assessment.save(update_fields=["grade_weight"])
    # weight 0 also means not counted toward grade
    if hasattr(assessment, "counts_toward_grade"):
        assessment.counts_toward_grade = w > 0
        assessment.save(update_fields=["counts_toward_grade"])
    return {"success": True, "grade_weight": w}


def set_assessment_curve_max_points(assessment, value) -> dict:
    from .assessment_options import curve_allowed_for_assessment

    if not curve_allowed_for_assessment(assessment):
        return {"success": False, "error": "Curve is not enabled for this assessment."}
    live = assessment_template_total_points(assessment)
    try:
        pts = float(value)
    except (TypeError, ValueError):
        return {"success": False, "error": "Invalid curve value."}
    if pts < 0:
        return {"success": False, "error": "Curve cannot be negative."}
    if pts > live + 1e-9 and live > 0:
        return {
            "success": False,
            "error": f"Curve cannot exceed assessment total ({live}).",
        }
    # Allow setting up to live; if live is 0, allow any non-negative until points exist
    if live > 0:
        pts = min(pts, live)
    assessment.curve_max_points = pts
    assessment.save(update_fields=["curve_max_points"])
    return {"success": True, "curve_max_points": pts, "curve_live_total": live}


def student_grades_for_course(course, student) -> dict:
    """
    Student's own submitted/graded attempts in this course.
    When retakes exist, only the counting attempt (per Retake assessment scoring)
    is included in the main grade list.
    """
    m = _models()
    from .assessment_options import select_counting_attempt
    from .student_attempts import course_template_assessment

    attempts = list(
        m.StudentAssessmentAttempt.objects.filter(
            course=course,
            user=student,
            status=m.StudentAssessmentAttempt.STATUS_SUBMITTED,
            score_voided=False,
        )
        .select_related("assessment")
        .order_by("assessment__order", "assessment_id", "id")
    )
    by_assessment = {}
    for attempt in attempts:
        if attempt.assessment_id is None:
            continue
        template = course_template_assessment(attempt.assessment)
        if template is None:
            continue
        by_assessment.setdefault(template.id, []).append(attempt)

    # Same weight denominator as the teacher Grades Weight column.
    course_assessments = list(
        m.Assessment.objects.filter(
            course=course,
            parent_assessment__isnull=True,
            user__isnull=True,
        ).exclude(status="deleted")
    )
    weight_total = sum(assessment_grade_weight(a) for a in course_assessments)

    rows = []
    for assessment_id, group in by_assessment.items():
        assessment = course_template_assessment(group[0].assessment)
        if assessment is None:
            continue
        if (assessment.status or "").lower() == "deleted":
            continue
        if assessment.user_id is not None:
            continue
        attempt = select_counting_attempt(group, assessment) or group[-1]
        visible = scores_visible_to_student(assessment, attempt)
        manual_pending = m.StudentAssessmentProblem.objects.filter(
            attempt=attempt, requires_manual_grading=True
        ).exists()
        mode = assessment_release_mode(assessment)
        counts = assessment_counts_toward_grade(assessment)
        weight = assessment_grade_weight(assessment)
        weight_pct = (
            round((weight / weight_total) * 100.0, 1) if weight_total > 0 else 0.0
        )
        rows.append(
            {
                "assessment_id": assessment.id,
                "name": assessment.name,
                "assessment_status": assessment.status,
                "attempt_id": attempt.id,
                "submitted_at": attempt.submitted_at.isoformat()
                if attempt.submitted_at
                else None,
                "scores_visible": visible,
                "earned_points": attempt.earned_points if visible else None,
                "max_points": attempt.max_points if visible else None,
                "manual_pending": manual_pending and not visible,
                "counts_toward_grade": counts and weight > 0,
                "grade_weight": weight,
                "weight_percent": weight_pct,
                "student_release_mode": mode,
                "can_review": student_may_review_attempt(assessment, attempt),
                "percent": (
                    round(
                        float(attempt.earned_points) / float(attempt.max_points) * 100.0,
                        1,
                    )
                    if visible
                    and attempt.earned_points is not None
                    and attempt.max_points
                    and float(attempt.max_points) > 0
                    else None
                ),
            }
        )
    rows.sort(key=lambda r: (r.get("name") or "").lower())
    aggregation = course_grade_aggregation_mode(course)
    total = compute_course_total(rows, aggregation)
    return {
        "rows": rows,
        "total": total,
        "grade_aggregation_mode": aggregation,
    }


def student_rows_for_assessment(assessment) -> list[dict]:
    from .dashboard import user_roster_formal_name
    from .student_assessment_actions import student_has_open_retake
    from .student_attempts import attempts_qs_for_template

    m = _models()
    attempts = list(
        attempts_qs_for_template(assessment)
        .select_related("user")
        .order_by(
            "user__user_last_name",
            "user__user_first_name",
            "user__username",
            "id",
        )
    )
    attempt_counts: dict[int, int] = {}
    attempt_numbers: dict[int, int] = {}
    per_user_ordinal: dict[int, int] = {}
    for attempt in attempts:
        uid = attempt.user_id
        if uid is None:
            continue
        attempt_counts[uid] = attempt_counts.get(uid, 0) + 1
        per_user_ordinal[uid] = per_user_ordinal.get(uid, 0) + 1
        attempt_numbers[attempt.id] = per_user_ordinal[uid]

    visible = scores_visible_for_assessment(assessment)
    rows = []
    for attempt in attempts:
        pending = list(
            m.StudentAssessmentProblem.objects.filter(
                attempt=attempt, requires_manual_grading=True
            ).values_list("slot_index", flat=True)
        )
        user = attempt.user
        uid = attempt.user_id
        orig_earned = getattr(attempt, "original_earned_points", None)
        orig_max = getattr(attempt, "original_max_points", None)
        score_adjusted = orig_earned is not None or orig_max is not None
        attempt_count = attempt_counts.get(uid, 1) if uid is not None else 1
        duration_secs = attempt_duration_seconds(attempt)
        retake_open = student_has_open_retake(assessment, user) if user else False
        from .student_attempts import attempt_is_retake

        retake_active = retake_open or (
            attempt.status
            in (
                m.StudentAssessmentAttempt.STATUS_READY,
                m.StudentAssessmentAttempt.STATUS_IN_PROGRESS,
            )
            and attempt_is_retake(attempt, assessment)
        )
        rows.append(
            {
                "attempt_id": attempt.id,
                "student_id": uid,
                "username": user.username if user else "?",
                "formal_name": user_roster_formal_name(user),
                "status": attempt.status,
                "earned_points": attempt.earned_points,
                "max_points": attempt.max_points,
                "original_earned_points": orig_earned,
                "original_max_points": orig_max,
                "score_adjusted": score_adjusted,
                "score_voided": bool(getattr(attempt, "score_voided", False)),
                "retake_open": retake_open,
                "retake_active": retake_active,
                "attempt_count": attempt_count,
                "attempt_number": attempt_numbers.get(attempt.id),
                "started_at": attempt.started_at.isoformat()
                if attempt.started_at
                else None,
                "submitted_at": attempt.submitted_at.isoformat()
                if attempt.submitted_at
                else None,
                "duration_seconds": duration_secs,
                "duration_display": format_duration_seconds(duration_secs),
                "manual_pending_slots": list(pending),
                "scores_visible": visible
                and (
                    scores_released_flag(assessment)
                    or not pending
                ),
            }
        )
    return rows


def assessment_has_retake_attempts(student_rows: list[dict]) -> bool:
    """True when any student has two or more attempts on this assessment."""
    return any(int(row.get("attempt_count") or 0) >= 2 for row in student_rows)


def _segment_display_map(loaded_segments) -> dict:
    """Map sequence_token → display string for resolving <token> refs."""
    out = {}
    for seg in loaded_segments or []:
        if not isinstance(seg, dict):
            continue
        token = str(seg.get("sequence_token") or seg.get("token") or "").strip()
        if not token:
            continue
        arch = str(seg.get("archetype") or seg.get("token") or "")
        # Skip bulky JSON manifests
        if arch.startswith(("graph", "slopeField", "canvas")):
            continue
        for key in ("latex_output", "evaluated_output", "simulated_value"):
            val = seg.get(key)
            if val is None or val == "":
                continue
            text = str(val).strip()
            if not text or text == "???" or text.startswith("{"):
                continue
            out[token] = text
            break
    return out


def _resolve_angle_tokens(text, display_map: dict) -> str:
    if text is None:
        return ""
    raw = str(text)
    if not raw or not display_map:
        return raw
    pattern = re.compile(r"(?:&lt;|<)([A-Za-z][A-Za-z0-9_]*)(?:&gt;|>)")

    def _replace(match):
        seq = match.group(1).strip()
        if seq in display_map:
            return str(display_map[seq])
        return match.group(0)

    try:
        return pattern.sub(_replace, raw)
    except Exception:
        return raw


def _field_max_points(field: dict) -> float:
    try:
        return float(field.get("points") if field.get("points") is not None else 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_field_visual_config(field: dict) -> dict | None:
    raw = field.get("evaluated_output")
    if raw in (None, ""):
        raw = field.get("simulated_value")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    return None


def _visual_preview_for_review(field: dict, student_content) -> dict | None:
    """
    Student/expected canvas pair for slope-field and graph-between-points
    in teacher/student attempt review (mirrors practice-test visual_preview).
    """
    arch = re.sub(
        r"\d+$",
        "",
        str(field.get("archetype") or field.get("token") or "").strip(),
    )
    config = _parse_field_visual_config(field)
    if not isinstance(config, dict):
        return None

    if arch == "slopeFieldGraph" and config.get("archetype") == "slopeFieldGraph":
        marks = []
        if isinstance(student_content, dict) and isinstance(student_content.get("marks"), list):
            marks = student_content.get("marks") or []
        elif isinstance(student_content, list):
            marks = student_content
        return {
            "kind": "slopeFieldGraph",
            "config": config,
            "student_marks": marks,
        }

    if arch == "graphBetweenPoints" and config.get("archetype") == "graphBetweenPoints":
        student_segs = []
        if isinstance(student_content, dict) and isinstance(student_content.get("segments"), list):
            student_segs = [
                s for s in (student_content.get("segments") or []) if isinstance(s, dict)
            ]
        # Prefer full student_draw segments (samples + dividers/markers) — same
        # source as practice-test review. Falling back to student_targets must
        # keep start_divider/end_divider or endpoint circles won't render.
        expected_segs = [
            s
            for s in (config.get("segments") or [])
            if isinstance(s, dict) and s.get("student_draw")
        ]
        if not expected_segs:
            for t in config.get("student_targets") or []:
                if not isinstance(t, dict):
                    continue
                if t.get("start") is None or t.get("end") is None:
                    continue
                expected_segs.append(
                    {
                        "id": t.get("id"),
                        "type": t.get("type") or "segment",
                        "start": t.get("start"),
                        "end": t.get("end"),
                        "start_divider": t.get("start_divider") or "none",
                        "end_divider": t.get("end_divider") or "none",
                    }
                )
        return {
            "kind": "graphBetweenPoints",
            "config": config,
            "student_segments": student_segs,
            "expected_segments": expected_segs,
        }

    return None


def _matrix_answer_expected_lines(field: dict, resolve_line) -> list | None:
    """
    Expected solve-cell lines for matrixAnswer from frozen evaluated_output JSON.
    Matches practice-test / student-answer style: \"r,c: value\".
    """
    raw = field.get("evaluated_output")
    if raw is None or raw == "":
        raw = field.get("simulated_value")
    payload = None
    if isinstance(raw, dict):
        payload = raw
    elif isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                payload = parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = None
    if not isinstance(payload, dict):
        return None
    arch_payload = str(payload.get("archetype") or "").strip()
    if arch_payload and arch_payload != "matrixAnswer":
        return None

    rows = payload.get("rows") or []
    solve_cells = payload.get("solve_cells") or []
    if not isinstance(rows, list) or not isinstance(solve_cells, list):
        return None

    lines = []
    for pair in solve_cells:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        try:
            r = int(pair[0])
            c = int(pair[1])
        except (TypeError, ValueError):
            continue
        val = ""
        if 0 <= r < len(rows) and isinstance(rows[r], (list, tuple)) and 0 <= c < len(rows[r]):
            val = rows[r][c]
        text = resolve_line(val) if val not in (None, "") else ""
        if text:
            lines.append(f"{r},{c}: {text}")
        else:
            lines.append(f"{r},{c}:")
    return lines or None


def _format_expected_for_teacher(field: dict, display_map: dict | None = None):
    """Human-readable expected answer(s) from a frozen answer_field."""
    if not isinstance(field, dict):
        return None
    if _field_max_points(field) <= 0:
        return None

    display_map = display_map or {}
    arch = str(field.get("archetype") or field.get("token") or "")
    base_arch = re.sub(r"\d+$", "", arch).strip()

    def _resolve_line(line) -> str:
        return _resolve_angle_tokens(str(line), display_map).strip()

    # MC: prefer linked latex / graph-aware option display over evaluate_output dumps.
    if base_arch == "multipleChoiceAnswer":
        return None  # caller uses expected_answer_parts / option formatting

    # matrixAnswer evaluate_output is JSON (summary + rows + solve_cells); extract cells.
    if base_arch == "matrixAnswer":
        return _matrix_answer_expected_lines(field, _resolve_line)

    # Prefer already-evaluated output (token-resolved) when present.
    raw = field.get("evaluated_output")
    if raw is None or raw == "":
        raw = field.get("simulated_value")

    if raw not in (None, ""):
        if isinstance(raw, (dict, list)):
            if isinstance(raw, dict) and raw.get("archetype") in (
                "graph",
                "graphBetweenPoints",
                "slopeFieldGraph",
                "canvas",
                "matrixAnswer",
            ):
                return None
            try:
                return [json.dumps(raw, ensure_ascii=False)]
            except (TypeError, ValueError):
                return [str(raw)]
        text = str(raw).strip()
        if text and not text.startswith("{"):
            # Multi-line expected (answersOrDne)
            lines = [_resolve_line(line) for line in text.split("\n")]
            lines = [ln for ln in lines if ln]
            if lines:
                return lines

    inputs = field.get("inputs") if isinstance(field.get("inputs"), dict) else {}
    options = inputs.get("options")
    if isinstance(options, list) and options:
        correct = []
        for opt in options:
            if not isinstance(opt, dict) or not opt.get("is_correct"):
                continue
            content = str(
                opt.get("content_resolved") or opt.get("content") or opt.get("id") or ""
            ).strip()
            content = _resolve_line(content)
            if content:
                correct.append(content)
        if correct:
            return correct

    return None


def _format_student_answer_for_teacher(
    field: dict, content, display_map: dict | None = None
) -> list:
    """Display lines for a student's saved answer (teacher review)."""
    display_map = display_map or {}
    arch = str(field.get("archetype") or field.get("token") or "")
    base_arch = re.sub(r"\d+$", "", arch).strip()

    def _resolve_line(line) -> str:
        return _resolve_angle_tokens(str(line), display_map).strip()

    if content is None:
        return []

    if base_arch == "multipleChoiceAnswer":
        # Lines come from display parts in teacher_review_payload.
        return []

    if arch.startswith("answersOrDne"):
        if isinstance(content, dict):
            if content.get("dne"):
                return ["DNE"]
            entries = content.get("entries") or []
            lines = []
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        val = entry.get("value")
                        if val not in (None, ""):
                            lines.append(_resolve_line(val))
                    elif entry not in (None, ""):
                        lines.append(_resolve_line(entry))
            return [ln for ln in lines if ln]
        if isinstance(content, str) and content.strip().upper() in ("DNE", "NONE", "N/A"):
            return ["DNE"]

    if isinstance(content, dict):
        if content.get("dne"):
            return ["DNE"]
        if "value" in content and content.get("value") not in (None, ""):
            return [_resolve_line(content.get("value"))]
        if isinstance(content.get("entries"), list):
            lines = []
            for entry in content["entries"]:
                if isinstance(entry, dict):
                    val = entry.get("value")
                    if val not in (None, ""):
                        lines.append(_resolve_line(val))
                elif entry not in (None, ""):
                    lines.append(_resolve_line(entry))
            return [ln for ln in lines if ln]
        if isinstance(content.get("selected"), list):
            return [_resolve_line(x) for x in content["selected"] if x not in (None, "")]
        if isinstance(content.get("cells"), dict):
            cells = content.get("cells") or {}
            return [f"{k}: {_resolve_line(v)}" for k, v in sorted(cells.items()) if v not in (None, "")]
        if isinstance(content.get("marks"), list):
            n = len(content.get("marks") or [])
            return [f"{n} slope mark{'s' if n != 1 else ''}"]
        if isinstance(content.get("segments"), list):
            return [f"Segments: {len(content.get('segments') or [])}"]
        try:
            return [json.dumps(content, ensure_ascii=False)]
        except Exception:
            return [str(content)]

    if isinstance(content, (list, tuple)):
        return [_resolve_line(x) for x in content if x not in (None, "")]
    text = str(content).strip()
    return [_resolve_line(text)] if text else []


def teacher_review_payload(attempt) -> dict:
    """Full attempt payload for teacher review/rescore (includes answer keys)."""
    m = _models()
    from .student_attempts import _client_segments_from_problem
    from .util import (
        _display_part_plaintext,
        _mc_answer_display_parts,
        _mc_expected_display_parts,
        _mc_selected_option_ids,
        _segments_by_sequence_token,
        answer_field_accepts_student_input,
    )

    problems = list(
        m.StudentAssessmentProblem.objects.filter(attempt=attempt).order_by(
            "slot_index", "id"
        )
    )
    answers = {
        (a.problem_id, a.field_token): a
        for a in m.StudentAssessmentAnswer.objects.filter(
            problem_id__in=[p.id for p in problems]
        )
    }
    out_problems = []
    for p in problems:
        key = p.answer_key or {}
        fields = key.get("answer_fields") or p.answer_fields or []
        loaded_full = key.get("loaded_segments") or []
        display_map = _segment_display_map(loaded_full)
        segs_by_tok = _segments_by_sequence_token(loaded_full)
        field_rows = []
        for f in fields:
            if not isinstance(f, dict):
                continue
            if not answer_field_accepts_student_input(f):
                continue
            token = str(f.get("sequence_token") or f.get("token") or "").strip()
            if not token:
                continue
            ans = answers.get((p.id, token))
            detail = (ans.detail if ans else None) or {}
            arch = str(f.get("archetype") or f.get("token") or "")
            base_arch = re.sub(r"\d+$", "", arch).strip()
            requires_manual = bool(detail.get("requires_manual_grading"))
            if not requires_manual and not detail.get("teacher_rescored"):
                # Unscored answer rows for manual field types still need a grade.
                if ans is None or ans.points_score is None:
                    requires_manual = bool(
                        f.get("requires_manual_grading")
                        or arch.startswith("longAnswer")
                        or arch.startswith("canvas")
                    )
            expected_list = _format_expected_for_teacher(f, display_map)
            student_lines = _format_student_answer_for_teacher(
                f, ans.content if ans else None, display_map
            )
            student_parts = []
            expected_parts = []
            if base_arch == "multipleChoiceAnswer":
                inputs = f.get("inputs") if isinstance(f.get("inputs"), dict) else {}
                options = inputs.get("options") if isinstance(inputs.get("options"), list) else []
                student_parts = _mc_answer_display_parts(
                    options,
                    _mc_selected_option_ids(ans.content if ans else None),
                    segs_by_tok,
                )
                expected_parts = _mc_expected_display_parts(options, segs_by_tok)
                student_lines = [
                    ln for ln in (_display_part_plaintext(part) for part in student_parts) if ln
                ]
                expected_list = [
                    ln for ln in (_display_part_plaintext(part) for part in expected_parts) if ln
                ]
            visual_preview = _visual_preview_for_review(
                f, ans.content if ans else None
            )
            # Prefer canvases over "N slope marks" / opaque segment counts.
            if visual_preview:
                student_lines = []
                expected_list = []
            base_max = _field_max_points(f)
            effective_max = base_max
            if detail.get("max") is not None:
                try:
                    effective_max = float(detail.get("max"))
                except (TypeError, ValueError):
                    effective_max = base_max
            field_rows.append(
                {
                    "field_token": token,
                    "archetype": f.get("archetype") or f.get("token"),
                    "label": f.get("label") or token,
                    "max_points": effective_max,
                    "base_max_points": base_max,
                    "student_answer": ans.content if ans else None,
                    "student_answer_lines": student_lines,
                    "student_answer_parts": student_parts,
                    "points_score": ans.points_score if ans else None,
                    "auto_points_score": ans.auto_points_score if ans else None,
                    "requires_manual_grading": requires_manual,
                    "detail": detail.get("detail"),
                    "fully_correct": detail.get("fully_correct"),
                    "show_answer_compare": True,
                    "expected": expected_list[0]
                    if expected_list and len(expected_list) == 1
                    else None,
                    "expected_answers": expected_list or [],
                    "expected_answer_parts": expected_parts,
                    "visual_preview": visual_preview,
                }
            )

        out_problems.append(
            {
                "problem_row_id": p.id,
                "slot_index": p.slot_index,
                "section_name": p.section_name,
                "title": p.title,
                "body_html": p.body_html,
                "loaded_segments": _client_segments_from_problem(p),
                # Teacher also needs full segments for expected graphs — use answer_key
                "loaded_segments_full": loaded_full,
                "earned_points": p.earned_points,
                "max_points": p.max_points,
                "requires_manual_grading": p.requires_manual_grading,
                "fields": field_rows,
                "student_answers": {
                    tok: answers[(p.id, tok)].content
                    for tok in [fr["field_token"] for fr in field_rows]
                    if (p.id, tok) in answers
                },
            }
        )

    return {
        "attempt_id": attempt.id,
        "assessment_id": attempt.assessment_id,
        "student_id": attempt.user_id,
        "username": attempt.user.username if attempt.user else "?",
        "status": attempt.status,
        "earned_points": attempt.earned_points,
        "max_points": attempt.max_points,
        "problems": out_problems,
    }


def apply_teacher_scores(attempt, updates: list[dict]) -> dict:
    """
    updates: [{problem_row_id, field_token, points_score, max_points?}]
    Recalculates problem + attempt totals. max_points may be set to 0 for
    extra-credit fields (earned still counts; max does not add to denominator).
    """
    m = _models()
    problems = {
        p.id: p
        for p in m.StudentAssessmentProblem.objects.filter(attempt=attempt)
    }
    touched_problems = set()

    for item in updates or []:
        if not isinstance(item, dict):
            continue
        try:
            pid = int(item.get("problem_row_id") or item.get("problem_id"))
        except (TypeError, ValueError):
            continue
        token = str(item.get("field_token") or "").strip()
        if not token or pid not in problems:
            continue
        try:
            pts = float(item.get("points_score"))
        except (TypeError, ValueError):
            continue
        ans, _created = m.StudentAssessmentAnswer.objects.get_or_create(
            problem_id=pid,
            field_token=token,
            defaults={"content": None},
        )
        ans.points_score = pts
        detail = dict(ans.detail or {})
        detail["requires_manual_grading"] = False
        detail["teacher_rescored"] = True
        detail["earned"] = pts
        if "max_points" in item and item.get("max_points") is not None:
            try:
                detail["max"] = float(item.get("max_points"))
            except (TypeError, ValueError):
                pass
        ans.detail = detail
        ans.save(update_fields=["points_score", "detail"])
        touched_problems.add(pid)

    # Recompute problem totals from answer points + effective max overrides
    earned_total = 0.0
    max_total = 0.0
    for problem in problems.values():
        answers = {
            a.field_token: a
            for a in m.StudentAssessmentAnswer.objects.filter(problem=problem)
        }
        fields = (problem.answer_key or {}).get("answer_fields") or problem.answer_fields or []
        p_earned = 0.0
        p_max = 0.0
        still_manual = False
        for f in fields:
            if not isinstance(f, dict):
                continue
            token = str(f.get("sequence_token") or f.get("token") or "").strip()
            if not token:
                continue
            ans = answers.get(token)
            base = _field_max_points(f)
            eff_max = base
            if ans and isinstance(ans.detail, dict) and ans.detail.get("max") is not None:
                try:
                    eff_max = float(ans.detail.get("max"))
                except (TypeError, ValueError):
                    eff_max = base
            if ans and ans.points_score is not None:
                p_earned += float(ans.points_score)
            # max=0 means extra credit: earned counts, max does not inflate denominator
            if eff_max > 0:
                p_max += eff_max
            if ans and (ans.detail or {}).get("requires_manual_grading"):
                still_manual = True

        problem.earned_points = p_earned
        problem.max_points = p_max
        problem.requires_manual_grading = still_manual
        problem.save(
            update_fields=["earned_points", "max_points", "requires_manual_grading"]
        )
        earned_total += float(p_earned or 0)
        max_total += float(p_max or 0)

    attempt.earned_points = earned_total
    attempt.max_points = max_total
    attempt.save(update_fields=["earned_points", "max_points"])
    _upsert_final_grade(attempt)

    return {
        "success": True,
        "earned_total": earned_total,
        "max_total": max_total,
        "requires_manual_grading": m.StudentAssessmentProblem.objects.filter(
            attempt=attempt, requires_manual_grading=True
        ).exists(),
    }
