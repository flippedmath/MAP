"""Forgot-password request and reset helpers."""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .models import PasswordResetRequest, UserProfile

logger = logging.getLogger(__name__)

RESET_TTL = timedelta(minutes=15)


def find_user_by_username_or_email(identifier: str):
    """Return a UserProfile matching username or email (case-insensitive), or None."""
    value = (identifier or "").strip()
    if not value:
        return None
    try:
        return UserProfile.objects.get(
            Q(username__iexact=value) | Q(user_email__iexact=value)
        )
    except UserProfile.DoesNotExist:
        return None
    except UserProfile.MultipleObjectsReturned:
        # Prefer exact username match if both collide somehow.
        return (
            UserProfile.objects.filter(username__iexact=value).first()
            or UserProfile.objects.filter(user_email__iexact=value).first()
        )


def get_reset_by_code(code: str):
    if not code:
        return None
    return (
        PasswordResetRequest.objects.select_related("u")
        .filter(code=code)
        .first()
    )


def reset_is_expired(row: PasswordResetRequest) -> bool:
    if row is None or row.timeout is None:
        return True
    timeout_time = row.timeout
    if timezone.is_naive(timeout_time):
        timeout_time = timezone.make_aware(timeout_time)
    return timezone.now() >= timeout_time


def delete_pending_resets_for_user(user) -> int:
    """Delete all pending password-reset rows for a user. Returns count deleted."""
    if user is None:
        return 0
    user_id = getattr(user, "user_id", None) or getattr(user, "pk", None)
    if user_id is None:
        return 0
    deleted, _ = PasswordResetRequest.objects.filter(u_id=user_id).delete()
    return deleted


def _send_password_reset_email(*, user, reset_row: PasswordResetRequest) -> None:
    from .mail import absolute_url, send_app_email

    reset_path = reverse("password_reset_confirm", kwargs={"code": reset_row.code})
    reset_url = absolute_url(reset_path)
    to_email = (getattr(user, "user_email", None) or "").strip()
    send_app_email(
        subject="Password reset — Flipped Math MAP",
        message=(
            "A password reset was requested for your account.\n\n"
            f"Open this link within 15 minutes to choose a new password:\n{reset_url}\n\n"
            "If you did not request this, you can ignore this message.\n"
        ),
        recipient=to_email,
        fail_silently=True,
    )


def _send_password_changed_email(*, user) -> None:
    from .mail import send_app_email

    to_email = (getattr(user, "user_email", None) or "").strip()
    send_app_email(
        subject="Password updated — Flipped Math MAP",
        message=(
            "Your account password was changed using a reset link.\n\n"
            "If you did not make this change, contact IT Support right away.\n"
        ),
        recipient=to_email,
        fail_silently=True,
    )


@transaction.atomic
def create_password_reset_request(*, identifier: str) -> PasswordResetRequest | None:
    """
    If a matching user exists, create (or replace) a 15-minute reset token,
    notify the user, and email the reset link. Returns the row, or None if no match.

    Callers should always show a generic success message to avoid account enumeration.
    """
    user = find_user_by_username_or_email(identifier)
    if user is None:
        return None

    PasswordResetRequest.objects.filter(u_id=user.user_id).delete()
    row = PasswordResetRequest.objects.create(
        u_id=user.user_id,
        code=secrets.token_urlsafe(32),
        timeout=timezone.now() + RESET_TTL,
        creation_date=timezone.now(),
        requested_identifier=(identifier or "").strip()[:255] or None,
    )

    try:
        from .notifications import (
            create_notification,
            REASON_ACCOUNT_PASSWORD_RESET_REQUESTED,
        )

        reset_path = reverse("password_reset_confirm", kwargs={"code": row.code})
        create_notification(
            user,
            title="Password reset requested",
            content={
                "reset_path": reset_path,
                "expires_at": row.timeout.isoformat() if row.timeout else None,
                "message": (
                    "A password reset was requested for your account. "
                    "Use the link sent to your email within 15 minutes to choose a new password. "
                    "If you did not request this, you can reach out IT Support for help."
                ),
            },
            reason=REASON_ACCOUNT_PASSWORD_RESET_REQUESTED,
            sender=user,
        )
    except Exception:
        logger.exception(
            "Failed to notify password-reset request for user_id=%s",
            getattr(user, "user_id", None),
        )

    _send_password_reset_email(user=user, reset_row=row)
    return row


@transaction.atomic
def nullify_password_resets_on_login(user) -> int:
    """
    If the user logs in successfully while a reset is pending, delete the row(s)
    and notify that the reset was nullified. Returns number of rows deleted.
    """
    deleted = delete_pending_resets_for_user(user)
    if deleted <= 0:
        return 0

    try:
        from .notifications import (
            create_notification,
            REASON_ACCOUNT_PASSWORD_RESET_NULLIFIED,
        )

        create_notification(
            user,
            title="Password reset cancelled",
            content={
                "message": (
                    "Your pending password reset was cancelled because you signed in "
                    "successfully without changing your password."
                ),
            },
            reason=REASON_ACCOUNT_PASSWORD_RESET_NULLIFIED,
            sender=user,
        )
    except Exception:
        logger.exception(
            "Failed to notify password-reset nullify for user_id=%s",
            getattr(user, "user_id", None),
        )
    return deleted


@transaction.atomic
def complete_password_reset(
    *,
    reset_row: PasswordResetRequest,
    new_password: str,
    confirm_password: str,
) -> UserProfile:
    """
    Validate and set a new password from a forgot-password link.
    Deletes the reset row, notifies the user, and emails a confirmation.
    """
    if reset_is_expired(reset_row):
        raise ValueError("This password reset link has expired. Request a new one.")

    user = reset_row.u
    if user is None:
        raise ValueError("This password reset link is no longer valid.")

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

    PasswordResetRequest.objects.filter(pk=reset_row.pk).delete()
    # Clear any other stray rows for this user.
    PasswordResetRequest.objects.filter(u_id=user.user_id).delete()

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
                    "Your account password was changed using a reset link. "
                    "If you did not make this change, contact IT Support right away."
                ),
                "via": "forgot_password",
            },
            reason=REASON_ACCOUNT_PASSWORD_UPDATED,
            sender=user,
        )
    except Exception:
        logger.exception(
            "Failed to notify password reset completion for user_id=%s",
            getattr(user, "user_id", None),
        )

    _send_password_changed_email(user=user)
    return user
