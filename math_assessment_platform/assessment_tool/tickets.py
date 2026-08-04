"""IT Tickets + Contact Us helpers."""

from __future__ import annotations

import logging
import re
import secrets
from html import escape as html_escape
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.html import urlize

from .models import (
    ContactUs,
    Ticket,
    TicketAdminFilterPref,
    TicketDiscussion,
    UserProfile,
)
from .notifications import create_notification

logger = logging.getLogger(__name__)

MAX_SUBJECT = 200
MAX_FIRST_NAME = 100
MAX_EMAIL = 254
MAX_BODY = 5000

CONTACT_PURPOSES = (
    ("general_question", "General question"),
    ("billing", "Billing"),
    ("bug_error", "Bug / error"),
    ("compliment", "Compliment"),
    ("suggestion", "Suggestion"),
    ("other", "Other"),
)
CONTACT_PURPOSE_VALUES = {p[0] for p in CONTACT_PURPOSES}

TICKET_STATUSES = (
    ("new", "New"),
    ("open", "Open"),
    ("awaiting_response", "Awaiting response"),
    ("on_hold", "On hold"),
    ("resolved", "Resolved"),
    ("closed", "Closed"),
    ("canceled", "Canceled"),
)
TICKET_STATUS_VALUES = {s[0] for s in TICKET_STATUSES}
ACTIVE_TICKET_STATUSES = ("new", "open", "awaiting_response", "on_hold", "resolved")
DELETABLE_TICKET_STATUSES = frozenset({"closed", "canceled"})

TICKET_PRIORITIES = (
    ("low", "Low"),
    ("normal", "Normal"),
    ("high", "High"),
    ("urgent", "Urgent"),
)
TICKET_PRIORITY_VALUES = {p[0] for p in TICKET_PRIORITIES}

def purpose_label(value: str | None) -> str:
    for key, label in CONTACT_PURPOSES:
        if key == value:
            return label
    return (value or "—").replace("_", " ").capitalize()


def status_label(value: str | None) -> str:
    for key, label in TICKET_STATUSES:
        if key == value:
            return label
    return (value or "—").replace("_", " ").capitalize()


def priority_label(value: str | None) -> str:
    for key, label in TICKET_PRIORITIES:
        if key == value:
            return label
    return (value or "—").replace("_", " ").capitalize()


def generate_access_token() -> str:
    return secrets.token_urlsafe(32)[:64]


def ticket_client_path(ticket: Ticket) -> str:
    return reverse("ticket_client", kwargs={"access_token": ticket.access_token})


def ticket_client_absolute_url(request, ticket: Ticket) -> str:
    return request.build_absolute_uri(ticket_client_path(ticket))


def validate_length(value: str, *, field: str, max_len: int) -> str:
    text = (value or "").strip()
    if len(text) > max_len:
        raise ValidationError(f"{field} must be at most {max_len} characters.")
    return text


def validate_email(value: str) -> str:
    email = validate_length(value, field="Email", max_len=MAX_EMAIL).lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise ValidationError("Enter a valid email address.")
    return email


def validate_purpose(value: str) -> str:
    purpose = (value or "").strip()
    if not purpose:
        raise ValidationError("Select a purpose.")
    if purpose not in CONTACT_PURPOSE_VALUES:
        raise ValidationError("Select a valid contact purpose.")
    return purpose


def validate_status(value: str) -> str:
    status = (value or "").strip()
    if status not in TICKET_STATUS_VALUES:
        raise ValidationError("Select a valid status.")
    return status


def validate_priority(value: str) -> str:
    priority = (value or "").strip() or "normal"
    if priority not in TICKET_PRIORITY_VALUES:
        raise ValidationError("Select a valid priority.")
    return priority


def make_comment_payload(
    body: str,
    *,
    kind: str = "user",
    meta: dict | None = None,
) -> dict:
    return {
        "format": "plain",
        "body": body or "",
        "kind": kind,
        "meta": meta or {},
    }


