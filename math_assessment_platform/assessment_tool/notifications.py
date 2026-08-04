"""
User notification helpers.

Keep notification writes here so future unrelated alert types share one API
against the unmanaged ``notification`` table.
"""

from __future__ import annotations

import ast
import json
import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from django.apps import apps
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

REASON_COMPLETE_PROBLEM_RENDER_FAILURE = "complete_problem_render_failure"
REASON_COURSE_INVITATION = "course_invitation"
REASON_COURSE_INVITATION_DIFFERENT_ACCOUNT = "course_invitation_different_account"
REASON_COURSE_INVITATION_ALREADY_ENROLLED = "course_invitation_already_enrolled"
REASON_PARENT_COURSE_INVITATION = "parent_course_invitation"
REASON_PARENT_COURSE_INVITATION_DIFFERENT_ACCOUNT = (
    "parent_course_invitation_different_account"
)
REASON_PARENT_COURSE_INVITATION_ALREADY_HAS_ACCESS = (
    "parent_course_invitation_already_has_access"
)
REASON_PARENT_COURSE_INVITATION_WRONG_ACCOUNT_TYPE = (
    "parent_course_invitation_wrong_account_type"
)
REASON_ACCOUNT_DISPLAY_NAME_CHANGED = "account_display_name_changed"
REASON_ACCOUNT_EMAIL_CHANGE_STARTED = "account_email_change_started"
REASON_ACCOUNT_EMAIL_UPDATED = "account_email_updated"
REASON_ACCOUNT_PASSWORD_UPDATED = "account_password_updated"
REASON_ACCOUNT_PASSWORD_RESET_REQUESTED = "account_password_reset_requested"
REASON_ACCOUNT_PASSWORD_RESET_NULLIFIED = "account_password_reset_nullified"
REASON_TICKET_CREATED = "ticket_created"
REASON_TICKET_UPDATED = "ticket_updated"
REASON_TEACHER_COURSE_INVITATION = "teacher_course_invitation"

NOTIFICATION_TRASH_RETENTION = timedelta(days=30)
NOTIFICATIONS_PAGE_SIZE = 10


def _as_utc(value=None):
    """
    Normalize datetimes to timezone-aware UTC for storage.

    Naive values are treated as already-UTC wall times. Aware values are
    converted to UTC. ``None`` uses ``timezone.now()`` (UTC when USE_TZ).
    """
    if value is None:
        value = timezone.now()
    if not isinstance(value, datetime):
        raise TypeError(f"Expected datetime, got {type(value)!r}")
    if timezone.is_naive(value):
        value = timezone.make_aware(value, dt_timezone.utc)
    else:
        value = value.astimezone(dt_timezone.utc)
    return value


def _utc_isoformat(value):
    """UTC instant as ISO-8601 with a trailing Z (for JSON payloads / HTML datetime)."""
    if value is None:
        return None
    return _as_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


# Public alias for views / templates helpers.
utc_isoformat = _utc_isoformat


def create_notification(
    receiver,
    *,
    title,
    content,
    reason=None,
    sender=None,
    send_on=None,
    expr_date=None,
    creation_date=None,
):
    """
    Persist a row in the unmanaged ``notification`` table.

    ``receiver`` / ``sender`` are UserProfile instances (or compatible FKs).
    ``content`` may be a string or JSON-serializable object.

    ``creation_date``, ``send_on``, and ``expr_date`` are stored as UTC.
    """
    if receiver is None:
        logger.warning("create_notification skipped: no receiver")
        return None

    Notification = apps.get_model("assessment_tool", "Notification")
    if isinstance(content, (dict, list)):
        content_text = json.dumps(content, ensure_ascii=False, default=str)
    else:
        content_text = "" if content is None else str(content)

    now_utc = _as_utc(creation_date) if creation_date is not None else _as_utc()
    send_on_utc = _as_utc(send_on) if send_on is not None else now_utc
    expr_date_utc = _as_utc(expr_date) if expr_date is not None else None
    try:
        note = Notification.objects.create(
            receiver=receiver,
            sender=sender,
            title=str(title or "")[:255],
            content=content_text,
            reason=(str(reason)[:255] if reason else None),
            creation_date=now_utc,
            send_on=send_on_utc,
            expr_date=expr_date_utc,
            is_read=False,
        )
        return note
    except Exception:
        logger.exception(
            "Failed to create notification for receiver=%s title=%s",
            getattr(receiver, "pk", receiver),
            title,
        )
        return None


def _notification_model():
    return apps.get_model("assessment_tool", "Notification")


def _active_filter():
    """Notifications that are not in the trash."""
    return Q(deleted_at__isnull=True)


