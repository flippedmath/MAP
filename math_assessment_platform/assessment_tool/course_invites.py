"""
Course invitation helpers for Teacher/IT Course Management.

Enrollment into a course slot only happens after the Student account is
email-verified (unactivated_account is false) and the invite is still pending.
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

from .models import UserCourseActivation, UserProfile, UsersInCourse
from .course_enrollment import start_enrollment_for_slot

logger = logging.getLogger(__name__)

INVITE_SESSION_KEY = "pending_course_invite_code"
INVITE_TTL = timedelta(days=14)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def user_can_manage_course(user, course) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "user_type", None) == "IT_Support":
        return True
    if getattr(user, "user_type", None) != "Teacher":
        return False
    return UsersInCourse.objects.filter(
        course=course,
        user=user,
        user__user_type="Teacher",
    ).exists()


def _aware(dt):
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt


def invite_is_expired(invite) -> bool:
    timeout = _aware(invite.timeout)
    if timeout is None:
        return False
    return timeout <= timezone.now()


def invite_is_redeemable(invite) -> bool:
    return (
        invite is not None
        and invite.status == UserCourseActivation.STATUS_PENDING
        and not invite_is_expired(invite)
    )


def normalize_recipient(raw: str) -> tuple[str, str]:
    """
    Return (kind, value) where kind is 'email' or 'username'.
    """
    value = (raw or "").strip()
    if not value:
        raise ValueError("Enter an email address or username.")
    if EMAIL_RE.match(value):
        return "email", BaseUserManager.normalize_email(value).lower()
    return "username", value.lower()


def _pending_for_course_email(course, email):
    if not email:
        return UserCourseActivation.objects.none()
    return UserCourseActivation.objects.filter(
        course=course,
        status=UserCourseActivation.STATUS_PENDING,
        temp_email__iexact=email,
    )


def _pending_for_course_user(course, user):
    if user is None:
        return UserCourseActivation.objects.none()
    return UserCourseActivation.objects.filter(
        course=course,
        status=UserCourseActivation.STATUS_PENDING,
        target_user=user,
    )


def _user_already_enrolled(course, user) -> bool:
    if user is None:
        return False
    return UsersInCourse.objects.filter(course=course, user=user).exists()


def user_already_enrolled_in_course(course, user) -> bool:
    return _user_already_enrolled(course, user)


@transaction.atomic
def create_course_invite(*, course, created_by, recipient_raw: str) -> UserCourseActivation:
    kind, value = normalize_recipient(recipient_raw)
    target_user = None
    temp_email = None
    invited_username = None

    if kind == "email":
        temp_email = value
        target_user = UserProfile.objects.filter(user_email__iexact=temp_email).first()
        if target_user and target_user.user_type != "Student":
            raise ValueError(
                f"“{temp_email}” is registered as {target_user.user_type}, not as a Student, "
                "so they cannot be enrolled with a student invitation. "
                "See Help (coming soon) for how to invite a co-Teacher to a course."
            )
        if target_user and _user_already_enrolled(course, target_user):
            raise ValueError("That student is already enrolled in this course.")
        if _pending_for_course_email(course, temp_email).exists():
            raise ValueError("A pending invitation already exists for that email.")
        if target_user and _pending_for_course_user(course, target_user).exists():
            raise ValueError("A pending invitation already exists for that student.")
    else:
        invited_username = value
        target_user = UserProfile.objects.filter(username__iexact=value).first()
        if target_user is None:
            raise ValueError("No user exists with that username.")
        if target_user.user_type != "Student":
            raise ValueError(
                f"“{target_user.username}” is registered as {target_user.user_type}, not as a Student, "
                "so they cannot be enrolled with a student invitation. "
                "See Help (coming soon) for how to invite a co-Teacher to a course."
            )
        if _user_already_enrolled(course, target_user):
            raise ValueError("That student is already enrolled in this course.")
        if _pending_for_course_user(course, target_user).exists():
            raise ValueError("A pending invitation already exists for that student.")
        temp_email = (target_user.user_email or "").strip().lower() or None
        if temp_email and _pending_for_course_email(course, temp_email).exclude(
            target_user=target_user
        ).exists():
            raise ValueError("A pending invitation already exists for that email.")

    # Empty slot only — existing students are NOT enrolled until they accept the invite link.
    slot = UsersInCourse.objects.create(
        user=None,
        course=course,
        user_access="active",
        creation_date=timezone.now(),
    )

    invite = UserCourseActivation.objects.create(
        course=course,
        slot=slot,
        temp_email=temp_email,
        code=secrets.token_urlsafe(24),
        timeout=timezone.now() + INVITE_TTL,
        status=UserCourseActivation.STATUS_PENDING,
        invited_username=invited_username,
        target_user=target_user,
        created_by=created_by,
        creation_date=timezone.now(),
    )

    # TODO: send invitation email when SMTP is wired.
    if target_user is not None:
        try:
            from .notifications import create_notification, REASON_COURSE_INVITATION

            invite_path = reverse(
                "course_invite_redeem", kwargs={"code": invite.code}
            )
            create_notification(
                target_user,
                title=f"Course invitation: {course.name}",
                content={
                    "course_id": course.id,
                    "course_name": course.name,
                    "invite_code": invite.code,
                    "invite_path": invite_path,
                    "message": (
                        f"You have been invited to join {course.name}. "
                        "Open the invitation link and accept to activate your access. "
                        "You are not enrolled until you confirm."
                    ),
                },
                reason=REASON_COURSE_INVITATION,
                sender=created_by,
            )
        except Exception:
            logger.exception("Failed to notify invitee for invite id=%s", invite.pk)

    return invite


@transaction.atomic
def void_course_invite(invite: UserCourseActivation) -> None:
    """
    Permanently remove a pending invitation (same as deleting the
    ``user_course_activation`` row). Empty unused course slots are removed too.

    TODO(credits): When the credit system is implemented, reimburse the Teacher
    for credits spent to extend this invite if it was never accepted/activated.
    """
    invite = UserCourseActivation.objects.select_for_update().select_related("slot").get(
        pk=invite.pk
    )
    if invite.status != UserCourseActivation.STATUS_PENDING:
        raise ValueError("Only pending invitations can be voided.")

    slot = invite.slot
    slot_id = invite.slot_id
    invite_id = invite.pk
    invite.delete()

    # TODO(credits): reimburse Teacher credits for unused invite (invite_id=%s).
    _ = invite_id  # reserved for future credit ledger linkage

    if slot_id and slot is not None and slot.user_id is None:
        UsersInCourse.objects.filter(pk=slot_id, user__isnull=True).delete()


def get_invite_by_code(code: str):
    if not code:
        return None
    return (
        UserCourseActivation.objects.select_related(
            "course", "slot", "target_user", "created_by"
        )
        .filter(code=code)
        .first()
    )


def invite_status_label(status: str) -> str:
    labels = {
        UserCourseActivation.STATUS_PENDING: "Pending — awaiting student acceptance",
        UserCourseActivation.STATUS_ACCEPTED: "Accepted — enrolled",
        UserCourseActivation.STATUS_VOIDED: "Voided",
    }
    return labels.get(status, status or "—")


INVALID_OR_VOIDED_INVITE_MESSAGE = (
    "This invitation link has either been voided, is invalid, or has already been used. "
    "If this is a mistake, reach out to the Teacher who extended the course "
    "enrollment invitation."
)


def redeem_block_reason(invite) -> str | None:
    """Human-readable reason the invite cannot be used, or None if redeemable."""
    if invite is None:
        return INVALID_OR_VOIDED_INVITE_MESSAGE
    if invite.status == UserCourseActivation.STATUS_VOIDED:
        # Legacy rows only; voiding now deletes the invite.
        return INVALID_OR_VOIDED_INVITE_MESSAGE
    if invite.status == UserCourseActivation.STATUS_ACCEPTED:
        # Legacy accepted rows; new accepts delete the invite instead.
        return INVALID_OR_VOIDED_INVITE_MESSAGE
    if invite.status != UserCourseActivation.STATUS_PENDING:
        return "This invitation is not available."
    if invite_is_expired(invite):
        return "This invitation has expired."
    return None


def is_unclaimed_email_invite(invite) -> bool:
    """Email invite not yet bound to a specific account (new-email / open redeem)."""
    if invite is None:
        return False
    if invite.status != UserCourseActivation.STATUS_PENDING:
        return False
    if invite.invited_username:
        return False
    return invite.target_user_id is None and bool(invite.temp_email)


def invite_sent_email(invite) -> str | None:
    if invite is None or not invite.temp_email:
        return None
    return invite.temp_email.strip().lower()


def user_matches_invite(user, invite) -> bool:
    if user is None or invite is None:
        return False
    if invite.target_user_id and invite.target_user_id == user.user_id:
        return True
    if invite.temp_email and user.user_email and user.user_email.lower() == invite.temp_email.lower():
        return True
    return False


def _display_name_for(user) -> str:
    return (
        user.user_display_name
        or " ".join(
            part for part in [user.user_first_name, user.user_last_name] if part
        ).strip()
        or user.username
    )


def _notify_teacher_already_enrolled(invite, user, *, original_email, original_username):
    teacher = invite.created_by
    if teacher is None:
        try:
            teacher = UserProfile.objects.filter(pk=invite.created_by_id).first()
        except Exception:
            teacher = None
    if teacher is None:
        return
    try:
        from .notifications import (
            create_notification,
            REASON_COURSE_INVITATION_ALREADY_ENROLLED,
        )

        management_path = (
            reverse("course_management", kwargs={"course_id": invite.course_id})
            + f"?invite={invite.pk}"
        )
        create_notification(
            teacher,
            title=f"Already-enrolled student used an invite ({invite.course.name})",
            content={
                "course_id": invite.course_id,
                "course_name": invite.course.name,
                "invite_id": invite.pk,
                "invite_code": invite.code,
                "course_management_path": management_path,
                "invitation_sent_to_email": original_email,
                "invitation_sent_to_username": original_username,
                "accessor_username": user.username,
                "accessor_display_name": _display_name_for(user),
                "accessor_email": user.user_email,
                "message": (
                    f"{_display_name_for(user)} ({user.username} / {user.user_email}) "
                    f"opened or tried to accept an invitation for {invite.course.name}, "
                    "but they are already enrolled. Consider voiding this invitation and "
                    "re-sending it to the intended recipient."
                ),
            },
            reason=REASON_COURSE_INVITATION_ALREADY_ENROLLED,
            sender=user,
        )
    except Exception:
        logger.exception(
            "Failed to notify teacher of already-enrolled invite access for invite id=%s",
            invite.pk,
        )


def handle_already_enrolled_invite_access(invite, user) -> str:
    """
    Student is already in the course. Inform them and notify the teacher.
    Does not consume/accept the pending invite.
    """
    original_email = invite.temp_email
    original_username = invite.invited_username or (
        invite.target_user.username if invite.target_user_id else None
    )
    _notify_teacher_already_enrolled(
        invite,
        user,
        original_email=original_email,
        original_username=original_username,
    )
    return (
        f"You are already enrolled in {invite.course.name}. "
        "No further action is needed for this invitation. "
        "Your teacher has been notified in case this link was meant for someone else."
    )


def _notify_teacher_different_account(invite, user, *, original_email, original_username):
    teacher = invite.created_by
    if teacher is None:
        return
    try:
        from .notifications import (
            create_notification,
            REASON_COURSE_INVITATION_DIFFERENT_ACCOUNT,
        )

        display_name = _display_name_for(user)
        invite_path = reverse(
            "course_invite_redeem", kwargs={"code": invite.code}
        )
        create_notification(
            teacher,
            title=f"Invitation accepted with a different account ({invite.course.name})",
            content={
                "course_id": invite.course_id,
                "course_name": invite.course.name,
                "invite_id": invite.pk,
                "invite_code": invite.code,
                "invite_path": invite_path,
                "invitation_sent_to_email": original_email,
                "invitation_sent_to_username": original_username,
                "accepted_username": user.username,
                "accepted_display_name": display_name,
                "accepted_email": user.user_email,
                "message": (
                    f"The invitation sent to {original_email or original_username or 'the recipient'} "
                    f"was accepted using a different student account "
                    f"({user.username} / {user.user_email})."
                ),
            },
            reason=REASON_COURSE_INVITATION_DIFFERENT_ACCOUNT,
            sender=user,
        )
    except Exception:
        logger.exception(
            "Failed to notify teacher of alternate-account accept for invite id=%s",
            invite.pk,
        )


@transaction.atomic
def claim_invite_for_new_user(invite: UserCourseActivation, user: UserProfile) -> UserCourseActivation:
    invite = UserCourseActivation.objects.select_for_update().get(pk=invite.pk)
    reason = redeem_block_reason(invite)
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
def enroll_user_from_invite(invite: UserCourseActivation, user: UserProfile) -> tuple[bool, str]:
    """
    Bind the student to the course slot if allowed.

    Returns (enrolled: bool, message: str).
    """
    invite = (
        UserCourseActivation.objects.select_for_update()
        .select_related("slot", "course")
        .get(pk=invite.pk)
    )

    if getattr(user, "user_type", None) != "Student":
        return False, "Only student accounts can accept course invitations."

    if getattr(user, "unactivated_account", False):
        return False, "Verify your email before joining the course."

    if invite.status == UserCourseActivation.STATUS_VOIDED:
        return (
            False,
            INVALID_OR_VOIDED_INVITE_MESSAGE,
        )
    # Legacy accepted rows (pre delete-on-accept); treat as consumed.
    if invite.status == UserCourseActivation.STATUS_ACCEPTED:
        if invite.slot_id and invite.slot.user_id == user.user_id:
            return True, "You are already enrolled in this course via this invitation."
        return False, INVALID_OR_VOIDED_INVITE_MESSAGE
    if invite.status != UserCourseActivation.STATUS_PENDING:
        return False, "This invitation is not available."
    if invite_is_expired(invite):
        return False, "This invitation has expired."

    matches = user_matches_invite(user, invite)
    alternate_ok = is_unclaimed_email_invite(invite) and not matches
    if invite.target_user_id and invite.target_user_id != user.user_id:
        return False, "This invitation is assigned to a different user."
    if not matches and not alternate_ok:
        return False, "This invitation does not match your account."

    original_email = invite.temp_email
    original_username = invite.invited_username
    used_different_account = bool(
        alternate_ok
        or (
            original_email
            and user.user_email
            and original_email.lower() != user.user_email.lower()
        )
    )

    if _user_already_enrolled(invite.course, user):
        # Keep invite pending so the teacher can void and re-send to the intended recipient.
        msg = handle_already_enrolled_invite_access(
            invite,
            user,
        )
        return False, msg

    slot = invite.slot
    if slot.user_id and slot.user_id != user.user_id:
        return False, "This course slot is no longer available."

    course_name = invite.course.name
    slot.user = user
    slot.user_access = "active"
    slot.save(update_fields=["user", "user_access"])

    # Durable enrollment stint (separate from seat); grades for this period key off it.
    start_enrollment_for_slot(course=invite.course, user=user, slot=slot)

    if used_different_account:
        _notify_teacher_different_account(
            invite,
            user,
            original_email=original_email,
            original_username=original_username,
        )

    # Invite is consumed: remove redeemable row; enrollment lives on users_in_course
    # plus student_course_enrollment.
    invite.delete()

    if used_different_account:
        return (
            True,
            f"You have joined {course_name}. "
            f"Your account email ({user.user_email}) was used instead of the invitation email "
            f"({original_email}).",
        )

    return True, f"You have joined {course_name}."


def complete_course_invite_if_pending(user, invite_code: str | None = None) -> tuple[bool, str | None]:
    """
    After email verification (or Accept), enroll if a matching pending invite exists.

    Prefer explicit invite_code (session); else find pending invite claimed by / matching user.
    If the session invite code no longer exists (void/delete), surface that clearly without enrolling.
    """
    if user is None:
        return False, None
    if getattr(user, "unactivated_account", False):
        return False, None

    invite = None
    if invite_code:
        invite = get_invite_by_code(invite_code)
        if invite is None:
            # Invite was voided/deleted after signup started.
            return False, INVALID_OR_VOIDED_INVITE_MESSAGE

    if invite is None:
        invite = (
            UserCourseActivation.objects.filter(
                status=UserCourseActivation.STATUS_PENDING,
                target_user=user,
            )
            .order_by("-creation_date", "-pk")
            .first()
        )
    if invite is None and user.user_email:
        invite = (
            UserCourseActivation.objects.filter(
                status=UserCourseActivation.STATUS_PENDING,
                temp_email__iexact=user.user_email,
            )
            .filter(Q(target_user__isnull=True) | Q(target_user=user))
            .order_by("-creation_date", "-pk")
            .first()
        )

    if invite is None:
        return False, None

    enrolled, message = enroll_user_from_invite(invite, user)
    return enrolled, message