def comment_body_text(comment: Any) -> str:
    if isinstance(comment, dict):
        return str(comment.get("body") or "")
    if comment is None:
        return ""
    return str(comment)


def comment_html(comment: Any) -> str:
    """Escape plain body and linkify URLs / relative /qa/ paths."""
    body = comment_body_text(comment)
    if not body:
        return ""
    lines = []
    for line in body.splitlines():
        esc = html_escape(line)
        esc = urlize(esc, nofollow=True, autoescape=False)

        def repl_qa(m: re.Match) -> str:
            path = m.group(0)
            return (
                f'<a href="{html_escape(path)}" rel="nofollow">'
                f"{html_escape(path)}</a>"
            )

        esc = re.sub(r"(?<![\"\'=])(/qa/\d+/?)", repl_qa, esc)
        lines.append(esc)
    return "<br>\n".join(lines)


def format_qa_link_text(*, title: str, path: str) -> str:
    clean_title = (title or "Q&A article").strip() or "Q&A article"
    return f"Q&A: {clean_title}\n{path}"


def _actor_label(user) -> str:
    if user is None:
        return "Someone"
    return (
        getattr(user, "user_display_name", None)
        or getattr(user, "username", None)
        or "User"
    )


def _touch_ticket(ticket: Ticket, *, unread: bool | None = None) -> None:
    now = timezone.now()
    ticket.modification_date = now
    ticket.last_comment_at = now
    if unread is not None:
        ticket.admin_unread = unread
    update_fields = ["modification_date", "last_comment_at"]
    if unread is not None:
        update_fields.append("admin_unread")
    ticket.save(update_fields=update_fields)


def _add_discussion(
    ticket: Ticket,
    *,
    email: str,
    body: str,
    kind: str = "user",
    meta: dict | None = None,
    is_system: bool = False,
    author_user=None,
    set_admin_unread: bool | None = None,
) -> TicketDiscussion:
    row = TicketDiscussion.objects.create(
        commentor_email=email or "",
        ticket_reference=ticket,
        comment=make_comment_payload(body, kind=kind, meta=meta),
        creation_date=timezone.now(),
        is_system=is_system,
        author_user=author_user,
    )
    _touch_ticket(ticket, unread=set_admin_unread)
    return row


@transaction.atomic
def create_contact_us(
    *,
    subject: str,
    contact_purpose: str,
    first_name: str,
    respond_to_email: str,
    inquiry: str,
    user=None,
) -> ContactUs:
    subject = validate_length(subject, field="Subject", max_len=MAX_SUBJECT)
    if not subject:
        raise ValidationError("Subject is required.")
    purpose = validate_purpose(contact_purpose)
    first_name = validate_length(first_name, field="First name", max_len=MAX_FIRST_NAME)
    if not first_name:
        raise ValidationError("First name is required.")
    email = validate_email(respond_to_email)
    inquiry = validate_length(inquiry, field="Inquiry", max_len=MAX_BODY)
    if not inquiry:
        raise ValidationError("Inquiry is required.")

    username = None
    if user is not None and getattr(user, "is_authenticated", False):
        username = user

    return ContactUs.objects.create(
        subject=subject,
        contact_purpose=purpose,
        username=username,
        respond_to_email=email,
        first_name=first_name,
        inquiry=inquiry,
        creation_date=timezone.now(),
    )


def _send_ticket_email(*, ticket: Ticket, kind: str) -> None:
    from .mail import absolute_url, send_app_email

    path = ticket_client_path(ticket)
    url = absolute_url(path)
    if kind == "ticket_created":
        subject = f'Support ticket created: "{ticket.title}"'
        body = (
            f'Your support ticket "{ticket.title}" has been created.\n\n'
            f"View or reply here:\n{url}\n"
        )
    else:
        subject = f'Support ticket updated: "{ticket.title}"'
        body = (
            f'Your support ticket "{ticket.title}" has an update.\n\n'
            f"View it here:\n{url}\n"
        )
    send_app_email(
        subject=subject,
        message=body,
        recipient=ticket.respond_to_email,
        fail_silently=True,
    )