def _sent_filter(now=None):
    """Notifications that have already been scheduled to send."""
    now = now or timezone.now()
    return Q(send_on__isnull=True) | Q(send_on__lte=now)


def _attention_worthy_filter(now=None):
    """Unread active notifications that should currently draw attention."""
    now = now or timezone.now()
    not_expired = Q(expr_date__isnull=True) | Q(expr_date__gt=now)
    return _sent_filter(now) & not_expired & _active_filter() & Q(is_read=False)


def user_has_unread_notifications(user) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    Notification = _notification_model()
    return Notification.objects.filter(
        receiver=user,
    ).filter(_attention_worthy_filter()).exists()


def unread_notifications_for_user(user, *, limit=20, include_content=False):
    """Attention-worthy unread notifications for ``user``, newest first.

    Does not mark notifications as read.
    """
    Notification = _notification_model()
    if user is None or not getattr(user, "is_authenticated", False):
        return Notification.objects.none()
    qs = (
        Notification.objects.filter(receiver=user)
        .filter(_attention_worthy_filter())
        .order_by("-creation_date", "-pk")
    )
    if not include_content:
        qs = qs.defer("content")
    if limit is not None:
        qs = qs[:limit]
    return qs


def mark_user_notifications_read(user) -> int:
    """Mark attention-worthy unread notifications as read. Returns rows updated."""
    if user is None or not getattr(user, "is_authenticated", False):
        return 0
    Notification = _notification_model()
    return Notification.objects.filter(
        receiver=user,
    ).filter(_attention_worthy_filter()).update(is_read=True)


def mark_all_active_notifications_read(user) -> int:
    """Mark every active (non-trashed) unread notification as read. Returns count."""
    if user is None or not getattr(user, "is_authenticated", False):
        return 0
    Notification = _notification_model()
    return (
        Notification.objects.filter(receiver=user, is_read=False)
        .filter(_sent_filter())
        .filter(_active_filter())
        .update(is_read=True)
    )


def user_has_unread_list_notifications(user) -> bool:
    """True if the user has any unread notification that appears on the list page."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    Notification = _notification_model()
    return (
        Notification.objects.filter(receiver=user, is_read=False)
        .filter(_sent_filter())
        .filter(_active_filter())
        .exists()
    )


def user_has_read_list_notifications(user) -> bool:
    """True if the user has any read (active) notification that can be bulk-deleted."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    Notification = _notification_model()
    return (
        Notification.objects.filter(receiver=user, is_read=True)
        .filter(_sent_filter())
        .filter(_active_filter())
        .exists()
    )


def delete_all_read_notifications_for_user(user) -> int:
    """Move all active read notifications into trash. Returns rows updated."""
    if user is None or not getattr(user, "is_authenticated", False):
        return 0
    Notification = _notification_model()
    return (
        Notification.objects.filter(receiver=user, is_read=True)
        .filter(_sent_filter())
        .filter(_active_filter())
        .update(deleted_at=timezone.now())
    )


def serialize_notification_list_item(note):
    """Template/JSON-friendly dict for one notifications-list row."""
    return {
        "id": note.pk,
        "title": note.title,
        "reason": note.reason,
        "reason_label": reason_label_for(note.reason),
        "creation_date_utc": (
            _utc_isoformat(note.creation_date) if note.creation_date else None
        ),
        "is_read": bool(note.is_read),
    }


def notifications_page_for_user(user, *, offset=0, limit=NOTIFICATIONS_PAGE_SIZE):
    """
    Return (rows, total_count, has_more) for the active notifications list.

    ``rows`` are serialized list items; ``offset``/``limit`` slice newest-first.
    """
    qs = notifications_for_user(user, include_content=False)
    total_count = qs.count()
    offset = max(0, int(offset or 0))
    limit = max(1, int(limit or NOTIFICATIONS_PAGE_SIZE))
    page = list(qs[offset : offset + limit])
    rows = [serialize_notification_list_item(note) for note in page]
    has_more = (offset + len(rows)) < total_count
    return rows, total_count, has_more


