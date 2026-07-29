"""
Teacher per-student actions on an assessment attempt:
open retake, adjust attempt score, void attempt score.
"""

from __future__ import annotations

from django.db import connection, transaction


def _models():
    from . import models as m

    return m


def _student_pk(student) -> int:
    return int(getattr(student, "pk", None) or getattr(student, "user_id"))


def student_has_open_retake(assessment, student) -> bool:
    if assessment is None or student is None:
        return False
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT status_open FROM open_student_assessment_overwrite
            WHERE a_id = %s AND u_id = %s
            """,
            [assessment.id, _student_pk(student)],
        )
        row = cursor.fetchone()
    return bool(row and row[0])


def set_student_open_retake(assessment, student, *, open_flag: bool = True) -> None:
    """Upsert open_student_assessment_overwrite (composite PK a_id, u_id)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO open_student_assessment_overwrite (a_id, u_id, status_open)
            VALUES (%s, %s, %s)
            ON CONFLICT (a_id, u_id) DO UPDATE SET status_open = EXCLUDED.status_open
            """,
            [assessment.id, _student_pk(student), bool(open_flag)],
        )


def clear_student_open_retake(assessment, student) -> None:
    set_student_open_retake(assessment, student, open_flag=False)


def open_test_for_retake(assessment, student) -> dict:
    """
    Teacher opens a one-shot retake window for this student.
    No student request is required — this only arms the override so the
    student can start another attempt. The flag clears when they submit
    or when the teacher closes the retake.
    """
    m = _models()
    from .course_enrollment import get_active_enrollment
    from .student_attempts import (
        attempts_qs_for_template,
        course_template_assessment,
    )

    template = course_template_assessment(assessment) or assessment
    enrollment = get_active_enrollment(course=template.course, user=student)
    if enrollment is None:
        return {"success": False, "error": "Student is not actively enrolled."}

    student_attempts = attempts_qs_for_template(template).filter(enrollment=enrollment)
    has_submitted = student_attempts.filter(
        status=m.StudentAssessmentAttempt.STATUS_SUBMITTED,
    ).exists()
    if not has_submitted:
        return {
            "success": False,
            "error": "Student has not submitted this assessment yet.",
        }

    if student_attempts.filter(
        status=m.StudentAssessmentAttempt.STATUS_IN_PROGRESS,
    ).exists() or student_attempts.filter(
        status=m.StudentAssessmentAttempt.STATUS_READY,
    ).exists():
        return {
            "success": False,
            "error": "Student already has an open attempt in progress.",
        }

    set_student_open_retake(template, student, open_flag=True)
    return {
        "success": True,
        "retake_open": True,
        "message": "Retake window opened for this student.",
    }


def close_test_for_retake(assessment, student) -> dict:
    """
    Teacher ends a per-student retake.
    - No attempt created yet / ready only: clear grant and discard ready take
      so nothing is recorded.
    - In progress: force-submit the active retake with saved answers.
    """
    m = _models()
    from .course_enrollment import get_active_enrollment
    from .student_attempts import (
        attempts_qs_for_template,
        course_template_assessment,
        discard_unstarted_attempt,
        finalize_student_attempt_if_open,
    )

    template = course_template_assessment(assessment) or assessment
    enrollment = get_active_enrollment(course=template.course, user=student)
    if enrollment is None:
        return {"success": False, "error": "Student is not actively enrolled."}

    had_open_grant = student_has_open_retake(template, student)
    latest = (
        attempts_qs_for_template(template)
        .filter(enrollment=enrollment)
        .order_by("-id")
        .first()
    )

    discarded = False
    submitted = False
    if latest is not None:
        if latest.status == m.StudentAssessmentAttempt.STATUS_READY:
            discarded = discard_unstarted_attempt(latest)
        elif latest.status == m.StudentAssessmentAttempt.STATUS_IN_PROGRESS:
            finalize_student_attempt_if_open(latest)
            latest.refresh_from_db()
            submitted = (
                latest.status == m.StudentAssessmentAttempt.STATUS_SUBMITTED
                or latest.auto_graded_at is not None
            )

    clear_student_open_retake(template, student)

    if not had_open_grant and not discarded and not submitted:
        return {
            "success": False,
            "error": "No open retake to close for this student.",
        }

    if discarded:
        message = "Retake closed. The unstarted attempt was removed."
    elif submitted:
        message = "Retake closed. The in-progress attempt was submitted."
    else:
        message = "Retake window closed for this student."

    return {
        "success": True,
        "retake_open": False,
        "discarded_unstarted": discarded,
        "submitted_in_progress": submitted,
        "message": message,
    }


@transaction.atomic
def adjust_attempt_score(attempt, *, earned_points, max_points) -> dict:
    m = _models()
    attempt = m.StudentAssessmentAttempt.objects.select_for_update().get(pk=attempt.pk)
    if attempt.status != m.StudentAssessmentAttempt.STATUS_SUBMITTED:
        return {"success": False, "error": "Only submitted attempts can be adjusted."}
    if getattr(attempt, "score_voided", False):
        return {"success": False, "error": "Voided attempts cannot be adjusted."}

    try:
        earned = float(earned_points)
        max_pts = float(max_points)
    except (TypeError, ValueError):
        return {"success": False, "error": "Invalid score values."}
    if earned < 0 or max_pts < 0:
        return {"success": False, "error": "Scores cannot be negative."}

    # Preserve the first pre-edit totals for display.
    if attempt.original_earned_points is None and attempt.earned_points is not None:
        attempt.original_earned_points = float(attempt.earned_points)
    if attempt.original_max_points is None and attempt.max_points is not None:
        attempt.original_max_points = float(attempt.max_points)

    attempt.earned_points = earned
    attempt.max_points = max_pts
    attempt.save(
        update_fields=[
            "earned_points",
            "max_points",
            "original_earned_points",
            "original_max_points",
        ]
    )
    from .student_attempts import _upsert_final_grade

    _upsert_final_grade(attempt)
    return {
        "success": True,
        "earned_points": attempt.earned_points,
        "max_points": attempt.max_points,
        "original_earned_points": attempt.original_earned_points,
        "original_max_points": attempt.original_max_points,
        "score_adjusted": True,
    }


@transaction.atomic
def void_attempt_score(attempt) -> dict:
    """Toggle void on a submitted attempt (void ↔ restore)."""
    m = _models()
    from .student_attempts import _upsert_final_grade

    attempt = m.StudentAssessmentAttempt.objects.select_for_update().get(pk=attempt.pk)
    if attempt.status != m.StudentAssessmentAttempt.STATUS_SUBMITTED:
        return {"success": False, "error": "Only submitted attempts can be voided."}

    currently_voided = bool(getattr(attempt, "score_voided", False))
    attempt.score_voided = not currently_voided
    attempt.save(update_fields=["score_voided"])

    # Rebuild final grade from non-voided attempts (latest/highest options
    # skip voided takes).
    _upsert_final_grade(attempt)

    return {
        "success": True,
        "score_voided": attempt.score_voided,
        "message": (
            "Test score voided."
            if attempt.score_voided
            else "Test score restored."
        ),
    }