def notify_ticket_client(*, ticket: Ticket, kind: str = "ticket_created") -> None:
    """In-app (if linked user) + email. Sets client_notified_at."""
    from .notifications import (
        REASON_TICKET_CREATED,
        REASON_TICKET_UPDATED,
    )

    path = ticket_client_path(ticket)
    reason = REASON_TICKET_CREATED if kind == "ticket_created" else REASON_TICKET_UPDATED
    title = (
        "Support ticket created"
        if kind == "ticket_created"
        else "Support ticket updated"
    )
    message = (
        f'Your support ticket "{ticket.title}" is available.'
        if kind == "ticket_created"
        else f'Your support ticket "{ticket.title}" has an update.'
    )
    payload = {
        "message": message,
        "ticket_title": ticket.title,
        "ticket_path": path,
        "access_token": ticket.access_token,
    }
    if ticket.username_id:
        create_notification(
            ticket.username,
            title=title,
            content=payload,
            reason=reason,
        )
    _send_ticket_email(ticket=ticket, kind=kind)
    ticket.client_notified_at = timezone.now()
    ticket.save(update_fields=["client_notified_at"])


def _resolve_assignee(assignee_id) -> UserProfile | None:
    if not assignee_id:
        return None
    try:
        aid = int(assignee_id)
    except (TypeError, ValueError):
        return None
    return (
        UserProfile.objects.filter(pk=aid, user_type="IT_Support").first()
    )


@transaction.atomic
def create_ticket(
    *,
    title: str,
    contact_purpose: str,
    first_name: str,
    respond_to_email: str,
    body: str,
    username=None,
    assigned_to=None,
    priority: str = "normal",
    status: str = "new",
    created_by=None,
    notify_client: bool = False,
    system_note: str | None = None,
) -> Ticket:
    title = validate_length(title, field="Title", max_len=MAX_SUBJECT)
    if not title:
        raise ValidationError("Title is required.")
    purpose = validate_purpose(contact_purpose)
    first_name = validate_length(first_name, field="First name", max_len=MAX_FIRST_NAME)
    if not first_name:
        raise ValidationError("First name is required.")
    email = validate_email(respond_to_email)
    body = validate_length(body, field="Message", max_len=MAX_BODY)
    priority = validate_priority(priority)
    status = validate_status(status)
    now = timezone.now()

    ticket = Ticket.objects.create(
        status=status,
        title=title,
        contact_purpose=purpose,
        username=username,
        respond_to_email=email,
        first_name=first_name,
        assigned_to=assigned_to,
        creation_date=now,
        access_token=generate_access_token(),
        priority=priority,
        modification_date=now,
        last_comment_at=now if body else None,
        admin_unread=False,
        client_notified_at=None,
    )

    if body:
        _add_discussion(
            ticket,
            email=email,
            body=body,
            kind="user",
            author_user=username if getattr(username, "pk", None) else None,
            set_admin_unread=False,
        )

    note = system_note or (
        f"Ticket created by {_actor_label(created_by)}"
        if created_by
        else "Ticket created"
    )
    admin_email = getattr(created_by, "user_email", None) or "it-support@local"
    _add_discussion(
        ticket,
        email=admin_email,
        body=note,
        kind="system",
        meta={"action": "create"},
        is_system=True,
        author_user=created_by if getattr(created_by, "pk", None) else None,
        set_admin_unread=False,
    )

    if notify_client:
        notify_ticket_client(ticket=ticket, kind="ticket_created")

    return ticket


