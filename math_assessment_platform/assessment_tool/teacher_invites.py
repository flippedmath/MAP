"""Co-Teacher invite and roster helpers for Course Management."""

from __future__ import annotations

import logging
import re
import secrets
from datetime import timedelta

from django.contrib.auth.base_user import BaseUserManager
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .dashboard import user_display_name
from .models import Course, TeacherCourseInvitation, UserProfile, UsersInCourse
from .util import assign_user_to_course

logger = logging.getLogger(__name__)

TEACHER_INVITE_TTL = timedelta(days=14)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USER_ACCESS_ACTIVE = "active"
# Accounts that can be invited / listed as course Teachers (main or co-teacher).
COURSE_TEACHER_USER_TYPES = ("Teacher", "IT_Support")


def is_course_teacher_account(user) -> bool:
    return getattr(user, "user_type", None) in COURSE_TEACHER_USER_TYPES


def _aware(dt):
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt


def teacher_invite_is_expired(invite: TeacherCourseInvitation) -> bool:
    timeout = _aware(invite.timeout)
    if timeout is None:
        return False
    return timeout <= timezone.now()


def teacher_invite_is_redeemable(invite: TeacherCourseInvitation | None) -> bool:
    return invite is not None and not teacher_invite_is_expired(invite)


def teacher_roster_name(user) -> str:
    """Display name + last name, or first + last when no display name."""
    if user is None:
        return "—"
    display = (getattr(user, "user_display_name", None) or "").strip()
    first = (getattr(user, "user_first_name", None) or "").strip()
    last = (getattr(user, "user_last_name", None) or "").strip()
    if display:
        if last and last.lower() not in display.lower():
            return f"{display} {last}".strip()
        return display
    full = f"{first} {last}".strip()
    return full or (getattr(user, "username", None) or "—")


def user_is_course_owner(user, course) -> bool:
    if user is None or course is None:
        return False
    owner_id = getattr(course, "owner_id", None)
    user_id = getattr(user, "user_id", None) or getattr(user, "pk", None)
    return bool(owner_id and user_id and owner_id == user_id)