def notifications_for_user(user, *, include_content=False):
    """Active (non-trashed) historic notifications for the user, newest first.

    By default defers ``content`` so the list page does not load large payloads.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        Notification = _notification_model()
        return Notification.objects.none()
    Notification = _notification_model()
    qs = (
        Notification.objects.filter(receiver=user)
        .filter(_sent_filter())
        .filter(_active_filter())
        .order_by("-creation_date", "-pk")
    )
    if not include_content:
        qs = qs.defer("content")
    return qs


def trashed_notifications_for_user(user, *, include_content=False):
    """Trashed notifications for ``user``, most recently deleted first."""
    if user is None or not getattr(user, "is_authenticated", False):
        Notification = _notification_model()
        return Notification.objects.none()
    Notification = _notification_model()
    qs = (
        Notification.objects.filter(receiver=user)
        .filter(deleted_at__isnull=False)
        .order_by("-deleted_at", "-pk")
    )
    if not include_content:
        qs = qs.defer("content")
    return qs


def user_has_trashed_notifications(user) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    Notification = _notification_model()
    return Notification.objects.filter(
        receiver=user,
        deleted_at__isnull=False,
    ).exists()


def get_notification_for_user(user, notification_id, *, include_trashed=False):
    """Return one sent notification belonging to ``user``, or None.

    By default excludes trashed rows. Trashed notifications must be restored
    before they can be opened/read.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    Notification = _notification_model()
    qs = Notification.objects.filter(receiver=user, pk=notification_id).filter(
        _sent_filter()
    )
    if not include_trashed:
        qs = qs.filter(_active_filter())
    return qs.first()


def mark_notification_read(user, notification_id) -> bool:
    """Mark one active notification as read for ``user``. Returns True if updated."""
    note = get_notification_for_user(user, notification_id, include_trashed=False)
    if note is None or note.is_read:
        return False
    note.is_read = True
    note.save(update_fields=["is_read"])
    return True


def delete_notification_for_user(user, notification_id) -> bool:
    """Move one active notification into trash. Returns True if updated."""
    note = get_notification_for_user(user, notification_id, include_trashed=False)
    if note is None:
        return False
    note.deleted_at = timezone.now()
    note.save(update_fields=["deleted_at"])
    return True


def restore_notification_for_user(user, notification_id) -> bool:
    """Restore one trashed notification to the active list. Returns True if updated."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    Notification = _notification_model()
    note = (
        Notification.objects.filter(
            receiver=user,
            pk=notification_id,
            deleted_at__isnull=False,
        )
        .filter(_sent_filter())
        .first()
    )
    if note is None:
        return False
    note.deleted_at = None
    note.save(update_fields=["deleted_at"])
    return True


def empty_notification_trash_for_user(user) -> int:
    """Permanently delete all trashed notifications for ``user``. Returns count."""
    if user is None or not getattr(user, "is_authenticated", False):
        return 0
    Notification = _notification_model()
    deleted, _ = Notification.objects.filter(
        receiver=user,
        deleted_at__isnull=False,
    ).delete()
    return deleted


def purge_expired_trashed_notifications(*, older_than=None) -> int:
    """
    Permanently delete trashed notifications older than the retention window
    (default 30 days) for all users. Returns number of rows removed.

    Intended to be invoked only by the scheduled management command
    ``purge_trashed_notifications`` (e.g. daily cron), not from request handlers.
    """
    cutoff = timezone.now() - (older_than or NOTIFICATION_TRASH_RETENTION)
    Notification = _notification_model()
    deleted, _ = Notification.objects.filter(
        deleted_at__isnull=False,
        deleted_at__lte=cutoff,
    ).delete()
    return deleted


def parse_notification_content(content):
    """Return (parsed_structure_or_None, display_text).

    Accepts:
    - already-decoded ``dict`` / ``list`` (common when the DB column is json/jsonb)
    - JSON text
    - Python-literal text (legacy ``str(dict)`` rows)
    """
    if content is None:
        return None, ""

    if isinstance(content, (dict, list)):
        return content, json.dumps(content, indent=2, ensure_ascii=False, default=str)

    text = str(content).strip()
    if not text:
        return None, ""

    try:
        parsed = json.loads(text)
        if isinstance(parsed, (dict, list)):
            return parsed, json.dumps(parsed, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    # Legacy / driver edge case: content stored or stringified as a Python literal.
    if text[:1] in "{[":
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, (dict, list)):
                return parsed, json.dumps(
                    parsed, indent=2, ensure_ascii=False, default=str
                )
        except (SyntaxError, ValueError, MemoryError):
            pass

    return None, text


def _parse_iso_datetime(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            return timezone.make_aware(value, dt_timezone.utc)
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, dt_timezone.utc)
    return parsed


def _clean_error_text(text):
    cleaned = str(text or "").strip()
    for prefix in ("⚠️ Error: ", "⚠️ ", "Error: "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    return cleaned


def _humanize_reason(reason):
    labels = {
        REASON_COMPLETE_PROBLEM_RENDER_FAILURE: "Problem render failure",
        REASON_COURSE_INVITATION: "Course invitation",
        REASON_COURSE_INVITATION_DIFFERENT_ACCOUNT: "Invitation accepted with different account",
        REASON_COURSE_INVITATION_ALREADY_ENROLLED: "Invite used by already-enrolled student",
        REASON_PARENT_COURSE_INVITATION: "Parent grade access invitation",
        REASON_PARENT_COURSE_INVITATION_DIFFERENT_ACCOUNT: (
            "Parent invitation accepted with different account"
        ),
        REASON_PARENT_COURSE_INVITATION_ALREADY_HAS_ACCESS: (
            "Parent invite used by parent who already has access"
        ),
        REASON_PARENT_COURSE_INVITATION_WRONG_ACCOUNT_TYPE: (
            "Non-Parent account used a parent invitation"
        ),
        REASON_ACCOUNT_DISPLAY_NAME_CHANGED: "Display name updated",
        REASON_ACCOUNT_EMAIL_CHANGE_STARTED: "Email change started",
        REASON_ACCOUNT_EMAIL_UPDATED: "Email address updated",
        REASON_ACCOUNT_PASSWORD_UPDATED: "Password updated",
        REASON_ACCOUNT_PASSWORD_RESET_REQUESTED: "Password reset requested",
        REASON_ACCOUNT_PASSWORD_RESET_NULLIFIED: "Password reset cancelled",
        REASON_TICKET_CREATED: "Support ticket created",
        REASON_TICKET_UPDATED: "Support ticket updated",
        REASON_TEACHER_COURSE_INVITATION: "Co-teacher course invitation",
    }
    if not reason:
        return None
    return labels.get(reason) or str(reason).replace("_", " ").capitalize()


def _format_display_value(value):
    """Turn nested payload values into short reader-friendly text."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _clean_error_text(value) or "—"
    if isinstance(value, dict):
        if not value:
            return "—"
        parts = []
        for key, nested in value.items():
            parts.append(f"{key}: {_format_display_value(nested)}")
        return "; ".join(parts)
    if isinstance(value, (list, tuple)):
        if not value:
            return "—"
        return ", ".join(_format_display_value(item) for item in value)
    return str(value)


