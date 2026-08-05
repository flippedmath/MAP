"""
Frozen student assessment attempts: generate, folders, takeability, grade-once.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
from datetime import timedelta

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
ASSESSMENT_STATUSES = frozenset({"closed", "open", "upcoming", "hidden", "retake"})
# Legacy values still read for compatibility; not offered in the UI.
_ASSESSMENT_STATUS_ALIASES = {
    "inactive": "hidden",
    "locked": "closed",
    "submitted": "closed",
    "active": "open",
    # Legacy class-wide retake flag maps onto the modern retake status.
    "retake_available": "retake",
    "retake available": "retake",
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
    if status in ("open", "retake"):
        return True
    if status == "upcoming":
        return upcoming_window_contains(assessment, now=now)
    return False


def assessment_active_retake_series(assessment) -> int:
    """Current series that class open/retake applies to (minimum 1)."""
    if assessment is None:
        return 1
    try:
        value = int(getattr(assessment, "active_retake_series", 1) or 1)
    except (TypeError, ValueError):
        value = 1
    return value if value >= 1 else 1


def attempt_retake_series(attempt) -> int:
    if attempt is None:
        return 1
    try:
        value = int(getattr(attempt, "retake_series", 1) or 1)
    except (TypeError, ValueError):
        value = 1
    return value if value >= 1 else 1


def student_has_submitted_in_series(attempts, series: int) -> bool:
    m = _models()
    series = int(series)
    for attempt in attempts or []:
        if attempt_retake_series(attempt) != series:
            continue
        if (
            attempt.status == m.StudentAssessmentAttempt.STATUS_SUBMITTED
            or attempt.auto_graded_at is not None
        ):
            return True
    return False


def resolve_series_for_new_attempt(template, student, prior_attempts) -> int:
    """
    Choose retake_series for a newly created attempt.

    - Per-student open-retake grant: use the grant's target series (selected attempt).
    - Class ``retake`` after a submission in the active series: advance the
      assessment's active series (once) and assign that new series.
    - Otherwise: assessment.active_retake_series.
    """
    from .student_assessment_actions import (
        get_student_open_retake_series,
        student_has_open_retake,
    )

    template = course_template_assessment(template) or template
    active = assessment_active_retake_series(template)
    status = normalize_assessment_status(getattr(template, "status", None))

    if student_has_open_retake(template, student):
        grant_series = get_student_open_retake_series(template, student)
        if grant_series is not None:
            return max(1, int(grant_series))
        return active

    if status == "retake" and student_has_submitted_in_series(prior_attempts, active):
        # Assign the next series for this take, but do not advance the class
        # active_retake_series until a student actually starts (begin_attempt).
        # That way an unused open→close / retake→close can discard READY takes
        # and leave the class series unchanged.
        return active + 1

    return active


def maybe_advance_active_retake_series_on_start(template, attempt) -> None:
    """
    Persist class active_retake_series when the first student starts a take in a
    newer series under class ``retake`` (not per-student grants).
    """
    if template is None or attempt is None:
        return
    if normalize_assessment_status(getattr(template, "status", None)) != "retake":
        return
    from .student_assessment_actions import student_has_open_retake

    if student_has_open_retake(template, attempt.user):
        return
    series = attempt_retake_series(attempt)
    m = _models()
    locked = (
        m.Assessment.objects.select_for_update()
        .filter(pk=template.pk)
        .first()
    )
    if locked is None:
        return
    current = assessment_active_retake_series(locked)
    if series > current:
        locked.active_retake_series = series
        locked.save(update_fields=["active_retake_series"])


def revert_active_retake_series_to_used(template) -> int:
    """
    Snap active_retake_series back to the highest series that has real student
    work (started / submitted). Used after discarding an unused class session.
    """
    template = course_template_assessment(template) or template
    m = _models()
    max_used = 1
    for att in attempts_qs_for_template(template).iterator():
        if (
            att.started_at is not None
            or att.auto_graded_at is not None
            or att.status
            in (
                m.StudentAssessmentAttempt.STATUS_IN_PROGRESS,
                m.StudentAssessmentAttempt.STATUS_SUBMITTED,
            )
        ):
            max_used = max(max_used, attempt_retake_series(att))
    current = assessment_active_retake_series(template)
    if current > max_used:
        template.active_retake_series = max_used
        template.modified_date = timezone.now()
        template.save(update_fields=["active_retake_series", "modified_date"])
        return max_used
    return current


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


def attempt_force_deadline(assessment, attempt, *, now=None):
    """
    Authoritative server deadline for an open attempt.

    Returns (deadline_datetime_or_None, reason_or_None). Reasons:
    ``assessment_end``, ``time_limit``, or ``class_closed``.
    """
    if assessment is None or attempt is None:
        return None, None
    m = _models()
    if (
        attempt.status == m.StudentAssessmentAttempt.STATUS_SUBMITTED
        or attempt.auto_graded_at is not None
    ):
        return None, None

    now = _aware(now) or timezone.now()
    template = course_template_assessment(assessment) or assessment
    _start, window_end = assessment_window_bounds(template)
    from .assessment_options import countdown_timer_payload

    countdown = countdown_timer_payload(
        template,
        attempt,
        window_end=window_end,
        now=now,
    )
    force_iso = countdown.get("force_submit_at")
    force_reason = countdown.get("force_submit_reason")
    force_at = None
    if force_iso:
        from django.utils.dateparse import parse_datetime

        force_at = parse_datetime(force_iso)
        if force_at is not None and timezone.is_naive(force_at):
            force_at = timezone.make_aware(
                force_at, timezone.get_current_timezone()
            )

    if force_at is not None and force_at <= now:
        return force_at, force_reason or "time_limit"

    if assessment_taking_ended(template, now=now):
        if not attempt_may_continue_while_closed(attempt, template, attempt.user):
            return now, "class_closed"

    if force_at is not None:
        return force_at, force_reason
    return None, None


def attempt_deadline_expired(assessment, attempt, *, now=None) -> bool:
    deadline, _reason = attempt_force_deadline(assessment, attempt, now=now)
    if deadline is None:
        return False
    now = _aware(now) or timezone.now()
    return deadline <= now


def attempt_must_stop_taking(assessment, attempt, *, now=None) -> dict:
    """
    Whether an open attempt must stop (window/time-limit/class closed).

    Returns ``{must_stop, reason, force_submit_at}``.
    """
    deadline, reason = attempt_force_deadline(assessment, attempt, now=now)
    now = _aware(now) or timezone.now()
    must_stop = bool(deadline is not None and deadline <= now)
    return {
        "must_stop": must_stop,
        "reason": reason if must_stop else None,
        "force_submit_at": deadline,
    }


def force_submit_unsubmitted_attempts(template, *, reason: str = "closed") -> dict:
    """
    Compile saved answers for every ready/in_progress attempt on this template
    into graded submissions.

    Per-student open-retake grants are left alone — those end only via Close retake.
    Class-wide retake/open takes are force-submitted when the class closes.
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
            focus_reason = (
                "window_ended"
                if reason in ("window_ended", "window_expired", "time_limit")
                else "assessment_closed"
            )
            submit_and_grade_attempt(
                attempt,
                focus_unlock_reason=focus_reason,
            )
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

    Session rules (open / retake / upcoming window that is being closed):
    - If nobody started during the current session, discard generated READY
      attempts (as if the window never opened) and do not write new grades.
      Per-student open-retake grants are left alone.
    - If at least one student started, force-submit unfinished class attempts
      and score them (per-student grants still left alone).

    When no session stamp exists (legacy), fall back to lifetime engagement.
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

    # Capture before finalize_class_session_on_close clears the pending stamp.
    pending = _aware(getattr(template, "open_session_pending_at", None))
    session_had_start = (
        session_had_student_start(template, since=pending)
        if pending is not None
        else None
    )

    cancel_active_generation_jobs(
        template, reason="Cancelled because the assessment was closed."
    )
    finalize_class_session_on_close(template)

    throw_unused_session = False
    if session_had_start is False:
        throw_unused_session = True
    elif session_had_start is True:
        throw_unused_session = False
    else:
        # No pending stamp (already closed / legacy). If the only open class
        # takes are never-started READY rows, throw them away — including the
        # leftover class-retake case after a prior closed→retake→closed cycle.
        m = _models()
        has_in_progress = False
        has_ready = False
        for att in (
            attempts_qs_for_template(template)
            .filter(
                status__in=(
                    m.StudentAssessmentAttempt.STATUS_READY,
                    m.StudentAssessmentAttempt.STATUS_IN_PROGRESS,
                )
            )
            .select_related("user")
            .iterator()
        ):
            if attempt_may_continue_while_closed(att, template, att.user):
                continue
            if att.status == m.StudentAssessmentAttempt.STATUS_IN_PROGRESS:
                has_in_progress = True
            else:
                has_ready = True
        if has_ready and not has_in_progress:
            throw_unused_session = True
        elif not assessment_has_student_engagement(template):
            throw_unused_session = True
        else:
            throw_unused_session = False

    if throw_unused_session:
        discard_result = discard_unstarted_class_attempts(template)
        reverted_series = revert_active_retake_series_to_used(template)
        # Defensive: drop accidental grade rows only when the assessment never
        # had real engagement at all.
        m = _models()
        if not assessment_has_student_engagement(template):
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
            "reverted_active_retake_series": reverted_series,
            **discard_result,
        }

    result = force_submit_unsubmitted_attempts(template, reason=reason)
    result["thrown"] = False
    result["status_changed"] = status_changed
    result["assessment_status"] = template.status
    result["zeros_recorded"] = record_zeros_on_assessment_close(assessment=template)
    return result


