"""
Private PDF attachments for Contact Us and support tickets.

Files live under PRIVATE_FILE_ROOT (not MEDIA). Downloads are auth/token gated.
Reasonable classroom limit: 10 MB (far below typical 100-page scanned packets).
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import ContactUs, ContactUsAttachment, Ticket, TicketAttachment, TicketDiscussion

logger = logging.getLogger(__name__)

CONTACT_STORAGE_PREFIX = "contact_us_attachments"
TICKET_STORAGE_PREFIX = "ticket_attachments"
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENT_MB = MAX_ATTACHMENT_BYTES // (1024 * 1024)
_PDF_MAGIC = b"%PDF"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-]+")


def private_file_root() -> Path:
    root = getattr(settings, "PRIVATE_FILE_ROOT", None) or os.path.join(
        settings.BASE_DIR, "private_files"
    )
    return Path(root)


def absolute_path_for_storage(storage_path: str) -> Path:
    rel = (storage_path or "").replace("\\", "/").lstrip("/")
    if not (
        rel.startswith(f"{CONTACT_STORAGE_PREFIX}/")
        or rel.startswith(f"{TICKET_STORAGE_PREFIX}/")
    ):
        raise ValueError("Invalid attachment storage path.")
    if ".." in rel.split("/"):
        raise ValueError("Invalid attachment storage path.")
    full = (private_file_root() / rel).resolve()
    root = private_file_root().resolve()
    if not str(full).startswith(str(root) + os.sep) and full != root:
        raise ValueError("Invalid attachment storage path.")
    return full


def _safe_original_filename(name: str | None) -> str:
    raw = (name or "attachment.pdf").strip() or "attachment.pdf"
    base = os.path.basename(raw)
    cleaned = _SAFE_NAME_RE.sub("_", base)[:200]
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned


def read_uploaded_pdf(uploaded_file) -> tuple[bytes, str]:
    if uploaded_file is None:
        raise ValueError("Choose a PDF file to upload.")
    name = getattr(uploaded_file, "name", "") or ""
    ctype = (getattr(uploaded_file, "content_type", None) or "").lower()
    if not name.lower().endswith(".pdf") and "pdf" not in ctype:
        raise ValueError("Attachment must be a PDF file.")

    size = getattr(uploaded_file, "size", None)
    if size is not None and size > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"PDF must be at most {MAX_ATTACHMENT_MB} MB.")

    chunks: list[bytes] = []
    total = 0
    for chunk in uploaded_file.chunks():
        total += len(chunk)
        if total > MAX_ATTACHMENT_BYTES:
            raise ValueError(f"PDF must be at most {MAX_ATTACHMENT_MB} MB.")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data.startswith(_PDF_MAGIC):
        raise ValueError("File does not look like a valid PDF.")
    return data, _safe_original_filename(name)


def _write_bytes(relative: str, data: bytes) -> None:
    dest = absolute_path_for_storage(relative)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def delete_storage_file(storage_path: str | None) -> None:
    if not storage_path:
        return
    try:
        path = absolute_path_for_storage(storage_path)
    except ValueError:
        return
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        logger.exception("Failed deleting attachment file %s", storage_path)


def store_contact_us_pdf(*, contact: ContactUs, uploaded_file) -> ContactUsAttachment:
    data, original_filename = read_uploaded_pdf(uploaded_file)
    relative = f"{CONTACT_STORAGE_PREFIX}/contact_{contact.pk}/{uuid.uuid4().hex}.pdf"
    _write_bytes(relative, data)
    return ContactUsAttachment.objects.create(
        contact_us=contact,
        storage_path=relative,
        original_filename=original_filename,
        content_type="application/pdf",
        byte_size=len(data),
        creation_date=timezone.now(),
    )


def store_ticket_pdf(
    *,
    ticket: Ticket,
    uploaded_file,
    discussion: TicketDiscussion | None = None,
    uploaded_by=None,
) -> TicketAttachment:
    data, original_filename = read_uploaded_pdf(uploaded_file)
    relative = f"{TICKET_STORAGE_PREFIX}/ticket_{ticket.pk}/{uuid.uuid4().hex}.pdf"
    _write_bytes(relative, data)
    return TicketAttachment.objects.create(
        ticket=ticket,
        discussion=discussion,
        storage_path=relative,
        original_filename=original_filename,
        content_type="application/pdf",
        byte_size=len(data),
        uploaded_by=uploaded_by if getattr(uploaded_by, "pk", None) else None,
        creation_date=timezone.now(),
    )


@transaction.atomic
def migrate_contact_attachments_to_ticket(
    *,
    contact: ContactUs,
    ticket: Ticket,
    discussion: TicketDiscussion | None = None,
) -> list[TicketAttachment]:
    """
    Move Contact Us PDFs onto the new ticket (same bytes, new storage path),
    then delete contact attachment rows/files.
    """
    created: list[TicketAttachment] = []
    rows = list(
        ContactUsAttachment.objects.filter(contact_us=contact).order_by("id")
    )
    for row in rows:
        try:
            src = absolute_path_for_storage(row.storage_path)
        except ValueError:
            continue
        if not src.is_file():
            logger.warning(
                "Missing contact attachment file contact_id=%s path=%s",
                contact.pk,
                row.storage_path,
            )
            row.delete()
            continue
        data = src.read_bytes()
        relative = f"{TICKET_STORAGE_PREFIX}/ticket_{ticket.pk}/{uuid.uuid4().hex}.pdf"
        _write_bytes(relative, data)
        created.append(
            TicketAttachment.objects.create(
                ticket=ticket,
                discussion=discussion,
                storage_path=relative,
                original_filename=row.original_filename,
                content_type=row.content_type or "application/pdf",
                byte_size=row.byte_size or len(data),
                uploaded_by=None,
                creation_date=timezone.now(),
            )
        )
        old_path = row.storage_path
        row.delete()
        delete_storage_file(old_path)
    return created


def attachments_for_contact(contact: ContactUs) -> list[ContactUsAttachment]:
    return list(
        ContactUsAttachment.objects.filter(contact_us=contact).order_by("id")
    )


def attachments_for_ticket(ticket: Ticket) -> list[TicketAttachment]:
    return list(
        TicketAttachment.objects.filter(ticket=ticket)
        .select_related("discussion", "uploaded_by")
        .order_by("id")
    )


def attachments_by_discussion_id(ticket: Ticket) -> dict[int | None, list[TicketAttachment]]:
    grouped: dict[int | None, list[TicketAttachment]] = {}
    for att in attachments_for_ticket(ticket):
        key = att.discussion_id
        grouped.setdefault(key, []).append(att)
    return grouped


def delete_contact_attachments(contact: ContactUs) -> None:
    for row in ContactUsAttachment.objects.filter(contact_us=contact):
        path = row.storage_path
        row.delete()
        delete_storage_file(path)


def delete_ticket_attachments(ticket: Ticket) -> None:
    for row in TicketAttachment.objects.filter(ticket=ticket):
        path = row.storage_path
        row.delete()
        delete_storage_file(path)


def delete_discussion_attachments(discussion: TicketDiscussion) -> None:
    for row in TicketAttachment.objects.filter(discussion=discussion):
        path = row.storage_path
        row.delete()
        delete_storage_file(path)
