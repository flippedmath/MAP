"""Account Settings helpers for profile display-name and email changes."""

from __future__ import annotations

import logging
import re

from django.contrib.auth.base_user import BaseUserManager
from django.db import transaction

from .models import EmailAuthentication, UserProfile

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

GENDER_LABELS = {
    "m": "Male",
    "f": "Female",
    "o": "Other",
}


def gender_label(raw) -> str:
    key = (raw or "").strip().lower()[:1]
    return GENDER_LABELS.get(key, (raw or "—").strip() or "—")


def normalize_display_name(raw: str | None) -> str | None:
    """Whitespace-normalize; empty clears the display name."""
    cleaned = " ".join((raw or "").split())
    return cleaned or None


def normalize_email(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ValueError("Enter a new email address.")
    if not EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address.")
    return BaseUserManager.normalize_email(value).lower()


def pending_email_for_user(user):
    """Return pending EmailAuthentication row for an already-active account, if any."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "unactivated_account", False):
        # New-account activation uses the same table; treat as signup, not settings change.
        return None
    return EmailAuthentication.objects.filter(u_id=user).first()


@transaction.atomic
def update_display_name(user, raw_display_name: str | None) -> tuple[bool, str | None]:
    """
    Update display name. Returns (changed, new_value).
    Sends a notification when the value actually changes.
    """
    new_value = normalize_display_name(raw_display_name)
    old_value = (getattr(user, "user_display_name", None) or None)
    if old_value == new_value or ((old_value or "") == (new_value or "")):
        return False, new_value

    user.user_display_name = new_value
    user.save(update_fields=["user_display_name"])

    try:
        from .notifications import create_notification, REASON_ACCOUNT_DISPLAY_NAME_CHANGED

        create_notification(
            user,
            title="Display name updated",
            content={
                "previous_display_name": old_value,
                "new_display_name": new_value,
                "message": (
                    f"Your display name was changed from "
                    f"“{old_value or '(none)'}” to “{new_value or '(none)'}”."
                ),
            },
            reason=REASON_ACCOUNT_DISPLAY_NAME_CHANGED,
            sender=user,
        )
    except Exception:
        logger.exception(
            "Failed to notify display-name change for user_id=%s",
            getattr(user, "user_id", None),
        )

    return True, new_value


@transaction.atomic
def start_email_change(*, user, new_email_raw: str, password: str) -> EmailAuthentication:
    """
    Password-gate and start pending email verification for an activated account.
    Does not change user.user_email until the code is verified.
    """
    if getattr(user, "unactivated_account", False):
        raise ValueError(
            "Finish activating your account before starting an email change from settings."
        )
    if not user.check_password(password or ""):
        raise ValueError("Incorrect password. Email change was not started.")

    new_email = normalize_email(new_email_raw)
    current = (user.user_email or "").strip().lower()
    if new_email == current:
        raise ValueError("That is already your current email address.")

    if UserProfile.objects.filter(user_email__iexact=new_email).exclude(
        user_id=user.user_id
    ).exists():
        raise ValueError("That email is already associated with another account.")
    if EmailAuthentication.objects.filter(temp_email__iexact=new_email).exclude(
        u_id=user.user_id
    ).exists():
        raise ValueError("That email is already pending verification for another account.")

    previous_email = user.user_email
    auth = EmailAuthentication.generate_auth_record(user, new_email)

    try:
        from .notifications import (
            create_notification,
            REASON_ACCOUNT_EMAIL_CHANGE_STARTED,
        )

        create_notification(
            user,
            title="Email change started",
            content={
                "previous_email": previous_email,
                "pending_email": new_email,
                "message": (
                    f"A process to change your email from {previous_email} to {new_email} "
                    "has started. Enter the verification code to finish, or cancel the "
                    "change from Account Settings to keep your current email."
                ),
            },
            reason=REASON_ACCOUNT_EMAIL_CHANGE_STARTED,
            sender=user,
        )
    except Exception:
        logger.exception(
            "Failed to notify email-change start for user_id=%s",
            getattr(user, "user_id", None),
        )

    from .mail import send_verification_code_email

    send_verification_code_email(to_email=auth.temp_email, code=auth.code)

    return auth


@transaction.atomic
def cancel_pending_email_change(user) -> bool:
    """Delete pending email_authentication rows for an activated account. Returns True if removed."""
    if user is None or getattr(user, "unactivated_account", False):
        return False
    deleted, _ = EmailAuthentication.objects.filter(u_id=user).delete()
    return deleted > 0


def normalize_organization(raw: str | None) -> str | None:
    cleaned = " ".join((raw or "").split())
    return cleaned or None


@transaction.atomic
def update_organization(user, raw_organization: str | None) -> tuple[bool, str | None]:
    """Update organization for Teacher/IT. Returns (changed, new_value)."""
    if getattr(user, "user_type", None) not in ("Teacher", "IT_Support"):
        raise ValueError("Only Teacher and IT Support accounts can edit organization.")
    new_value = normalize_organization(raw_organization)
    old_value = (getattr(user, "organization", None) or None)
    if (old_value or "") == (new_value or ""):
        return False, new_value
    user.organization = new_value
    user.save(update_fields=["organization"])
    return True, new_value


@transaction.atomic
def reset_password(
    *,
    user,
    new_password: str,
    confirm_password: str,
    current_password: str,
) -> None:
    """
    Verify current password, then set a new password after match +
    Django AUTH_PASSWORD_VALIDATORS checks. Notifies the user on success.
    """
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError

    if not user.check_password(current_password or ""):
        raise ValueError("Incorrect password. Password was not updated.")

    password = new_password or ""
    confirm = confirm_password or ""
    if not password:
        raise ValueError("Enter a new password.")
    if password != confirm:
        raise ValueError("Passwords do not match.")
    if user.check_password(password):
        raise ValueError("New password must be different from your current password.")
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise ValueError(" ".join(exc.messages)) from exc
    user.set_password(password)
    user.save(update_fields=["password"])

    try:
        from .password_reset import delete_pending_resets_for_user

        delete_pending_resets_for_user(user)
    except Exception:
        logger.exception(
            "Failed to clear pending password resets after settings password update "
            "for user_id=%s",
            getattr(user, "user_id", None),
        )

    try:
        from .notifications import (
            create_notification,
            REASON_ACCOUNT_PASSWORD_UPDATED,
        )

        create_notification(
            user,
            title="Password updated",
            content={
                "message": (
                    "Your account password was updated. If you did not make this change, "
                    "contact IT Support right away."
                ),
            },
            reason=REASON_ACCOUNT_PASSWORD_UPDATED,
            sender=user,
        )
    except Exception:
        logger.exception(
            "Failed to notify password update for user_id=%s",
            getattr(user, "user_id", None),
        )


def notify_email_updated(*, user, previous_email: str, new_email: str) -> None:
    try:
        from .notifications import (
            create_notification,
            REASON_ACCOUNT_EMAIL_UPDATED,
        )

        create_notification(
            user,
            title="Email address updated",
            content={
                "previous_email": previous_email,
                "new_email": new_email,
                "message": (
                    f"Your account email was updated from {previous_email} to {new_email}."
                ),
            },
            reason=REASON_ACCOUNT_EMAIL_UPDATED,
            sender=user,
        )
    except Exception:
        logger.exception(
            "Failed to notify email update for user_id=%s",
            getattr(user, "user_id", None),
        )