def _kv_rows(mapping):
    if not isinstance(mapping, dict) or not mapping:
        return []
    rows = []
    for key, value in mapping.items():
        rows.append({"key": str(key), "value": _format_display_value(value)})
    return rows


def _parse_failed_token_item(item):
    if isinstance(item, dict):
        token = str(
            item.get("sequence_token")
            or item.get("token")
            or item.get("name")
            or item.get("id")
            or ""
        )
        archetype = str(item.get("archetype") or item.get("token") or "")
        raw_error = _clean_error_text(
            item.get("reason") or item.get("error") or item.get("message") or item
        )
    else:
        token = ""
        archetype = ""
        raw_error = _clean_error_text(item)

    issue = ""
    message = raw_error
    # Common shape: "randInt exclusive_bounds: Structural Error: ..."
    if ": " in raw_error:
        head, tail = raw_error.split(": ", 1)
        if " " in head and not head.lower().startswith("structural"):
            # e.g. "randInt exclusive_bounds"
            parts = head.split(" ", 1)
            if len(parts) == 2 and not archetype:
                archetype = parts[0]
            issue = parts[-1] if len(parts) == 2 else head
            message = tail
            if message.lower().startswith("structural error:"):
                message = message.split(":", 1)[1].strip()
        elif head.lower() == "structural error":
            message = tail

    return {
        "token": token,
        "archetype": archetype,
        "issue": issue.replace("_", " ") if issue else "",
        "error": message,
        "raw_error": raw_error,
    }


def _failed_items_from_summary(summary):
    failed_tokens = (summary or {}).get("failed_tokens") or []
    if isinstance(failed_tokens, dict):
        return [
            _parse_failed_token_item({"sequence_token": k, "reason": v})
            for k, v in failed_tokens.items()
        ]
    if isinstance(failed_tokens, list):
        return [_parse_failed_token_item(item) for item in failed_tokens]
    if failed_tokens:
        return [_parse_failed_token_item(failed_tokens)]
    return []


def _location_path(hierarchy):
    hierarchy = hierarchy or {}
    parts = []
    for key, label in (
        ("assessment_name", "Assessment"),
        ("section_name", "Section"),
        ("problem_set_name", "Problem set"),
        ("problem_name", "Problem"),
    ):
        name = hierarchy.get(key)
        if name:
            parts.append(str(name))
    return " / ".join(parts) if parts else None


def _is_render_failure_payload(reason, parsed):
    if reason == REASON_COMPLETE_PROBLEM_RENDER_FAILURE:
        return isinstance(parsed, dict)
    return isinstance(parsed, dict) and (
        "attempt_summaries" in parsed or "failing_random_values" in parsed
    )


