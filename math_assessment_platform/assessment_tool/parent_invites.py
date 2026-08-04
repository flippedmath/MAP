"""
Parent grade-access invitation helpers for Teacher/IT Course Management.

A ParentUserCourse row is created only after a Parent accepts (and verifies email
when signing up). Invite void/accept hard-delete the parent_course_invitation row.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import timedelta

from django.contrib.auth.base_user import BaseUserManager
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .folder_roots import (
    WORKSPACE_COURSE_MANAGEMENT_MESSAGE,
    course_is_under_workspace,
)
from .models import ParentCourseInvitation, ParentUserCourse, UserProfile, UsersInCourse
from .dashboard import user_display_name

logger = logging.getLogger(__name__)

PARENT_INVITE_SESSION_KEY = "pending_parent_invite_code"
PARENT_INVITE_TTL = timedelta(days=14)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

INVALID_OR_VOIDED_PARENT_INVITE_MESSAGE = (
    "This parent invitation link has either been voided, is invalid, or has already been used. "
    "If this is a mistake, reach out to the Teacher who sent the invitation."
)


def _aware(dt):
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt


def parent_invite_is_expired(invite) -> bool:
    timeout = _aware(invite.timeout)
    if timeout is None:
        return False
    return timeout <= timezone.now()


def parent_invite_is_redeemable(invite) -> bool:
    return (
        invite is not None
        and invite.status == ParentCourseInvitation.STATUS_PENDING
        and not parent_invite_is_expired(invite)
    )


def normalize_parent_email(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ValueError("Enter a parent email address.")
    if not EMAIL_RE.match(value):
        raise ValueError("Enter a valid parent email address.")
    return BaseUserManager.normalize_email(value).lower()


def student_enrolled_in_course(course, student) -> bool:
    if student is None:
        return False
    return UsersInCourse.objects.filter(
        course=course,
        user=student,
        user__user_type="Student",
    ).exists()


def parent_has_course_access(*, parent, student, course) -> bool:
    if parent is None or student is None or course is None:
        return False
    return ParentUserCourse.objects.filter(
        parent=parent,
        student=student,
        course=course,
    ).exists()


def _pending_for_course_student_email(course, student, email):
    if not email:
        return ParentCourseInvitation.objects.none()
    return ParentCourseInvitation.objects.filter(
        course=course,
        student=student,
        status=ParentCourseInvitation.STATUS_PENDING,
        temp_email__iexact=email,
    )


def _pending_for_course_student_user(course, student, user):
    if user is None:
        return ParentCourseInvitation.objects.none()
    return ParentCourseInvitation.objects.filter(
        course=course,
        student=student,
        status=ParentCourseInvitation.STATUS_PENDING,
        target_user=user,
    )


def _display_name_for(user) -> str:
    return user_display_name(user)


@transaction.atomic
def grant_parent_access(*, course, parent, student, created_by=None) -> ParentUserCourse:
    """
    Grant an existing Parent grade access for an enrolled Student in this course.
    """
    _ = created_by
    if course_is_under_workspace(course):
        raise ValueError(WORKSPACE_COURSE_MANAGEMENT_MESSAGE)
    if getattr(parent, "user_type", None) != "Parent":
        raise ValueError("Only Parent accounts can be granted grade access.")
    if getattr(student, "user_type", None) != "Student":
        raise ValueError("Grade access must be linked to a Student.")
    if not student_enrolled_in_course(course, student):
        raise ValueError("That student is not enrolled in this course.")
    existing = ParentUserCourse.objects.filter(
        parent=parent, student=student, course=course
    ).first()
    if existing is not None:
        return existing
    return ParentUserCourse.objects.create(
        parent=parent,
        student=student,
        course=course,
    )


@transaction.atomic
def revoke_parent_access(*, course, parent, student) -> bool:
    """
    Remove Parent grade access for this Student+Course. Returns True if a row was deleted.
    """
    deleted, _ = ParentUserCourse.objects.filter(
        parent=parent,
        student=student,
        course=course,
    ).delete()
    return deleted > 0


def parent_access_rows_for_course(course) -> list[dict]:
    """
    For enrolled students, list Parents who already have at least one
    parent_user_course link for that Student (any course).
    """
    enrolled_ids = list(
        UsersInCourse.objects.filter(
            course=course,
            user__isnull=False,
            user__user_type="Student",
        ).values_list("user_id", flat=True)
    )
    if not enrolled_ids:
        return []

    links = list(
        ParentUserCourse.objects.filter(student_id__in=enrolled_ids)
        .select_related("parent", "student")
        .order_by(
            "student__user_last_name",
            "student__user_first_name",
            "parent__user_last_name",
            "parent__user_first_name",
            "parent__username",
        )
    )
    pairs: dict[tuple[int, int], dict] = {}
    for link in links:
        key = (link.parent_id, link.student_id)
        row = pairs.get(key)
        if row is None:
            parent = link.parent
            student = link.student
            pairs[key] = {
                "parent_id": parent.user_id,
                "parent_name": _display_name_for(parent),
                "parent_username": parent.username,
                "student_id": student.user_id,
                "student_name": _display_name_for(student),
                "student_username": student.username,
                "has_access": link.course_id == course.id,
            }
        elif link.course_id == course.id:
            pairs[key]["has_access"] = True

    rows = list(pairs.values())
    rows.sort(
        key=lambda r: (
            (r["student_name"] or "").casefold(),
            (r["parent_name"] or "").casefold(),
            r["student_id"],
            r["parent_id"],
        )
    )
    return rows


@transaction.atomic
def create_parent_invite(*, course, created_by, student, parent_email_raw: str) -> ParentCourseInvitation:
    if course_is_under_workspace(course):
        raise ValueError(WORKSPACE_COURSE_MANAGEMENT_MESSAGE)
    if getattr(student, "user_type", None) != "Student":
        raise ValueError("Select an enrolled Student.")
    if not student_enrolled_in_course(course, student):
        raise ValueError("That student is not enrolled in this course.")

    temp_email = normalize_parent_email(parent_email_raw)
    target_user = UserProfile.objects.filter(user_email__iexact=temp_email).first()
    if target_user and target_user.user_type != "Parent":
        raise ValueError(
            f"“{temp_email}” is registered as {target_user.user_type}, not as a Parent, "
            "so they cannot be invited for parent grade access."
        )
    if target_user and parent_has_course_access(
        parent=target_user, student=student, course=course
    ):
        raise ValueError("That parent already has grade access for this student in this course.")
    if _pending_for_course_student_email(course, student, temp_email).exists():
        raise ValueError("A pending parent invitation already exists for that email and student.")
    if target_user and _pending_for_course_student_user(course, student, target_user).exists():
        raise ValueError("A pending parent invitation already exists for that parent and student.")

    invite = ParentCourseInvitation.objects.create(
        course=course,
        student=student,
        temp_email=temp_email,
        code=secrets.token_urlsafe(24),
        timeout=timezone.now() + PARENT_INVITE_TTL,
        status=ParentCourseInvitation.STATUS_PENDING,
        target_user=target_user,
        created_by=created_by,
        creation_date=timezone.now(),
    )

    invite_path = reverse("parent_invite_redeem", kwargs={"code": invite.code})
    if target_user is not None:
        try:
            from .notifications import create_notification, REASON_PARENT_COURSE_INVITATION

            create_notification(
                target_user,
                title=f"Parent grade access invitation: {course.name}",
                content={
                    "course_id": course.id,
                    "course_name": course.name,
                    "student_id": student.user_id,
                    "student_name": _display_name_for(student),
                    "student_username": student.username,
                    "invite_code": invite.code,
                    "invite_path": invite_path,
                    "message": (
                        f"You have been invited to view grades for {_display_name_for(student)} "
                        f"in {course.name}. Open the invitation link and accept to activate access."
                    ),
                },
                reason=REASON_PARENT_COURSE_INVITATION,
                sender=created_by,
            )
        except Exception:
            logger.exception("Failed to notify parent invitee for invite id=%s", invite.pk)

    to_email = (invite.temp_email or "").strip() or (
        (getattr(target_user, "user_email", None) or "").strip() if target_user else ""
    )
    if to_email:
        from .mail import absolute_url, send_app_email

        student_label = _display_name_for(student)
        send_app_email(
            subject=f"Parent grade access invitation: {course.name}",
            message=(
                f"You have been invited to view grades for {student_label} "
                f"in {course.name}.\n\n"
                f"Open this link to accept:\n{absolute_url(invite_path)}\n\n"
                "If you did not expect this invitation, you can ignore this message.\n"
            ),
            recipient=to_email,
            fail_silently=True,
        )

    return invite


@transaction.atomic
def void_parent_invite(invite: ParentCourseInvitation) -> None:
    invite = ParentCourseInvitation.objects.select_for_update().get(pk=invite.pk)
    if invite.status != ParentCourseInvitation.STATUS_PENDING:
        raise ValueError("Only pending invitations can be voided.")
    invite.delete()


def get_parent_invite_by_code(code: str):
    if not code:
        return None
    return (
        ParentCourseInvitation.objects.select_related(
            "course", "student", "target_user", "created_by"
        )
        .filter(code=code)
        .first()
    )


def parent_invite_status_label(status: str) -> str:
    labels = {
        ParentCourseInvitation.STATUS_PENDING: "Pending — awaiting parent acceptance",
    }
    return labels.get(status, status or "—")


def parent_redeem_block_reason(invite) -> str | None:
    if invite is None:
        return INVALID_OR_VOIDED_PARENT_INVITE_MESSAGE
    if invite.status != ParentCourseInvitation.STATUS_PENDING:
        return INVALID_OR_VOIDED_PARENT_INVITE_MESSAGE
    if parent_invite_is_expired(invite):
        return "This invitation has expired."
    if not student_enrolled_in_course(invite.course, invite.student):
        return (
            "This invitation is no longer valid because the student is not enrolled "
            "in the course."
        )
    return None


def is_unclaimed_parent_email_invite(invite) -> bool:
    if invite is None:
        return False
    if invite.status != ParentCourseInvitation.STATUS_PENDING:
        return False
    return invite.target_user_id is None and bool(invite.temp_email)


def parent_user_matches_invite(user, invite) -> bool:
    if user is None or invite is None:
        return False
    if invite.target_user_id and invite.target_user_id == user.user_id:
        return True
    if invite.temp_email and user.user_email and user.user_email.lower() == invite.temp_email.lower():
        return True
    return False


def _notify_teacher_parent_already_has_access(invite, user, *, original_email):
    teacher = invite.created_by
    if teacher is None:
        return
    try:
        from .notifications import (
            create_notification,
            REASON_PARENT_COURSE_INVITATION_ALREADY_HAS_ACCESS,
        )

        management_path = (
            reverse("course_management", kwargs={"course_id": invite.course_id})
            + f"?parent_invite={invite.pk}"
        )
        create_notification(
            teacher,
            title=f"Parent with access used an invite ({invite.course.name})",
            content={
                "course_id": invite.course_id,
                "course_name": invite.course.name,
                "invite_id": invite.pk,
                "invite_code": invite.code,
                "course_management_path": management_path,
                "invitation_sent_to_email": original_email,
                "student_name": _display_name_for(invite.student),
                "student_username": invite.student.username if invite.student_id else None,
                "accessor_username": user.username,
                "accessor_display_name": _display_name_for(user),
                "accessor_email": user.user_email,
                "message": (
                    f"{_display_name_for(user)} ({user.username} / {user.user_email}) "
                    f"opened or tried to accept a parent invitation for {_display_name_for(invite.student)} "
                    f"in {invite.course.name}, but they already have access. Consider voiding this "
                    "invitation if it was meant for someone else."
                ),
            },
            reason=REASON_PARENT_COURSE_INVITATION_ALREADY_HAS_ACCESS,
            sender=user,
        )
    except Exception:
        logger.exception(
            "Failed to notify teacher of already-has-access parent invite id=%s",
            invite.pk,
        )


def handle_parent_already_has_access(invite, user) -> str:
    original_email = invite.temp_email
    _notify_teacher_parent_already_has_access(
        invite,
        user,
        original_email=original_email,
    )
    return (
        f"You already have grade access for {_display_name_for(invite.student)} "
        f"in {invite.course.name}. No further action is needed for this invitation. "
        "Your teacher has been notified in case this link was meant for someone else."
    )


def _notify_teacher_parent_different_account(invite, user, *, original_email):
    teacher = invite.created_by
    if teacher is None:
        return
    try:
        from .notifications import (
            create_notification,
            REASON_PARENT_COURSE_INVITATION_DIFFERENT_ACCOUNT,
        )

        invite_path = reverse("parent_invite_redeem", kwargs={"code": invite.code})
        create_notification(
            teacher,
            title=f"Parent invitation accepted with a different account ({invite.course.name})",
            content={
                "course_id": invite.course_id,
                "course_name": invite.course.name,
                "invite_id": invite.pk,
                "invite_code": invite.code,
                "invite_path": invite_path,
                "invitation_sent_to_email": original_email,
                "student_name": _display_name_for(invite.student),
                "student_username": invite.student.username if invite.student_id else None,
                "accepted_username": user.username,
                "accepted_display_name": _display_name_for(user),
                "accepted_email": user.user_email,
                "message": (
                    f"The parent invitation sent to {original_email or 'the recipient'} "
                    f"for {_display_name_for(invite.student)} in {invite.course.name} "
                    f"was accepted using a different Parent account "
                    f"({user.username} / {user.user_email})."
                ),
            },
            reason=REASON_PARENT_COURSE_INVITATION_DIFFERENT_ACCOUNT,
            sender=user,
        )
    except Exception:
        logger.exception(
            "Failed to notify teacher of alternate-account parent accept for invite id=%s",
            invite.pk,
        )


def _notify_teacher_non_parent_attempt(invite, user):
    teacher = invite.created_by
    if teacher is None:
        return
    try:
        from .notifications import (
            create_notification,
            REASON_PARENT_COURSE_INVITATION_WRONG_ACCOUNT_TYPE,
        )

        management_path = (
            reverse("course_management", kwargs={"course_id": invite.course_id})
            + f"?parent_invite={invite.pk}"
        )
        create_notification(
            teacher,
            title=f"Non-Parent account used a parent invite ({invite.course.name})",
            content={
                "course_id": invite.course_id,
                "course_name": invite.course.name,
                "invite_id": invite.pk,
                "invite_code": invite.code,
                "course_management_path": management_path,
                "invitation_sent_to_email": invite.temp_email,
                "student_name": _display_name_for(invite.student),
                "student_username": invite.student.username if invite.student_id else None,
                "accessor_username": user.username,
                "accessor_display_name": _display_name_for(user),
                "accessor_email": user.user_email,
                "accessor_user_type": getattr(user, "user_type", None),
                "message": (
                    f"{_display_name_for(user)} ({user.username}, {user.user_type}) "
                    f"tried to use a parent grade-access invitation for "
                    f"{_display_name_for(invite.student)} in {invite.course.name}."
                ),
            },
            reason=REASON_PARENT_COURSE_INVITATION_WRONG_ACCOUNT_TYPE,
            sender=user,
        )
    except Exception:
        logger.exception(
            "Failed to notify teacher of non-parent invite access for invite id=%s",
            invite.pk,
        )


def handle_non_parent_invite_access(invite, user) -> str:
    _notify_teacher_non_parent_attempt(invite, user)
    return (
        f"Your account is registered as {user.user_type}, not as a Parent, "
        "so it cannot accept a parent grade-access invitation. "
        "Log out and use a Parent account, or ask the Teacher to send a new invitation."
    )


@transaction.atomic
def claim_parent_invite_for_new_user(
    invite: ParentCourseInvitation, user: UserProfile
) -> ParentCourseInvitation:
    invite = ParentCourseInvitation.objects.select_for_update().get(pk=invite.pk)
    reason = parent_redeem_block_reason(invite)
    if reason:
        raise ValueError(reason)
    if invite.target_user_id and invite.target_user_id != user.user_id:
        raise ValueError("This invitation is already in use by another person.")
    invite.target_user = user
    if not invite.temp_email and user.user_email:
        invite.temp_email = user.user_email.lower()
    invite.save(update_fields=["target_user", "temp_email"])
    return invite


@transaction.atomic
def accept_parent_invite(invite: ParentCourseInvitation, user: UserProfile) -> tuple[bool, str]:
    """
    Create ParentUserCourse if allowed. Returns (granted: bool, message: str).
    """
    invite = (
        ParentCourseInvitation.objects.select_for_update()
        .select_related("course", "student")
        .get(pk=invite.pk)
    )

    if getattr(user, "user_type", None) != "Parent":
        return False, handle_non_parent_invite_access(invite, user)

    if course_is_under_workspace(invite.course):
        return False, WORKSPACE_COURSE_MANAGEMENT_MESSAGE

    if getattr(user, "unactivated_account", False):
        return False, "Verify your email before accepting parent grade access."

    block = parent_redeem_block_reason(invite)
    if block:
        return False, block

    matches = parent_user_matches_invite(user, invite)
    alternate_ok = is_unclaimed_parent_email_invite(invite) and not matches
    if invite.target_user_id and invite.target_user_id != user.user_id:
        return False, "This invitation is assigned to a different user."
    if not matches and not alternate_ok:
        return False, "This invitation does not match your account."

    original_email = invite.temp_email
    used_different_account = bool(
        alternate_ok
        or (
            original_email
            and user.user_email
            and original_email.lower() != user.user_email.lower()
        )
    )

    if parent_has_course_access(parent=user, student=invite.student, course=invite.course):
        msg = handle_parent_already_has_access(invite, user)
        return False, msg

    course_name = invite.course.name
    student_name = _display_name_for(invite.student)
    ParentUserCourse.objects.create(
        parent=user,
        student=invite.student,
        course=invite.course,
    )

    if used_different_account:
        _notify_teacher_parent_different_account(
            invite,
            user,
            original_email=original_email,
        )

    invite.delete()

    if used_different_account:
        return (
            True,
            f"You now have grade access for {student_name} in {course_name}. "
            f"Your account email ({user.user_email}) was used instead of the invitation email "
            f"({original_email}).",
        )

    return True, f"You now have grade access for {student_name} in {course_name}."


def complete_parent_invite_if_pending(user, invite_code: str | None = None) -> tuple[bool, str | None]:
    """
    After email verification (or Accept), grant access if a matching pending parent invite exists.
    """
    if user is None:
        return False, None
    if getattr(user, "user_type", None) != "Parent":
        return False, None
    if getattr(user, "unactivated_account", False):
        return False, None

    invite = None
    if invite_code:
        invite = get_parent_invite_by_code(invite_code)
        if invite is None:
            return False, INVALID_OR_VOIDED_PARENT_INVITE_MESSAGE

    if invite is None:
        invite = (
            ParentCourseInvitation.objects.filter(
                status=ParentCourseInvitation.STATUS_PENDING,
                target_user=user,
            )
            .order_by("-creation_date", "-pk")
            .first()
        )
    if invite is None and user.user_email:
        invite = (
            ParentCourseInvitation.objects.filter(
                status=ParentCourseInvitation.STATUS_PENDING,
                temp_email__iexact=user.user_email,
            )
            .filter(Q(target_user__isnull=True) | Q(target_user=user))
            .order_by("-creation_date", "-pk")
            .first()
        )

    if invite is None:
        return False, None

    granted, message = accept_parent_invite(invite, user)
    return granted, message