@transaction.atomic
def convert_contact_to_ticket(
    *,
    contact: ContactUs,
    created_by,
    title: str | None = None,
    contact_purpose: str | None = None,
    assigned_to_id=None,
    priority: str = "normal",
    notify_client: bool = False,
) -> Ticket:
    assignee = _resolve_assignee(assigned_to_id)
    ticket = create_ticket(
        title=title or contact.subject,
        contact_purpose=contact_purpose or contact.contact_purpose,
        first_name=contact.first_name,
        respond_to_email=contact.respond_to_email,
        body=contact.inquiry or "",
        username=contact.username,
        assigned_to=assignee,
        priority=priority,
        status="new",
        created_by=created_by,
        notify_client=False,
        system_note=(
            f"Ticket created from Contact Us by {_actor_label(created_by)}"
        ),
    )
    contact_id = contact.id
    contact.delete()
    logger.info(
        "Converted contact_us id=%s to ticket id=%s; contact row deleted",
        contact_id,
        ticket.id,
    )
    if notify_client:
        notify_ticket_client(ticket=ticket, kind="ticket_created")
    return ticket


@transaction.atomic
def set_ticket_priority(*, ticket: Ticket, priority: str, actor) -> Ticket:
    priority = validate_priority(priority)
    old = ticket.priority
    if old == priority:
        return ticket
    ticket.priority = priority
    ticket.modification_date = timezone.now()
    ticket.save(update_fields=["priority", "modification_date"])
    _add_discussion(
        ticket,
        email=getattr(actor, "user_email", None) or "it-support@local",
        body=f"{_actor_label(actor)} set priority to {priority_label(priority)}",
        kind="system",
        meta={"action": "priority", "from": old, "to": priority},
        is_system=True,
        author_user=actor,
        set_admin_unread=False,
    )
    return ticket


@transaction.atomic
def set_ticket_assignee(*, ticket: Ticket, assigned_to_id, actor) -> Ticket:
    assignee = _resolve_assignee(assigned_to_id) if assigned_to_id not in (None, "", "0") else None
    if assigned_to_id not in (None, "", "0") and assignee is None:
        raise ValidationError("Assignee must be an IT Support user.")
    old = ticket.assigned_to
    if (old.pk if old else None) == (assignee.pk if assignee else None):
        return ticket
    ticket.assigned_to = assignee
    ticket.modification_date = timezone.now()
    ticket.save(update_fields=["assigned_to", "modification_date"])
    if assignee:
        body = f"{_actor_label(actor)} assigned ticket to {_actor_label(assignee)}"
    else:
        body = f"{_actor_label(actor)} unassigned the ticket"
    _add_discussion(
        ticket,
        email=getattr(actor, "user_email", None) or "it-support@local",
        body=body,
        kind="system",
        meta={
            "action": "assign",
            "from": old.pk if old else None,
            "to": assignee.pk if assignee else None,
        },
        is_system=True,
        author_user=actor,
        set_admin_unread=False,
    )
    return ticket


@transaction.atomic
def set_ticket_status(*, ticket: Ticket, status: str, actor) -> Ticket:
    status = validate_status(status)
    old = ticket.status
    if old == status:
        return ticket
    ticket.status = status
    ticket.modification_date = timezone.now()
    ticket.save(update_fields=["status", "modification_date"])
    _add_discussion(
        ticket,
        email=getattr(actor, "user_email", None) or "it-support@local",
        body=f"{_actor_label(actor)} set status to {status_label(status)}",
        kind="system",
        meta={"action": "status", "from": old, "to": status},
        is_system=True,
        author_user=actor,
        set_admin_unread=False,
    )
    return ticket


@transaction.atomic
def add_admin_comment(
    *,
    ticket: Ticket,
    actor,
    body: str,
    notify_client: bool = False,
) -> TicketDiscussion:
    body = validate_length(body, field="Comment", max_len=MAX_BODY)
    if not body:
        raise ValidationError("Comment cannot be empty.")
    row = _add_discussion(
        ticket,
        email=getattr(actor, "user_email", None) or "it-support@local",
        body=body,
        kind="user",
        author_user=actor,
        set_admin_unread=False,
    )
    if notify_client:
        notify_ticket_client(ticket=ticket, kind="ticket_updated")
    return row