def mark_class_session_opened(assessment, *, at=None) -> None:
    """Record the start of an open / retake / upcoming class session."""
    template = course_template_assessment(assessment) or assessment
    stamp = _aware(at) or timezone.now()
    template.open_session_pending_at = stamp
    template.modified_date = timezone.now()
    template.save(update_fields=["open_session_pending_at", "modified_date"])


def session_had_student_start(template, *, since) -> bool:
    """True when any student started a take on/after the session open stamp."""
    since = _aware(since)
    if since is None:
        return False
    template = course_template_assessment(template) or template
    return (
        attempts_qs_for_template(template)
        .filter(started_at__isnull=False, started_at__gte=since)
        .exists()
    )


def finalize_class_session_on_close(assessment) -> None:
    """
    Commit open_session_at only when at least one student started during the
    pending open/retake session; always clear the pending stamp.
    """
    template = course_template_assessment(assessment) or assessment
    pending = _aware(getattr(template, "open_session_pending_at", None))
    update_fields = []
    if pending is not None and session_had_student_start(template, since=pending):
        template.open_session_at = pending
        update_fields.append("open_session_at")
    if getattr(template, "open_session_pending_at", None) is not None:
        template.open_session_pending_at = None
        update_fields.append("open_session_pending_at")
    if update_fields:
        template.modified_date = timezone.now()
        update_fields.append("modified_date")
        template.save(update_fields=update_fields)


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
    """Remove every READY class attempt (and take artifacts) for a course assessment."""
    return discard_unstarted_class_attempts(template)


