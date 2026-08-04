"""Outbound email helpers (SMTP via Django settings)."""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def absolute_url(path: str) -> str:
    """Join PUBLIC_BASE_URL with a site-relative path for email links."""
    base = (getattr(settings, "PUBLIC_BASE_URL", None) or "").rstrip("/")
    if not path:
        return base or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    if not base:
        return path
    return f"{base}{path}"


def send_app_email(
    *,
    subject: str,
    message: str,
    recipient: str | None,
    fail_silently: bool = False,
) -> int:
    """
    Send a plain-text email from DEFAULT_FROM_EMAIL.
    Returns the number of successfully delivered messages (0 or 1).
    """
    to = (recipient or "").strip()
    if not to:
        logger.warning("Skipping email with empty recipient subject=%r", subject)
        return 0
    try:
        sent = send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [to],
            fail_silently=fail_silently,
        )
        if sent:
            logger.info("Email sent subject=%r to=%s", subject, to)
        else:
            logger.warning("Email not sent subject=%r to=%s", subject, to)
        return sent
    except Exception:
        logger.exception("Email failed subject=%r to=%s", subject, to)
        if fail_silently:
            return 0
        raise


def send_verification_code_email(*, to_email: str, code: str) -> int:
    return send_app_email(
        subject="Verify your email — Flipped Math MAP",
        message=(
            "Your email verification code is:\n\n"
            f"  {code}\n\n"
            "Enter this code on the verification page to finish. "
            "It expires in 60 minutes.\n\n"
            "If you did not request this, you can ignore this message.\n"
        ),
        recipient=to_email,
        fail_silently=True,
    )