@transaction.atomic
def add_client_comment(*, ticket: Ticket, body: str, author_user=None) -> TicketDiscussion:
    body = validate_length(body, field="Comment", max_len=MAX_BODY)
    if not body:
        raise ValidationError("Comment cannot be empty.")

    reopened_from = None
    if ticket.status in ("closed", "canceled"):
        reopened_from = ticket.status
        ticket.status = "open"
        ticket.save(update_fields=["status"])

    row = _add_discussion(
        ticket,
        email=ticket.respond_to_email,
        body=body,
        kind="user",
        author_user=author_user,
        set_admin_unread=True,
    )
    if reopened_from:
        _add_discussion(
            ticket,
            email=ticket.respond_to_email,
            body="Client comment reopened ticket",
            kind="system",
            meta={
                "action": "reopen",
                "from": reopened_from,
                "to": "open",
            },
            is_system=True,
            author_user=author_user,
            set_admin_unread=True,
        )
    return row


def clear_admin_unread(ticket: Ticket) -> None:
    if not ticket.admin_unread:
        return
    ticket.admin_unread = False
    ticket.save(update_fields=["admin_unread"])


@transaction.atomic
def delete_discussion_comment(*, ticket: Ticket, discussion_id, actor=None) -> None:
    """IT admin hard-delete of a discussion row on this ticket."""
    try:
        did = int(discussion_id)
    except (TypeError, ValueError):
        raise ValidationError("Invalid comment.")
    row = (
        TicketDiscussion.objects.select_for_update()
        .filter(pk=did, ticket_reference=ticket)
        .first()
    )
    if row is None:
        raise ValidationError("Comment not found on this ticket.")
    row.delete()
    latest = (
        TicketDiscussion.objects.filter(ticket_reference=ticket)
        .order_by("-creation_date", "-id")
        .values_list("creation_date", flat=True)
        .first()
    )
    if latest is not None and timezone.is_naive(latest):
        latest = timezone.make_aware(latest)
    ticket.last_comment_at = latest
    ticket.modification_date = timezone.now()
    ticket.save(update_fields=["last_comment_at", "modification_date"])
    if actor is not None:
        logger.info(
            "Deleted ticket_discussion id=%s ticket_id=%s by user_id=%s",
            did,
            ticket.id,
            getattr(actor, "user_id", None) or getattr(actor, "pk", None),
        )


def can_delete_ticket(ticket: Ticket) -> bool:
    return (ticket.status or "") in DELETABLE_TICKET_STATUSES


@transaction.atomic
def delete_ticket(ticket: Ticket) -> None:
    if not can_delete_ticket(ticket):
        raise ValidationError("Only closed or canceled tickets can be deleted.")
    ticket.delete()


def delete_contact(contact: ContactUs) -> None:
    """Delete a Contact Us row. Never notifies the client."""
    contact.delete()


def it_support_users():
    return UserProfile.objects.filter(user_type="IT_Support").order_by(
        "username"
    )


FILTER_PARAM_KEYS = (
    "status",
    "priority",
    "assigned_to",
    "requester",
    "unread",
    "sort",
    "dir",
)

BUILTIN_FILTER_DEFAULTS = {
    "status": "",
    "priority": "",
    "assigned_to": "",
    "requester": "",
    "unread": "",
    "sort": "last_activity",
    "dir": "desc",
}


def sanitize_ticket_filters(raw) -> dict:
    """Keep only known filter keys with string values safe for the list query."""
    src = raw if isinstance(raw, dict) else {}
    out = dict(BUILTIN_FILTER_DEFAULTS)
    for key in FILTER_PARAM_KEYS:
        if key not in src:
            continue
        value = src.get(key)
        if value is None:
            value = ""
        value = str(value).strip()
        if key == "status":
            if value and value != "all" and value not in TICKET_STATUS_VALUES:
                value = ""
        elif key == "priority":
            if value and value not in TICKET_PRIORITY_VALUES:
                value = ""
        elif key == "assigned_to":
            if value and value != "unassigned" and not value.isdigit():
                value = ""
        elif key == "requester":
            if value and not value.isdigit():
                value = ""
        elif key == "unread":
            value = "1" if value in ("1", "true", "yes", "on") else ""
        elif key == "sort":
            if value not in (
                "creation_date",
                "last_activity",
                "last_comment_at",
                "status",
                "priority",
                "title",
            ):
                value = "last_activity"
        elif key == "dir":
            value = "asc" if value == "asc" else "desc"
        out[key] = value
    return out


