"""
Student course enrollment stints and remove-from-course (kick) helpers.

``users_in_course`` is the current seat only.
``student_course_enrollment`` is the durable stint used to scope
``final_grade_calculation`` so re-enrollment history stays separate.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    Assessment,
    EntityUserInput,
    FinalGradeCalculation,
    OpenStudentAssessmentOverwrite,
    StudentCourseEnrollment,
    UsersInCourse,
)

logger = logging.getLogger(__name__)

CREDIT_REIMBURSEMENT_WINDOW = timedelta(days=7)


def get_active_enrollment(course, user) -> StudentCourseEnrollment | None:
    if user is None:
        return None
    return (
        StudentCourseEnrollment.objects.filter(
            course=course,
            user=user,
            status=StudentCourseEnrollment.STATUS_ACTIVE,
        )
        .order_by("-started_at", "-pk")
        .first()
    )


def ensure_active_enrollment(*, course, user, slot=None) -> StudentCourseEnrollment:
    """
    Return the active stint for this student+course, creating one if needed
    (backfill for seats that predate enrollment instances).
    """
    existing = get_active_enrollment(course, user)
    if existing is not None:
        updates = []
        if slot is not None and existing.slot_id != slot.pk:
            existing.slot = slot
            updates.append("slot")
        if updates:
            existing.save(update_fields=updates)
        return existing

    started = timezone.now()
    if slot is not None and slot.creation_date:
        started = slot.creation_date
        if timezone.is_naive(started):
            started = timezone.make_aware(started)

    return StudentCourseEnrollment.objects.create(
        user=user,
        course=course,
        status=StudentCourseEnrollment.STATUS_ACTIVE,
        end_reason=None,
        started_at=started,
        ended_at=None,
        slot=slot,
    )


def start_enrollment_for_slot(*, course, user, slot) -> StudentCourseEnrollment:
    """Create (or reuse) an active enrollment when a student accepts an invite."""
    return ensure_active_enrollment(course=course, user=user, slot=slot)


def _score_from_student_assessment_copy(assessment: Assessment) -> tuple[float | None, float | None]:
    """
    Best-effort score from entity_user_input on a student assessment copy.
    Returns (points, max_points); either may be None if nothing graded yet.
    """
    from .models import AssessmentQuestionGroup, EntitySegment, Problem

    aqg_ids = list(
        AssessmentQuestionGroup.objects.filter(assessment=assessment).values_list(
            "id", flat=True
        )
    )
    problem_ids = list(
        Problem.objects.filter(aqg_id__in=aqg_ids).values_list("id", flat=True)
    )
    entities = EntitySegment.objects.filter(problem_id__in=problem_ids)
    entity_ids = list(entities.values_list("id", flat=True))
    if not entity_ids:
        return None, None

    inputs = EntityUserInput.objects.filter(entity_id__in=entity_ids)
    scored = inputs.exclude(points_score__isnull=True)
    if not scored.exists():
        return None, None

    points = float(scored.aggregate(total=Sum("points_score"))["total"] or 0.0)
    max_points_agg = entities.exclude(points__isnull=True).aggregate(total=Sum("points"))
    max_points = max_points_agg["total"]
    max_points = float(max_points) if max_points is not None else None
    return points, max_points


def snapshot_enrollment_grades(enrollment: StudentCourseEnrollment) -> int:
    """
    Ensure ``final_grade_calculation`` has rows for scores already earned in
    this stint (submitted student assessment copies).

    Does **not** invent zeros for open/unattempted tests — those are written
    when a teacher closes an assessment (see ``record_zeros_on_assessment_close``).
    Existing enrollment-scoped grade rows are left untouched.
    """
    course = enrollment.course
    student = enrollment.user
    created = 0

    student_copies = Assessment.objects.filter(
        course=course,
        user=student,
        parent_assessment__isnull=False,
    ).select_related("parent_assessment")

    for copy in student_copies:
        parent = copy.parent_assessment
        if parent is None:
            continue
        if FinalGradeCalculation.objects.filter(
            enrollment=enrollment,
            assessment=parent,
        ).exists():
            continue

        status = (copy.status or "").lower()
        points, max_points = _score_from_student_assessment_copy(copy)
        has_attempt_record = points is not None or status in {
            "submitted",
            "closed",
            "graded",
        }
        if not has_attempt_record:
            continue

        weight = 1
        if parent.points_weight is not None:
            try:
                weight = int(parent.points_weight)
            except (TypeError, ValueError):
                weight = 1

        FinalGradeCalculation.objects.create(
            enrollment=enrollment,
            course=course,
            user=student,
            assessment=parent,
            weight=weight,
            assessment_grade_points=0.0 if points is None else points,
            assessment_grade_max_points=max_points,
        )
        created += 1

    return created


def record_zeros_on_assessment_close(*, assessment: Assessment) -> int:
    """
    When a teacher closes a class assessment, write 0 / max for each actively
    enrolled student who does not already have a grade row for this assessment
    on their current enrollment stint.

    Call this from assessment-close flows once those are wired.
    """
    if assessment is None or assessment.user_id is not None:
        # Only parent/class assessments.
        return 0
    if assessment.course_id is None:
        return 0

    status = (assessment.status or "").lower()
    if status not in {"closed", "close"}:
        # Caller may set status before invoking; still allow explicit call.
        pass

    max_points = None
    weight = 1
    if assessment.points_weight is not None:
        try:
            weight = int(assessment.points_weight)
        except (TypeError, ValueError):
            weight = 1

    active = StudentCourseEnrollment.objects.filter(
        course_id=assessment.course_id,
        status=StudentCourseEnrollment.STATUS_ACTIVE,
    ).select_related("user")

    created = 0
    for enrollment in active:
        if FinalGradeCalculation.objects.filter(
            enrollment=enrollment,
            assessment=assessment,
        ).exists():
            continue
        FinalGradeCalculation.objects.create(
            enrollment=enrollment,
            course_id=assessment.course_id,
            user=enrollment.user,
            assessment=assessment,
            weight=weight,
            assessment_grade_points=0.0,
            assessment_grade_max_points=max_points,
        )
        created += 1
    return created


def _delete_student_course_progress(course, student) -> None:
    """Remove live course progress for the student (not historic final grades)."""
    OpenStudentAssessmentOverwrite.objects.filter(
        u=student,
        a__course=course,
    ).delete()

    # Student-specific assessment copies (and cascaded AQG/options).
    Assessment.objects.filter(course=course, user=student).delete()


def enrollment_within_credit_reimbursement_window(enrollment: StudentCourseEnrollment) -> bool:
    started = enrollment.started_at
    if started is None:
        return False
    if timezone.is_naive(started):
        started = timezone.make_aware(started)
    return timezone.now() - started <= CREDIT_REIMBURSEMENT_WINDOW


@transaction.atomic
def kick_student_from_course(*, course, student, removed_by=None) -> dict:
    """
    Remove a student from the course roster.

    - Snapshots existing/submitted grades onto final_grade_calculation for the stint
    - Ends the enrollment instance (history preserved for re-enroll separation)
    - Deletes live progress and the users_in_course seat
    - Placeholder for credit reimbursement when removed within one week

    Returns a summary dict for UI messaging.
    """
    if getattr(student, "user_type", None) != "Student":
        raise ValueError("Only student accounts can be removed from the course roster this way.")

    slot = (
        UsersInCourse.objects.select_for_update()
        .filter(course=course, user=student)
        .first()
    )
    if slot is None:
        raise ValueError("That student is not enrolled in this course.")

    enrollment = ensure_active_enrollment(course=course, user=student, slot=slot)
    enrollment = (
        StudentCourseEnrollment.objects.select_for_update().get(pk=enrollment.pk)
    )

    grades_snapshotted = snapshot_enrollment_grades(enrollment)
    grade_rows = FinalGradeCalculation.objects.filter(enrollment=enrollment).count()

    _delete_student_course_progress(course, student)

    reimbursable = enrollment_within_credit_reimbursement_window(enrollment)
    # TODO(credits): When the credit system is implemented, reimburse the Teacher
    # if reimbursable is True (student removed within one week of enrollment).
    _ = (reimbursable, removed_by)

    enrollment.status = StudentCourseEnrollment.STATUS_ENDED
    enrollment.end_reason = StudentCourseEnrollment.END_REASON_KICKED
    enrollment.ended_at = timezone.now()
    enrollment.slot = None
    enrollment.save(
        update_fields=["status", "end_reason", "ended_at", "slot"]
    )

    slot_id = slot.pk
    UsersInCourse.objects.filter(pk=slot_id).delete()

    try:
        from .notifications import create_notification

        create_notification(
            student,
            title=f"Removed from course: {course.name}",
            content={
                "course_id": course.id,
                "course_name": course.name,
                "message": (
                    f"You have been removed from {course.name}. "
                    "Your live course progress for this enrollment was deleted. "
                    "Any recorded grades for this enrollment period were saved to your transcript."
                ),
            },
            reason="course_student_removed",
            sender=removed_by,
        )
    except Exception:
        logger.exception(
            "Failed to notify student id=%s of removal from course id=%s",
            getattr(student, "pk", None),
            getattr(course, "pk", None),
        )

    return {
        "enrollment_id": enrollment.pk,
        "grade_rows": grade_rows,
        "grades_snapshotted": grades_snapshotted,
        "credit_reimbursement_pending": reimbursable,
    }