def build_notification_detail(note):
    """
    Build template-friendly detail fields for a notification row.

    Structured JSON stays in the DB; this turns it into readable sections.
    """
    parsed, display_text = parse_notification_content(getattr(note, "content", None))
    reason = note.reason
    base = {
        "id": note.pk,
        "title": note.title,
        "reason": reason,
        "reason_label": _humanize_reason(reason),
        "creation_date": note.creation_date,
        "creation_date_utc": (
            _utc_isoformat(note.creation_date) if note.creation_date else None
        ),
        "send_on": note.send_on,
        "expr_date": note.expr_date,
        "is_read": note.is_read,
        "is_trashed": getattr(note, "deleted_at", None) is not None,
        "deleted_at": getattr(note, "deleted_at", None),
        "deleted_at_utc": (
            _utc_isoformat(note.deleted_at)
            if getattr(note, "deleted_at", None)
            else None
        ),
        "detail_kind": "generic",
        "content_display": display_text,
        "parsed": parsed,
        "generic_sections": [],
    }

    if _is_render_failure_payload(reason, parsed):
        hierarchy = parsed.get("hierarchy") or {}
        attempts = parsed.get("attempt_summaries") or []
        attempt_rows = []
        unique_errors = []
        seen_errors = set()
        for summary in attempts:
            if not isinstance(summary, dict):
                continue
            failed_items = _failed_items_from_summary(summary)
            for item in failed_items:
                key = (item.get("token") or "", item.get("raw_error") or item.get("error") or "")
                if key not in seen_errors and (key[0] or key[1]):
                    seen_errors.add(key)
                    unique_errors.append(item)

            attempt_rows.append(
                {
                    "attempt": summary.get("attempt"),
                    "ok": bool(summary.get("ok")),
                    "failed_items": failed_items,
                    "random_value_rows": _kv_rows(summary.get("random_values") or {}),
                    "card_input_rows": _kv_rows(summary.get("card_inputs") or {}),
                }
            )

        recovered = bool(parsed.get("provided_successfully_after_retries"))
        base.update(
            {
                "detail_kind": REASON_COMPLETE_PROBLEM_RENDER_FAILURE,
                "note_text": parsed.get("note") or "",
                "error_time": _parse_iso_datetime(parsed.get("error_time")),
                "error_time_utc": _utc_isoformat(
                    _parse_iso_datetime(parsed.get("error_time"))
                ),
                "actor_username": parsed.get("actor_username"),
                "provided_successfully_after_retries": recovered,
                "succeeded_on_attempt": parsed.get("succeeded_on_attempt"),
                "total_attempts": parsed.get("total_attempts") or len(attempt_rows),
                "outcome_text": (
                    f"A practice instance was still produced on attempt "
                    f"{parsed.get('succeeded_on_attempt')}, but the problem was "
                    f"marked draft because earlier attempts failed."
                    if recovered
                    else (
                        "No valid practice instance could be produced. The problem "
                        "was marked draft so students are not served a broken item."
                    )
                ),
                "hierarchy": hierarchy,
                "location_path": _location_path(hierarchy),
                "card_input_rows": _kv_rows(parsed.get("card_inputs") or {}),
                "failing_random_rows": _kv_rows(
                    parsed.get("failing_random_values") or {}
                ),
                "unique_errors": unique_errors,
                "attempt_rows": attempt_rows,
            }
        )
        return base

    if reason == REASON_COURSE_INVITATION and isinstance(parsed, dict):
        invite_path = parsed.get("invite_path") or ""
        if not invite_path and parsed.get("invite_code"):
            from django.urls import reverse

            invite_path = reverse(
                "course_invite_redeem",
                kwargs={"code": parsed.get("invite_code")},
            )
        base.update(
            {
                "detail_kind": REASON_COURSE_INVITATION,
                "course_name": parsed.get("course_name") or "",
                "invite_path": invite_path,
                "invite_message": parsed.get("message")
                or (
                    "You have been invited to a course. Open the invitation link "
                    "and accept to activate your access."
                ),
            }
        )
        return base

    if reason == REASON_COURSE_INVITATION_ALREADY_ENROLLED and isinstance(parsed, dict):
        from django.urls import reverse

        management_path = parsed.get("course_management_path") or ""
        if not management_path and parsed.get("course_id") and parsed.get("invite_id"):
            management_path = (
                reverse("course_management", kwargs={"course_id": parsed["course_id"]})
                + f"?invite={parsed['invite_id']}"
            )
        elif not management_path and parsed.get("course_id"):
            management_path = reverse(
                "course_management", kwargs={"course_id": parsed["course_id"]}
            )
        base.update(
            {
                "detail_kind": REASON_COURSE_INVITATION_ALREADY_ENROLLED,
                "course_name": parsed.get("course_name") or "",
                "invite_message": parsed.get("message") or "",
                "invitation_sent_to_email": parsed.get("invitation_sent_to_email"),
                "invitation_sent_to_username": parsed.get("invitation_sent_to_username"),
                "accessor_username": parsed.get("accessor_username"),
                "accessor_display_name": parsed.get("accessor_display_name"),
                "accessor_email": parsed.get("accessor_email"),
                "course_management_path": management_path,
            }
        )
        return base

    if reason == REASON_COURSE_INVITATION_DIFFERENT_ACCOUNT and isinstance(parsed, dict):
        from django.urls import reverse

        invite_path = parsed.get("invite_path") or ""
        if not invite_path and parsed.get("invite_code"):
            invite_path = reverse(
                "course_invite_redeem",
                kwargs={"code": parsed.get("invite_code")},
            )
        base.update(
            {
                "detail_kind": REASON_COURSE_INVITATION_DIFFERENT_ACCOUNT,
                "course_name": parsed.get("course_name") or "",
                "invite_message": parsed.get("message") or "",
                "invite_code": parsed.get("invite_code") or "",
                "invite_path": invite_path,
                "invitation_sent_to_email": parsed.get("invitation_sent_to_email"),
                "invitation_sent_to_username": parsed.get("invitation_sent_to_username"),
                "accepted_username": parsed.get("accepted_username"),
                "accepted_display_name": parsed.get("accepted_display_name"),
                "accepted_email": parsed.get("accepted_email"),
            }
        )
        return base

    if reason == REASON_PARENT_COURSE_INVITATION and isinstance(parsed, dict):
        from django.urls import reverse

        invite_path = parsed.get("invite_path") or ""
        if not invite_path and parsed.get("invite_code"):
            invite_path = reverse(
                "parent_invite_redeem",
                kwargs={"code": parsed.get("invite_code")},
            )
        base.update(
            {
                "detail_kind": REASON_PARENT_COURSE_INVITATION,
                "course_name": parsed.get("course_name") or "",
                "student_name": parsed.get("student_name") or "",
                "student_username": parsed.get("student_username") or "",
                "invite_path": invite_path,
                "invite_message": parsed.get("message")
                or (
                    "You have been invited to view a student's grades. "
                    "Open the invitation link and accept to activate access."
                ),
            }
        )
        return base

    if reason == REASON_PARENT_COURSE_INVITATION_ALREADY_HAS_ACCESS and isinstance(
        parsed, dict
    ):
        from django.urls import reverse

        management_path = parsed.get("course_management_path") or ""
        if not management_path and parsed.get("course_id") and parsed.get("invite_id"):
            management_path = (
                reverse("course_management", kwargs={"course_id": parsed["course_id"]})
                + f"?parent_invite={parsed['invite_id']}"
            )
        elif not management_path and parsed.get("course_id"):
            management_path = reverse(
                "course_management", kwargs={"course_id": parsed["course_id"]}
            )
        base.update(
            {
                "detail_kind": REASON_PARENT_COURSE_INVITATION_ALREADY_HAS_ACCESS,
                "course_name": parsed.get("course_name") or "",
                "student_name": parsed.get("student_name") or "",
                "invite_message": parsed.get("message") or "",
                "invitation_sent_to_email": parsed.get("invitation_sent_to_email"),
                "accessor_username": parsed.get("accessor_username"),
                "accessor_display_name": parsed.get("accessor_display_name"),
                "accessor_email": parsed.get("accessor_email"),
                "course_management_path": management_path,
            }
        )
        return base

    if reason == REASON_PARENT_COURSE_INVITATION_WRONG_ACCOUNT_TYPE and isinstance(
        parsed, dict
    ):
        from django.urls import reverse

        management_path = parsed.get("course_management_path") or ""
        if not management_path and parsed.get("course_id") and parsed.get("invite_id"):
            management_path = (
                reverse("course_management", kwargs={"course_id": parsed["course_id"]})
                + f"?parent_invite={parsed['invite_id']}"
            )
        elif not management_path and parsed.get("course_id"):
            management_path = reverse(
                "course_management", kwargs={"course_id": parsed["course_id"]}
            )
        base.update(
            {
                "detail_kind": REASON_PARENT_COURSE_INVITATION_WRONG_ACCOUNT_TYPE,
                "course_name": parsed.get("course_name") or "",
                "student_name": parsed.get("student_name") or "",
                "invite_message": parsed.get("message") or "",
                "invitation_sent_to_email": parsed.get("invitation_sent_to_email"),
                "accessor_username": parsed.get("accessor_username"),
                "accessor_display_name": parsed.get("accessor_display_name"),
                "accessor_email": parsed.get("accessor_email"),
                "accessor_user_type": parsed.get("accessor_user_type"),
                "course_management_path": management_path,
            }
        )
        return base

    if reason == REASON_PARENT_COURSE_INVITATION_DIFFERENT_ACCOUNT and isinstance(
        parsed, dict
    ):
        from django.urls import reverse

        invite_path = parsed.get("invite_path") or ""
        if not invite_path and parsed.get("invite_code"):
            invite_path = reverse(
                "parent_invite_redeem",
                kwargs={"code": parsed.get("invite_code")},
            )
        base.update(
            {
                "detail_kind": REASON_PARENT_COURSE_INVITATION_DIFFERENT_ACCOUNT,
                "course_name": parsed.get("course_name") or "",
                "student_name": parsed.get("student_name") or "",
                "invite_message": parsed.get("message") or "",
                "invite_code": parsed.get("invite_code") or "",
                "invite_path": invite_path,
                "invitation_sent_to_email": parsed.get("invitation_sent_to_email"),
                "accepted_username": parsed.get("accepted_username"),
                "accepted_display_name": parsed.get("accepted_display_name"),
                "accepted_email": parsed.get("accepted_email"),
            }
        )
        return base

    if reason == REASON_ACCOUNT_DISPLAY_NAME_CHANGED and isinstance(parsed, dict):
        base.update(
            {
                "detail_kind": REASON_ACCOUNT_DISPLAY_NAME_CHANGED,
                "invite_message": parsed.get("message") or "",
                "previous_display_name": parsed.get("previous_display_name"),
                "new_display_name": parsed.get("new_display_name"),
            }
        )
        return base

    if reason == REASON_ACCOUNT_EMAIL_CHANGE_STARTED and isinstance(parsed, dict):
        from django.urls import reverse

        base.update(
            {
                "detail_kind": REASON_ACCOUNT_EMAIL_CHANGE_STARTED,
                "invite_message": parsed.get("message") or "",
                "previous_email": parsed.get("previous_email"),
                "pending_email": parsed.get("pending_email"),
                "account_settings_path": reverse("account_settings"),
                "verify_email_path": reverse("verify_email"),
            }
        )
        return base

    if reason == REASON_ACCOUNT_EMAIL_UPDATED and isinstance(parsed, dict):
        base.update(
            {
                "detail_kind": REASON_ACCOUNT_EMAIL_UPDATED,
                "invite_message": parsed.get("message") or "",
                "previous_email": parsed.get("previous_email"),
                "new_email": parsed.get("new_email"),
            }
        )
        return base

    if reason == REASON_ACCOUNT_PASSWORD_UPDATED and isinstance(parsed, dict):
        base.update(
            {
                "detail_kind": REASON_ACCOUNT_PASSWORD_UPDATED,
                "invite_message": parsed.get("message")
                or "Your account password was updated.",
            }
        )
        return base

    if reason == REASON_ACCOUNT_PASSWORD_RESET_REQUESTED and isinstance(parsed, dict):
        base.update(
            {
                "detail_kind": REASON_ACCOUNT_PASSWORD_RESET_REQUESTED,
                "invite_message": parsed.get("message") or "",
                "expires_at": parsed.get("expires_at") or "",
            }
        )
        return base

    if reason == REASON_ACCOUNT_PASSWORD_RESET_NULLIFIED and isinstance(parsed, dict):
        base.update(
            {
                "detail_kind": REASON_ACCOUNT_PASSWORD_RESET_NULLIFIED,
                "invite_message": parsed.get("message")
                or "Your pending password reset was cancelled.",
            }
        )
        return base

    if reason in (REASON_TICKET_CREATED, REASON_TICKET_UPDATED) and isinstance(
        parsed, dict
    ):
        base.update(
            {
                "detail_kind": reason,
                "invite_message": parsed.get("message") or "",
                "ticket_title": parsed.get("ticket_title") or "",
                "ticket_path": parsed.get("ticket_path") or "",
            }
        )
        return base

    if reason == REASON_TEACHER_COURSE_INVITATION and isinstance(parsed, dict):
        base.update(
            {
                "detail_kind": REASON_TEACHER_COURSE_INVITATION,
                "invite_message": parsed.get("message") or "",
                "course_name": parsed.get("course_name") or "",
                "inviter_name": parsed.get("inviter_name") or "",
                "invite_path": parsed.get("invite_path") or "",
                "invite_code": parsed.get("invite_code") or "",
            }
        )
        return base

    # Generic structured JSON: present top-level fields as labeled sections.
    if isinstance(parsed, dict) and parsed:
        sections = []
        for key, value in parsed.items():
            label = str(key).replace("_", " ").capitalize()
            if isinstance(value, dict):
                sections.append(
                    {
                        "label": label,
                        "kind": "kv",
                        "rows": _kv_rows(value),
                        "text": None,
                    }
                )
            elif isinstance(value, list):
                sections.append(
                    {
                        "label": label,
                        "kind": "list",
                        "rows": [
                            {"value": _format_display_value(item)} for item in value
                        ],
                        "text": None,
                    }
                )
            else:
                sections.append(
                    {
                        "label": label,
                        "kind": "text",
                        "rows": [],
                        "text": _format_display_value(value),
                    }
                )
        base["detail_kind"] = "structured"
        base["generic_sections"] = sections
    return base


