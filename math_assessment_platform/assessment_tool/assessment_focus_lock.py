"""Focus-leave locking for in-progress student assessment attempts."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .assessment_options import (
    CHOICE_LOCK_ON,
    GROUP_LOCK_FOCUS,
    resolved_assessment_option,
)


def focus_lock_enabled(assessment) -> bool:
    return (
        resolved_assessment_option(assessment, GROUP_LOCK_FOCUS)
        == CHOICE_LOCK_ON
    )


def active_focus_lock(attempt):
    if attempt is None:
        return None
    from . import models as m

    return (
        m.StudentAssessmentFocusLock.objects.filter(
            attempt=attempt,
            unlocked_at__isnull=True,
        )
        .order_by("-locked_at", "-id")
        .first()
    )


def focus_lock_payload(attempt) -> dict:
    lock = active_focus_lock(attempt)
    return {
        "focus_locked": lock is not None,
        "focus_locked_at": lock.locked_at.isoformat() if lock else None,
    }


def sync_user_ongoing_assessment(user) -> bool:
    """Keep the legacy profile flag as a cache of authoritative attempt state."""
    if user is None:
        return False
    from . import models as m

    active = m.StudentAssessmentAttempt.objects.filter(
        user=user,
        status=m.StudentAssessmentAttempt.STATUS_IN_PROGRESS,
    ).exists()
    if bool(getattr(user, "ongoing_assessment", False)) != active:
        m.UserProfile.objects.filter(pk=user.pk).update(ongoing_assessment=active)
        user.ongoing_assessment = active
    return active


@transaction.atomic
def lock_attempt_for_focus(attempt, answers_payload=None) -> dict:
    from . import models as m
    from .student_attempts import (
        course_template_assessment,
        upsert_answers,
    )

    attempt = (
        m.StudentAssessmentAttempt.objects.select_for_update()
        .get(pk=attempt.pk)
    )
    template = course_template_assessment(attempt.assessment)
    if template is None or not focus_lock_enabled(template):
        return {"success": True, "focus_lock_enabled": False, "focus_locked": False}
    if attempt.status == m.StudentAssessmentAttempt.STATUS_SUBMITTED:
        sync_user_ongoing_assessment(attempt.user)
        return {
            "success": True,
            "focus_lock_enabled": True,
            "focus_locked": False,
            "submitted": True,
        }
    if attempt.status != m.StudentAssessmentAttempt.STATUS_IN_PROGRESS:
        return {
            "success": False,
            "error": "Assessment has not started.",
            "focus_locked": False,
        }

    lock = active_focus_lock(attempt)
    if lock is not None:
        return {
            "success": True,
            "focus_lock_enabled": True,
            "focus_locked": True,
            "focus_locked_at": lock.locked_at.isoformat(),
        }
    if answers_payload:
        upsert_answers(attempt, answers_payload)
    lock = m.StudentAssessmentFocusLock.objects.create(
        attempt=attempt,
        locked_at=timezone.now(),
    )
    sync_user_ongoing_assessment(attempt.user)
    return {
        "success": True,
        "focus_lock_enabled": True,
        "focus_locked": True,
        "focus_locked_at": lock.locked_at.isoformat(),
    }


@transaction.atomic
def release_focus_lock(attempt, *, released_by, reason: str = "teacher") -> dict:
    from . import models as m

    attempt = m.StudentAssessmentAttempt.objects.select_for_update().get(pk=attempt.pk)
    lock = active_focus_lock(attempt)
    if lock is None:
        return {"success": False, "error": "This attempt is not focus-locked."}
    lock.unlocked_at = timezone.now()
    lock.unlocked_by = released_by
    lock.unlock_reason = reason
    lock.save(update_fields=["unlocked_at", "unlocked_by", "unlock_reason"])
    return {"success": True, "focus_locked": False}


def close_active_focus_lock(attempt, *, reason: str) -> None:
    from . import models as m

    m.StudentAssessmentFocusLock.objects.filter(
        attempt=attempt,
        unlocked_at__isnull=True,
    ).update(
        unlocked_at=timezone.now(),
        unlock_reason=reason,
    )


def delete_active_focus_lock(attempt) -> int:
    """Student chose submit-now: remove this lock as though it never occurred."""
    from . import models as m

    deleted, _ = m.StudentAssessmentFocusLock.objects.filter(
        attempt=attempt,
        unlocked_at__isnull=True,
    ).delete()
    return deleted