def user_can_manage_teachers(user, course) -> bool:
    """Only the main teacher (owner) or IT can invite/remove/transfer."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "user_type", None) == "IT_Support":
        return True
    return is_course_teacher_account(user) and user_is_course_owner(user, course)


def teacher_is_active_on_course(user, course) -> bool:
    if user is None or course is None:
        return False
    if not is_course_teacher_account(user):
        return False
    return UsersInCourse.objects.filter(
        course=course,
        user=user,
        user_access=USER_ACCESS_ACTIVE,
    ).exists()


def normalize_teacher_recipient(raw: str) -> tuple[str, str]:
    value = (raw or "").strip()
    if not value:
        raise ValueError("Enter a Teacher or IT Support username or email.")
    if EMAIL_RE.match(value):
        return "email", BaseUserManager.normalize_email(value).lower()
    return "username", value


def find_teacher_by_username_or_email(identifier: str) -> UserProfile | None:
    kind, value = normalize_teacher_recipient(identifier)
    qs = UserProfile.objects.filter(user_type__in=COURSE_TEACHER_USER_TYPES)
    if kind == "email":
        return qs.filter(user_email__iexact=value).first()
    return qs.filter(username__iexact=value).first()


def serialize_teacher_preview(user: UserProfile) -> dict:
    return {
        "user_id": user.user_id,
        "username": user.username,
        "email": (user.user_email or "").strip(),
        "first_name": (user.user_first_name or "").strip(),
        "last_name": (user.user_last_name or "").strip(),
        "display_name": (user.user_display_name or "").strip(),
        "roster_name": teacher_roster_name(user),
        "organization": (user.organization or "").strip(),
        "user_type": user.user_type,
        "user_type_label": (
            "IT Support" if user.user_type == "IT_Support" else "Teacher"
        ),
    }


def lookup_teacher_for_invite(*, course, recipient_raw: str) -> dict:
    teacher = find_teacher_by_username_or_email(recipient_raw)
    if teacher is None:
        raise ValueError(
            "No Teacher or IT Support account matches that username or email. "
            "Co-teachers must already have a Teacher or IT Support account."
        )
    if user_is_course_owner(teacher, course):
        raise ValueError("That user is already the main teacher for this course.")
    if teacher_is_active_on_course(teacher, course):
        raise ValueError("That user is already a teacher on this course.")
    if TeacherCourseInvitation.objects.filter(
        course=course, invitee=teacher
    ).exists():
        raise ValueError("That user already has a pending invitation for this course.")
    return serialize_teacher_preview(teacher)


def _notify_teacher_invited(*, invite: TeacherCourseInvitation) -> None:
    from .notifications import REASON_TEACHER_COURSE_INVITATION, create_notification

    course = invite.course
    inviter = invite.invited_by
    path = reverse("teacher_invite_redeem", kwargs={"code": invite.code})
    create_notification(
        invite.invitee,
        title=f"Co-teacher invitation: {course.name}",
        content={
            "message": (
                f"{user_display_name(inviter) or inviter.username} invited you to "
                f"co-teach “{course.name}”."
            ),
            "course_id": course.id,
            "course_name": course.name,
            "inviter_name": user_display_name(inviter) or inviter.username,
            "invite_path": path,
            "invite_code": invite.code,
        },
        reason=REASON_TEACHER_COURSE_INVITATION,
        sender=inviter,
    )


@transaction.atomic
def create_teacher_invite(*, course, created_by, recipient_raw: str) -> TeacherCourseInvitation:
    if not user_can_manage_teachers(created_by, course):
        raise ValueError("Only the main teacher can invite co-teachers.")
    preview = lookup_teacher_for_invite(course=course, recipient_raw=recipient_raw)
    invitee = UserProfile.objects.get(
        pk=preview["user_id"],
        user_type__in=COURSE_TEACHER_USER_TYPES,
    )
    invite = TeacherCourseInvitation.objects.create(
        course=course,
        invitee=invitee,
        invited_by=created_by,
        code=secrets.token_urlsafe(32),
        creation_date=timezone.now(),
        timeout=timezone.now() + TEACHER_INVITE_TTL,
    )
    _notify_teacher_invited(invite=invite)
    return invite


@transaction.atomic
def void_teacher_invite(invite: TeacherCourseInvitation, *, by_user=None) -> None:
    if invite is None:
        raise ValueError("Invitation not found.")
    if by_user is not None and not user_can_manage_teachers(by_user, invite.course):
        raise ValueError("Only the main teacher can void co-teacher invitations.")
    invite.delete()


@transaction.atomic
def accept_teacher_invite(*, invite: TeacherCourseInvitation, user) -> UsersInCourse:
    if not teacher_invite_is_redeemable(invite):
        raise ValueError("This co-teacher invitation is invalid or has expired.")
    if user is None or not getattr(user, "is_authenticated", False):
        raise ValueError("Log in as the invited account to accept.")
    if not is_course_teacher_account(user):
        raise ValueError(
            "Only Teacher or IT Support accounts can accept co-teacher invitations."
        )
    if user.user_id != invite.invitee_id:
        raise ValueError("This invitation was sent to a different account.")
    course = invite.course
    if teacher_is_active_on_course(user, course):
        invite.delete()
        return UsersInCourse.objects.get(course=course, user=user)
    membership = assign_user_to_course(user, course, authenticate=True)
    if membership.user_access != USER_ACCESS_ACTIVE:
        membership.user_access = USER_ACCESS_ACTIVE
        membership.save(update_fields=["user_access"])
    invite.delete()
    return membership


@transaction.atomic
def reject_teacher_invite(*, invite: TeacherCourseInvitation, user) -> None:
    if invite is None:
        raise ValueError("Invitation not found.")
    if user is None or user.user_id != invite.invitee_id:
        raise ValueError("Only the invited user can reject this invitation.")
    invite.delete()


@transaction.atomic
def remove_teacher_from_course(*, course, teacher, removed_by) -> None:
    if not user_can_manage_teachers(removed_by, course):
        raise ValueError("Only the main teacher can remove co-teachers.")
    if user_is_course_owner(teacher, course):
        raise ValueError("The main teacher cannot be removed from the course.")
    if not is_course_teacher_account(teacher):
        raise ValueError("Only Teacher or IT Support accounts can be course teachers.")
    pending = TeacherCourseInvitation.objects.filter(
        course=course, invitee=teacher
    ).first()
    if pending is not None:
        pending.delete()
        return
    deleted, _ = UsersInCourse.objects.filter(
        course=course,
        user=teacher,
    ).delete()
    if not deleted:
        raise ValueError("That user is not a teacher on this course.")


@transaction.atomic
def leave_course_as_teacher(*, course, teacher) -> None:
    if user_is_course_owner(teacher, course):
        raise ValueError(
            "The main teacher cannot leave the course. "
            "Transfer ownership to another teacher first."
        )
    pending = TeacherCourseInvitation.objects.filter(
        course=course, invitee=teacher
    ).first()
    if pending is not None and pending.invitee_id == teacher.user_id:
        pending.delete()
        return
    deleted, _ = UsersInCourse.objects.filter(
        course=course,
        user=teacher,
    ).delete()
    if not deleted:
        raise ValueError("You are not a teacher on this course.")


@transaction.atomic
def transfer_course_ownership(*, course, new_owner, by_user) -> Course:
    if not user_can_manage_teachers(by_user, course):
        raise ValueError("Only the main teacher can transfer ownership.")
    if not is_course_teacher_account(new_owner):
        raise ValueError(
            "Ownership can only transfer to a Teacher or IT Support account."
        )
    if user_is_course_owner(new_owner, course):
        raise ValueError("That user is already the main teacher.")
    if not teacher_is_active_on_course(new_owner, course):
        raise ValueError(
            "Ownership can only transfer to an active co-teacher on this course."
        )
    # Ensure outgoing owner keeps an active teacher seat.
    if by_user and is_course_teacher_account(by_user):
        if not teacher_is_active_on_course(by_user, course):
            assign_user_to_course(by_user, course, authenticate=True)
    course.owner = new_owner
    course.save(update_fields=["owner"])
    return course


def list_course_teacher_rows(*, course, viewer) -> list[dict]:
    """Rows for the Course Management teachers table (owner, co-teachers, pending)."""
    rows = []
    owner = course.owner
    seen_ids = set()
    if owner is not None:
        seen_ids.add(owner.user_id)
        rows.append(
            {
                "user_id": owner.user_id,
                "roster_name": teacher_roster_name(owner),
                "username": owner.username,
                "organization": (owner.organization or "").strip() or "—",
                "role": "main",
                "role_label": "Main teacher",
                "status": "active",
                "status_label": "Active",
                "invite_id": None,
                "can_make_main": False,
                "can_remove": False,
                "can_leave": False,
            }
        )

    memberships = (
        UsersInCourse.objects.filter(
            course=course,
            user__isnull=False,
            user__user_type__in=COURSE_TEACHER_USER_TYPES,
            user_access=USER_ACCESS_ACTIVE,
        )
        .select_related("user")
        .order_by("user__user_last_name", "user__user_first_name", "user__username")
    )
    can_manage = user_can_manage_teachers(viewer, course)
    for slot in memberships:
        teacher = slot.user
        if teacher.user_id in seen_ids:
            continue
        seen_ids.add(teacher.user_id)
        is_self = viewer is not None and teacher.user_id == getattr(
            viewer, "user_id", None
        )
        rows.append(
            {
                "user_id": teacher.user_id,
                "roster_name": teacher_roster_name(teacher),
                "username": teacher.username,
                "organization": (teacher.organization or "").strip() or "—",
                "role": "co",
                "role_label": "Co-teacher",
                "status": "active",
                "status_label": "Active",
                "invite_id": None,
                "can_make_main": can_manage,
                "can_remove": can_manage,
                "can_leave": is_self and not user_is_course_owner(teacher, course),
            }
        )

    pending = (
        TeacherCourseInvitation.objects.filter(course=course)
        .select_related("invitee")
        .order_by("-creation_date", "-id")
    )
    for invite in pending:
        teacher = invite.invitee
        if teacher.user_id in seen_ids:
            continue
        is_self = viewer is not None and teacher.user_id == getattr(
            viewer, "user_id", None
        )
        rows.append(
            {
                "user_id": teacher.user_id,
                "roster_name": teacher_roster_name(teacher),
                "username": teacher.username,
                "organization": (teacher.organization or "").strip() or "—",
                "role": "co",
                "role_label": "Co-teacher",
                "status": "pending",
                "status_label": "Pending",
                "invite_id": invite.id,
                "can_make_main": False,
                "can_remove": can_manage,
                "can_leave": is_self,
            }
        )
    return rows