def reason_label_for(reason):
    return _humanize_reason(reason)


def _problem_hierarchy_context(problem):
    """Collect assessment / section / set / problem names and ids when present."""
    ctx = {
        "problem_id": getattr(problem, "id", None),
        "problem_name": getattr(problem, "title", None),
        "assessment_id": None,
        "assessment_name": None,
        "section_id": None,
        "section_name": None,
        "problem_set_id": None,
        "problem_set_name": None,
    }
    aqg = getattr(problem, "aqg", None)
    if aqg is not None:
        ctx["section_id"] = getattr(aqg, "id", None)
        ctx["section_name"] = getattr(aqg, "name", None)
        assessment = getattr(aqg, "assessment", None)
        if assessment is not None:
            ctx["assessment_id"] = getattr(assessment, "id", None)
            ctx["assessment_name"] = getattr(assessment, "name", None)
    cqd = getattr(problem, "cqd", None)
    if cqd is not None:
        ctx["problem_set_id"] = getattr(cqd, "id", None)
        try:
            ctx["problem_set_name"] = cqd.get_display_name()
        except Exception:
            ctx["problem_set_name"] = getattr(cqd, "name", None)
    return ctx


def notify_owner_complete_problem_render_failure(
    problem,
    *,
    actor_user,
    attempt_summaries,
    demoted_at=None,
    succeeded_on_attempt=None,
):
    """
    Notify the problem owner that a complete problem failed to render and was
    forcibly marked draft.

    ``attempt_summaries``: list of dicts from practice-instance builds, each with
    at least ``attempt``, ``ok``, ``random_values``, ``card_inputs``, ``failed_tokens``.
    ``succeeded_on_attempt``: 1-based attempt number that produced a valid instance,
    or None if all attempts failed.
    """
    branch = getattr(problem, "branch_location", None)
    owner = getattr(branch, "owner", None) if branch is not None else None
    if owner is None:
        logger.warning(
            "No owner for problem id=%s; skip render-failure notification",
            getattr(problem, "id", None),
        )
        return None

    demoted_at = _as_utc(demoted_at) if demoted_at is not None else _as_utc()

    actor_username = getattr(actor_user, "username", None) or str(
        getattr(actor_user, "pk", "") or "unknown"
    )
    provided_successfully = succeeded_on_attempt is not None
    hierarchy = _problem_hierarchy_context(problem)

    # Prefer the first failing attempt's random snapshot for the top-level field
    failing_random = {}
    card_inputs = {}
    for summary in attempt_summaries or []:
        if not summary.get("ok"):
            failing_random = summary.get("random_values") or failing_random
            card_inputs = summary.get("card_inputs") or card_inputs
            break
    if not card_inputs and attempt_summaries:
        card_inputs = (attempt_summaries[0] or {}).get("card_inputs") or {}

    payload = {
        "error_time": _utc_isoformat(demoted_at),
        "actor_username": actor_username,
        "provided_successfully_after_retries": provided_successfully,
        "succeeded_on_attempt": succeeded_on_attempt,
        "total_attempts": len(attempt_summaries or []),
        "hierarchy": hierarchy,
        "card_inputs": card_inputs,
        "failing_random_values": failing_random,
        "attempt_summaries": attempt_summaries or [],
        "note": (
            "A problem marked complete failed to produce valid random entity values "
            "during practice/test rendering and was forcibly set to draft."
        ),
    }

    problem_label = hierarchy.get("problem_name") or f"#{hierarchy.get('problem_id')}"
    title = f"Problem marked draft after render failure: {problem_label}"
    # Keep title within CharField(255)
    title = title[:255]

    return create_notification(
        owner,
        title=title,
        content=payload,
        reason=REASON_COMPLETE_PROBLEM_RENDER_FAILURE,
        sender=actor_user if getattr(actor_user, "pk", None) else None,
        creation_date=demoted_at,
        send_on=demoted_at,
    )