def filters_from_request_get(querydict) -> dict:
    raw = {key: querydict.get(key, "") for key in FILTER_PARAM_KEYS}
    return sanitize_ticket_filters(raw)


def get_ticket_filter_defaults(user) -> dict | None:
    """Return saved defaults for the user, or None if none saved."""
    if user is None:
        return None
    user_id = getattr(user, "user_id", None) or getattr(user, "pk", None)
    if user_id is None:
        return None
    row = TicketAdminFilterPref.objects.filter(pk=user_id).first()
    if row is None:
        return None
    return sanitize_ticket_filters(row.filters)


def save_ticket_filter_defaults(*, user, filters) -> TicketAdminFilterPref:
    cleaned = sanitize_ticket_filters(filters)
    user_id = getattr(user, "user_id", None) or getattr(user, "pk", None)
    now = timezone.now()
    row, _created = TicketAdminFilterPref.objects.update_or_create(
        pk=user_id,
        defaults={"filters": cleaned, "updated_at": now},
    )
    return row


def clear_ticket_filter_defaults(user) -> bool:
    user_id = getattr(user, "user_id", None) or getattr(user, "pk", None)
    if user_id is None:
        return False
    deleted, _ = TicketAdminFilterPref.objects.filter(pk=user_id).delete()
    return deleted > 0


def filter_tickets_queryset(qs, params):
    """Apply list filters. Empty status = active (excludes closed/canceled)."""
    params = sanitize_ticket_filters(params)
    status = (params.get("status") or "").strip()
    if status and status != "all" and status in TICKET_STATUS_VALUES:
        qs = qs.filter(status=status)
    elif status == "all":
        pass
    else:
        qs = qs.filter(status__in=ACTIVE_TICKET_STATUSES)

    priority = (params.get("priority") or "").strip()
    if priority in TICKET_PRIORITY_VALUES:
        qs = qs.filter(priority=priority)

    assigned = (params.get("assigned_to") or "").strip()
    if assigned == "unassigned":
        qs = qs.filter(assigned_to__isnull=True)
    elif assigned.isdigit():
        qs = qs.filter(assigned_to_id=int(assigned))

    requester = (params.get("requester") or "").strip()
    if requester.isdigit():
        qs = qs.filter(username_id=int(requester))

    if (params.get("unread") or "").strip() in ("1", "true", "yes", "on"):
        qs = qs.filter(admin_unread=True)

    sort = (params.get("sort") or "last_activity").strip()
    direction = (params.get("dir") or "desc").strip().lower()
    prefix = "" if direction == "asc" else "-"
    sort_map = {
        "creation_date": "creation_date",
        "last_activity": "modification_date",
        "last_comment_at": "last_comment_at",
        "status": "status",
        "priority": "priority",
        "title": "title",
    }
    field = sort_map.get(sort, "modification_date")
    return qs.order_by(f"{prefix}{field}", f"{prefix}id")


def discussions_for_ticket(ticket: Ticket):
    return (
        TicketDiscussion.objects.filter(ticket_reference=ticket)
        .select_related("author_user")
        .order_by("creation_date", "id")
    )


def search_qa_articles(q: str, *, limit: int = 15):
    from .help_qa import search_by_titles
    from .models import QA

    term = (q or "").strip()
    qs = QA.objects.all()
    if term:
        qs = search_by_titles(qs, term)[:limit]
    else:
        qs = qs.order_by("-view_count", "id")[:limit]
    return [
        {
            "id": a.id,
            "title": a.title or "(untitled)",
            "detail_url": reverse("qa_detail", kwargs={"article_id": a.id}),
        }
        for a in qs
    ]