def discard_unstarted_class_attempts(template) -> dict:
    """
    Remove READY attempts that were never started.

    Per-student open-retake grants are preserved (those end via Close retake).
    """
    from .student_assessment_actions import student_has_open_retake

    m = _models()
    template = course_template_assessment(template) or template
    ready = list(
        attempts_qs_for_template(template)
        .filter(status=m.StudentAssessmentAttempt.STATUS_READY)
        .select_related("assessment", "branch", "user")
        .order_by("id")
    )
    discarded_ids = []
    skipped_grant_ids = []
    for attempt in ready:
        if student_has_open_retake(template, attempt.user):
            skipped_grant_ids.append(attempt.id)
            continue
        if discard_unstarted_attempt(attempt):
            discarded_ids.append(attempt.id)
    return {
        "discarded_count": len(discarded_ids),
        "discarded_attempt_ids": discarded_ids,
        "skipped_grant_attempt_ids": skipped_grant_ids,
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
    Class-wide open/upcoming/retake window, or a teacher per-student
    open-retake overwrite (allowed even when the class assessment is closed).
    """
    template = course_template_assessment(assessment) or assessment
    if assessment_is_hidden_from_students(template):
        return False
    if assessment_is_takeable(template, now=now):
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
        # Per-attempt time limit or window end: stop continuing.
        if attempt_deadline_expired(template, open_attempt, now=now):
            return False
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

    active_series = assessment_active_retake_series(template)
    status = normalize_assessment_status(template.status)
    from .student_assessment_actions import student_has_open_retake

    if student_has_open_retake(template, student):
        return True

    # Class retake: students who finished the active series (or never took)
    # may start; first starters under retake open a new series.
    if status == "retake":
        return True

    # Open / upcoming window: only the active series, and only if not yet
    # submitted in that series (prior series stay frozen).
    if student_has_submitted_in_series(attempts, active_series):
        return False
    return True

# Daemon generation workers can die on runserver reload / gunicorn recycle and
# leave rows stuck in pending/running, which blocks all further status edits.
# Pending should flip to running almost immediately; treat longer as dead.
_GENERATION_PENDING_STALE = timedelta(seconds=15)
_GENERATION_RUNNING_STALE = timedelta(minutes=5)


def cancel_active_generation_jobs(assessment, *, reason: str = "cancelled") -> int:
    """Mark any pending/running generation jobs for this assessment as failed."""
    m = _models()
    template = course_template_assessment(assessment) or assessment
    now = timezone.now()
    qs = m.AssessmentGenerationJob.objects.filter(
        assessment=template,
        status__in=(
            m.AssessmentGenerationJob.STATUS_PENDING,
            m.AssessmentGenerationJob.STATUS_RUNNING,
        ),
    )
    count = 0
    for job in qs.iterator():
        job.status = m.AssessmentGenerationJob.STATUS_FAILED
        job.error_message = str(reason or "cancelled")[:4000]
        job.finished_at = now
        job.save(update_fields=["status", "error_message", "finished_at"])
        count += 1
    return count


def fail_stale_generation_jobs(assessment=None) -> int:
    """
    Mark abandoned generation jobs as failed so teachers can change status again.

    Pending jobs should move to running almost immediately; if they do not, the
    worker never started. Long-running jobs are treated as abandoned workers.
    Jobs that already counted every student but never flipped to complete/failed
    are also treated as abandoned (worker died after the loop).
    """
    m = _models()
    now = timezone.now()
    qs = m.AssessmentGenerationJob.objects.filter(
        status__in=(
            m.AssessmentGenerationJob.STATUS_PENDING,
            m.AssessmentGenerationJob.STATUS_RUNNING,
        )
    )
    if assessment is not None:
        qs = qs.filter(assessment=assessment)

    failed = 0
    for job in qs.iterator():
        started = _aware(job.started_at) or now
        age = now - started
        total = int(job.total_students or 0)
        completed = int(job.completed_students or 0)
        finished_counts = total > 0 and completed >= total
        if job.status == m.AssessmentGenerationJob.STATUS_PENDING:
            stale = age >= _GENERATION_PENDING_STALE or finished_counts
        else:
            stale = age >= _GENERATION_RUNNING_STALE or finished_counts
        if not stale:
            continue
        prior_status = job.status
        job.status = m.AssessmentGenerationJob.STATUS_FAILED
        job.error_message = (
            "Generation worker did not finish (timed out or interrupted)."
        )[:4000]
        job.finished_at = now
        job.save(update_fields=["status", "error_message", "finished_at"])
        failed += 1
        logger.warning(
            "Failed stale assessment generation job id=%s assessment_id=%s "
            "prior_status=%s age_s=%.0f completed=%s/%s",
            job.id,
            job.assessment_id,
            prior_status,
            age.total_seconds(),
            completed,
            total,
        )
    return failed


def generation_job_blocks_edits(assessment) -> bool:
    fail_stale_generation_jobs(assessment)
    m = _models()
    return m.AssessmentGenerationJob.objects.filter(
        assessment=assessment,
        status__in=(
            m.AssessmentGenerationJob.STATUS_PENDING,
            m.AssessmentGenerationJob.STATUS_RUNNING,
        ),
    ).exists()


def latest_generation_job(assessment):
    fail_stale_generation_jobs(assessment)
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


def student_prior_problem_history_for_assessment(template, student):
    """
    Source problems and rand/randInt fingerprints from all prior attempts
    by this student on the assessment (including voided attempts).
    """
    from .util import random_fingerprint_from_frozen_problem

    m = _models()
    attempt_ids = list(
        attempts_qs_for_template(template)
        .filter(user=student)
        .values_list("id", flat=True)
    )
    seen_source_problem_ids = set()
    prior_random_fingerprints_by_source = {}
    if not attempt_ids:
        return {
            "seen_source_problem_ids": seen_source_problem_ids,
            "prior_random_fingerprints_by_source": prior_random_fingerprints_by_source,
        }

    rows = m.StudentAssessmentProblem.objects.filter(attempt_id__in=attempt_ids).only(
        "source_problem_id",
        "answer_key",
        "render_payload",
    )
    for row in rows:
        source_id = row.source_problem_id
        if source_id is None:
            continue
        source_id = int(source_id)
        seen_source_problem_ids.add(source_id)
        fingerprint = random_fingerprint_from_frozen_problem(row)
        if fingerprint is None:
            continue
        prior_random_fingerprints_by_source.setdefault(source_id, []).append(
            fingerprint
        )
    return {
        "seen_source_problem_ids": seen_source_problem_ids,
        "prior_random_fingerprints_by_source": prior_random_fingerprints_by_source,
    }


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
    """
    Allow an in-flight take on a closed class assessment only when the teacher
    granted a per-student open retake (REDO). Class-wide open/retake takes end
    when the class assessment is closed.
    """
    if attempt is None or student is None:
        return False
    from .student_assessment_actions import student_has_open_retake

    template = course_template_assessment(template) or template
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
        curve_max_points=float(getattr(template, "curve_max_points", 0) or 0),
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
    Problems are freshly generated for every new take unless Synchronize tests
    is enabled, in which case the current canonical form for this take number
    is cloned.
    """
    m = _models()
    template = course_template_assessment(parent_assessment) or parent_assessment

    # Serialize concurrent starts/retakes for the same enrollment.
    locked_enrollment = (
        m.StudentCourseEnrollment.objects.select_for_update()
        .filter(pk=enrollment.pk)
        .first()
    )
    if locked_enrollment is None:
        raise PermissionError("Student enrollment was not found.")
    enrollment = locked_enrollment

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
    series = resolve_series_for_new_attempt(template, student, prior_attempts)
    # Refresh template in case class retake advanced active_retake_series.
    template = m.Assessment.objects.filter(pk=template.pk).first() or template
    from .assessment_sync import (
        ensure_synchronized_form,
        synchronized_tests_enabled,
    )

    synchronized_form = None
    synchronized_problems = []
    problems = []
    if synchronized_tests_enabled(template):
        # Locked get-or-create so parallel late enrollments cannot mint
        # competing cohorts for the same attempt ordinal.
        synchronized_form = ensure_synchronized_form(template, take_index)
        synchronized_problems = list(
            synchronized_form.problems.all().order_by("slot_index", "id")
        )
    else:
        history = student_prior_problem_history_for_assessment(template, student)
        assembled = assemble_practice_test(
            template,
            actor_user=None,
            allow_status_mutation=False,
            seen_source_problem_ids=history["seen_source_problem_ids"],
            prior_random_fingerprints_by_source=history[
                "prior_random_fingerprints_by_source"
            ],
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
        synchronized_form=synchronized_form,
        retake_series=series,
        creation_date=now,
    )

    frozen_problems = []
    if synchronized_form is not None:
        for source in synchronized_problems:
            frozen_problems.append(
                {
                    "slot": int(source.slot_index or 0),
                    "section_name": source.section_name,
                    "title": source.title,
                    "source_problem_id": source.source_problem_id,
                    "body_html": source.body_html,
                    "render_payload": copy.deepcopy(source.render_payload or {}),
                    "answer_key": copy.deepcopy(source.answer_key or {}),
                    "answer_fields": copy.deepcopy(source.answer_fields or []),
                    "max_points": float(source.max_points or 0),
                }
            )
    else:
        for inst in problems:
            answer_key, render_payload, answer_fields, body_html = _freeze_instance(inst)
            max_points = 0.0
            for field in answer_key.get("answer_fields") or []:
                try:
                    max_points += float(field.get("points") or 0)
                except (TypeError, ValueError):
                    pass
            slot = int(inst.get("slot_index") or 0)
            frozen_problems.append(
                {
                    "slot": slot,
                    "section_name": inst.get("section_name"),
                    "title": inst.get("title") or f"Question {slot}",
                    "source_problem_id": inst.get("problem_id"),
                    "body_html": body_html,
                    "render_payload": render_payload,
                    "answer_key": answer_key,
                    "answer_fields": answer_fields,
                    "max_points": max_points,
                }
            )

    for frozen in frozen_problems:
        slot = frozen["slot"]
        title = frozen["title"] or f"Question {slot}"
        q_folder = _create_question_folder(student, assessment_folder, slot, title)
        m.StudentAssessmentProblem.objects.create(
            attempt=attempt,
            slot_index=slot,
            section_name=frozen["section_name"],
            title=title,
            source_problem_id=frozen["source_problem_id"],
            body_html=frozen["body_html"],
            render_payload=frozen["render_payload"],
            answer_key=frozen["answer_key"],
            answer_fields=frozen["answer_fields"],
            max_points=frozen["max_points"],
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

    with transaction.atomic():
        locked = (
            m.StudentAssessmentAttempt.objects.select_for_update()
            .filter(pk=attempt.pk)
            .first()
        )
        if locked is None or locked.status != m.StudentAssessmentAttempt.STATUS_READY:
            return locked or attempt

        locked.status = m.StudentAssessmentAttempt.STATUS_IN_PROGRESS
        if locked.started_at is None:
            locked.started_at = timezone.now()
        locked.save(update_fields=["status", "started_at"])

        template = course_template_assessment(
            m.Assessment.objects.filter(pk=locked.assessment_id).first()
        )
        if template is not None:
            maybe_advance_active_retake_series_on_start(template, locked)
        attempt = locked

    if attempt.user_id:
        m.UserProfile.objects.filter(pk=attempt.user_id).update(
            ongoing_assessment=True
        )
        if getattr(attempt, "user", None) is not None:
            attempt.user.ongoing_assessment = True
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

    needs_new = False
    if latest and latest.status == m.StudentAssessmentAttempt.STATUS_SUBMITTED:
        status = normalize_assessment_status(template.status)
        active_series = assessment_active_retake_series(template)
        has_grant = student_has_open_retake(template, student)
        if has_grant:
            needs_new = True
        elif status == "retake":
            needs_new = True
        elif status in ("open", "upcoming") and not student_has_submitted_in_series(
            list(
                attempts_qs_for_template(template)
                .filter(enrollment=enrollment)
                .order_by("id")
            ),
            active_series,
        ):
            # Submitted an older series; active series not yet attempted.
            needs_new = attempt_retake_series(latest) != active_series
        if not needs_new:
            return latest
    elif assessment_taking_ended(template):
        # No attempt yet and class is closed — cannot start.
        raise PermissionError("This assessment is closed.")

    attempt, _created = generate_attempt_for_student(
        template,
        student,
        enrollment,
        force_new=bool(needs_new),
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

    # Bail out if the class was closed (or the job was cancelled) before we start.
    job.refresh_from_db(fields=["status"])
    if job.status not in (
        m.AssessmentGenerationJob.STATUS_PENDING,
        m.AssessmentGenerationJob.STATUS_RUNNING,
    ):
        return

    job.status = m.AssessmentGenerationJob.STATUS_RUNNING
    job.save(update_fields=["status"])

    try:
        enrollments = _active_enrollments_for_course(assessment.course)
        job.total_students = len(enrollments)
        job.completed_students = 0
        job.save(update_fields=["total_students", "completed_students"])

        # Mint the shared attempt-1 form once before cloning to every student.
        from .assessment_sync import ensure_synchronized_form, synchronized_tests_enabled

        if synchronized_tests_enabled(assessment):
            try:
                ensure_synchronized_form(assessment, 1)
            except Exception as exc:
                job.status = m.AssessmentGenerationJob.STATUS_FAILED
                job.error_message = (
                    f"Synchronized form generation failed: {exc}"
                )[:4000]
                job.finished_at = timezone.now()
                job.save(update_fields=["status", "error_message", "finished_at"])
                return

        # Re-check: teacher may have closed/cancelled while we were syncing.
        job.refresh_from_db(fields=["status"])
        if job.status != m.AssessmentGenerationJob.STATUS_RUNNING:
            return

        assessment.refresh_from_db(fields=["status"])
        # Class-wide retake must mint a new take for students who already submitted.
        force_new = normalize_assessment_status(assessment.status) == "retake"

        errors = []
        for enrollment in enrollments:
            job.refresh_from_db(fields=["status"])
            if job.status != m.AssessmentGenerationJob.STATUS_RUNNING:
                return
            try:
                generate_attempt_for_student(
                    assessment,
                    enrollment.user,
                    enrollment,
                    force_new=force_new,
                )
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
    except Exception as exc:
        logger.exception("Assessment generation job %s crashed", job_id)
        try:
            job.refresh_from_db()
            if job.status in (
                m.AssessmentGenerationJob.STATUS_PENDING,
                m.AssessmentGenerationJob.STATUS_RUNNING,
            ):
                job.status = m.AssessmentGenerationJob.STATUS_FAILED
                job.error_message = f"Generation crashed: {exc}"[:4000]
                job.finished_at = timezone.now()
                job.save(update_fields=["status", "error_message", "finished_at"])
        except Exception:
            logger.exception(
                "Could not mark generation job %s failed after crash", job_id
            )


def start_generation_job(parent_assessment):
    """Create a job row and kick an async worker after commit."""
    m = _models()
    fail_stale_generation_jobs(parent_assessment)
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
        try:
            t = threading.Thread(
                target=run_generation_job,
                args=(job_id,),
                name=f"assessment-gen-{job_id}",
                daemon=True,
            )
            t.start()
        except Exception as exc:
            logger.exception("Failed to start generation worker for job %s", job_id)
            try:
                m.AssessmentGenerationJob.objects.filter(pk=job_id).update(
                    status=m.AssessmentGenerationJob.STATUS_FAILED,
                    error_message=f"Could not start generation worker: {exc}"[:4000],
                    finished_at=timezone.now(),
                )
            except Exception:
                logger.exception(
                    "Could not mark generation job %s failed after spawn error",
                    job_id,
                )

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
def submit_and_grade_attempt(attempt, *, focus_unlock_reason: str = "submitted"):
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

    from .assessment_focus_lock import (
        close_active_focus_lock,
        sync_user_ongoing_assessment,
    )

    close_active_focus_lock(attempt, reason=focus_unlock_reason)
    sync_user_ongoing_assessment(attempt.user)

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


@transaction.atomic
def regrade_attempt(attempt, *, preserve_teacher_scores: bool = True) -> dict:
    """
    Re-run automatic grading for a submitted attempt (answer-key corrections).

    Teacher-rescored fields are preserved when ``preserve_teacher_scores`` is True.
    """
    m = _models()
    attempt = m.StudentAssessmentAttempt.objects.select_for_update().get(pk=attempt.pk)
    if attempt.status != m.StudentAssessmentAttempt.STATUS_SUBMITTED:
        return {"success": False, "error": "Only submitted attempts can be re-graded."}
    if getattr(attempt, "score_voided", False):
        return {"success": False, "error": "Voided attempts cannot be re-graded."}

    problems = list(
        m.StudentAssessmentProblem.objects.filter(attempt=attempt)
        .order_by("slot_index", "id")
        .select_for_update()
    )
    answers = {
        (a.problem_id, a.field_token): a
        for a in m.StudentAssessmentAnswer.objects.filter(
            problem_id__in=[p.id for p in problems]
        ).select_for_update()
    }

    earned_total = 0.0
    max_total = 0.0
    any_manual = False
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
        p_earned = 0.0
        p_max = float(graded.get("max_total") or 0)
        requires_manual = False
        graded_by_token = {
            str(item.get("sequence_token") or item.get("token") or "").strip(): item
            for item in (graded.get("items") or [])
        }
        for f in entities:
            if not isinstance(f, dict):
                continue
            token = str(f.get("sequence_token") or f.get("token") or "").strip()
            if not token:
                continue
            item = graded_by_token.get(token) or {}
            ans = answers.get((problem.id, token))
            teacher_kept = (
                preserve_teacher_scores
                and ans is not None
                and isinstance(ans.detail, dict)
                and ans.detail.get("teacher_rescored")
            )
            if teacher_kept:
                try:
                    pts = float(ans.points_score) if ans.points_score is not None else 0.0
                except (TypeError, ValueError):
                    pts = 0.0
                detail = dict(ans.detail or {})
                try:
                    field_max = float(detail.get("max")) if detail.get("max") is not None else float(
                        item.get("max") or 0
                    )
                except (TypeError, ValueError):
                    field_max = float(item.get("max") or 0)
                p_earned += pts
                if field_max > 0:
                    # Max already included via graded max_total when not overridden.
                    pass
                continue

            try:
                pts_f = float(item.get("earned")) if item.get("earned") is not None else 0.0
            except (TypeError, ValueError):
                pts_f = 0.0
            try:
                auto_pts_f = (
                    float(item.get("auto_earned"))
                    if item.get("auto_earned") is not None
                    else pts_f
                )
            except (TypeError, ValueError):
                auto_pts_f = pts_f
            if item.get("requires_manual_grading"):
                requires_manual = True
                any_manual = True
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
            if ans is None:
                ans = m.StudentAssessmentAnswer.objects.create(
                    problem=problem,
                    field_token=token,
                    content=None,
                    points_score=pts_f,
                    auto_points_score=auto_pts_f,
                    detail=detail,
                )
                answers[(problem.id, token)] = ans
            else:
                ans.points_score = pts_f
                ans.auto_points_score = auto_pts_f
                ans.detail = detail
                ans.save(
                    update_fields=["points_score", "auto_points_score", "detail"]
                )
            p_earned += pts_f

        # Prefer graded max; teacher max overrides already reflected in field details.
        if p_max <= 0:
            p_max = float(problem.max_points or 0)
        problem.earned_points = p_earned
        problem.max_points = p_max
        problem.requires_manual_grading = requires_manual
        problem.save(
            update_fields=["earned_points", "max_points", "requires_manual_grading"]
        )
        earned_total += p_earned
        max_total += p_max

    if attempt.original_earned_points is None and attempt.earned_points is not None:
        attempt.original_earned_points = float(attempt.earned_points)
    if attempt.original_max_points is None and attempt.max_points is not None:
        attempt.original_max_points = float(attempt.max_points)
    attempt.earned_points = earned_total
    attempt.max_points = max_total
    if attempt.auto_graded_at is None:
        attempt.auto_graded_at = timezone.now()
    attempt.save(
        update_fields=[
            "earned_points",
            "max_points",
            "original_earned_points",
            "original_max_points",
            "auto_graded_at",
        ]
    )
    _upsert_final_grade(attempt)
    return {
        "success": True,
        "earned_total": earned_total,
        "max_total": max_total,
        "requires_manual_grading": any_manual,
    }


def notify_teachers_focus_enforcement_bypassed(attempt) -> None:
    """Inform course teachers that focus-leave client cooperation was missing."""
    from datetime import timedelta

    from .notifications import create_notification

    m = _models()
    template = course_template_assessment(attempt.assessment) or attempt.assessment
    course = attempt.course or (template.course if template is not None else None)
    if course is None:
        return
    student = attempt.user
    recent = timezone.now() - timedelta(hours=1)
    if m.Notification.objects.filter(
        reason="focus_leave_bypass",
        sender_id=getattr(student, "pk", None),
        creation_date__gte=recent,
        content__contains=f"attempt_id={attempt.id}",
    ).exists():
        return

    from .dashboard import user_display_name

    student_name = user_display_name(student) or (
        getattr(student, "username", None) or "Unknown student"
    )
    username = getattr(student, "username", None) or "—"
    assessment_name = (
        (template.name if template is not None else None)
        or (attempt.assessment.name if attempt.assessment else None)
        or f"Assessment {attempt.assessment_id}"
    )
    course_name = getattr(course, "name", None) or f"Course {course.id}"
    stamped = timezone.now()
    title = "Focus-leave enforcement bypassed"
    content = (
        f"{student_name} ({username}) submitted or updated answers for "
        f'"{assessment_name}" in {course_name} without the focus-leave '
        f"enforcement client active. Timestamp (UTC): {stamped.isoformat()}. "
        f"(attempt_id={attempt.id})"
    )
    teachers = m.UsersInCourse.objects.filter(
        course=course, user__user_type="Teacher", user__isnull=False
    ).select_related("user")
    seen = set()
    for row in teachers:
        if row.user_id in seen:
            continue
        seen.add(row.user_id)
        create_notification(
            row.user,
            title=title,
            content=content,
            reason="focus_leave_bypass",
            sender=student,
            creation_date=stamped,
        )
    owner = getattr(course, "owner", None)
    if owner is not None and owner.pk not in seen and getattr(owner, "user_type", None) == "Teacher":
        create_notification(
            owner,
            title=title,
            content=content,
            reason="focus_leave_bypass",
            sender=student,
            creation_date=stamped,
        )


def _upsert_final_grade(attempt):
    """
    Persist FinalGradeCalculation for this enrollment+template+series using the
    attempt that counts under Retake assessment scoring within that series.
    Voided attempts are ignored (e.g. "latest" falls back to the prior
    non-voided take in the same series).
    """
    m = _models()
    if not attempt.enrollment_id or not attempt.assessment_id:
        return
    take = attempt.assessment
    template = course_template_assessment(take) or take
    series = attempt_retake_series(attempt)
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
            retake_series=series,
        )
        .order_by("id")
    )
    counting = select_counting_attempt(siblings, template)
    if counting is None:
        m.FinalGradeCalculation.objects.filter(
            enrollment_id=attempt.enrollment_id,
            assessment_id=template_id,
            retake_series=series,
        ).delete()
        return

    from .assessment_grades import assessment_curve_bonus_points

    curve_bonus = assessment_curve_bonus_points(template)
    curved_earned = (
        float(counting.earned_points) + curve_bonus
        if counting.earned_points is not None
        else None
    )

    existing = m.FinalGradeCalculation.objects.filter(
        enrollment_id=attempt.enrollment_id,
        assessment_id=template_id,
        retake_series=series,
    ).first()
    if existing:
        existing.assessment_grade_points = curved_earned
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
            retake_series=series,
            assessment_grade_points=curved_earned,
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
    from .student_assessment_actions import student_has_open_retake

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
        if (getattr(enr.course, "status", None) or "") == "closed":
            continue
        assessments = m.Assessment.objects.filter(
            course=enr.course,
            parent_assessment__isnull=True,
            user__isnull=True,
        ).exclude(status__in=("deleted", "hidden"))
        for assessment in assessments:
            # Include historic take/retake rows under the course template — not
            # just attempts that still point at the template itself.
            attempts = list(
                attempts_qs_for_template(assessment)
                .filter(enrollment=enr)
                .order_by("id")
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
            facing = student_facing_assessment_status(assessment, now=now)
            is_redo = bool(
                student_has_open_retake(assessment, student)
                and not assessment_is_takeable(assessment, now=now)
            )
            rows.append(
                {
                    "course_id": enr.course_id,
                    "course_name": enr.course.name if enr.course else "",
                    "assessment_id": assessment.id,
                    "assessment_name": assessment.name,
                    "attempt_status": attempt.status if attempt else None,
                    "display_status": "REDO" if is_redo else facing,
                    "is_redo": is_redo,
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
