"""
Private credit invoice PDF storage and access control.

Files are stored under PRIVATE_FILE_ROOT (outside MEDIA_ROOT) so DEBUG media
serving cannot expose them. Downloads go through an authenticated view.
PDFs are stored as uploaded — never resized or recompressed.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .models import CreditInvoice, CreditLedger, UserProfile

STORAGE_PREFIX = "credit_invoices"
MAX_INVOICE_BYTES = 25 * 1024 * 1024
_PDF_MAGIC = b"%PDF"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-]+")


def private_file_root() -> Path:
    root = getattr(settings, "PRIVATE_FILE_ROOT", None) or os.path.join(
        settings.BASE_DIR, "private_files"
    )
    return Path(root)


def absolute_path_for_storage(storage_path: str) -> Path:
    """Resolve a relative storage_path under PRIVATE_FILE_ROOT (no traversal)."""
    rel = (storage_path or "").replace("\\", "/").lstrip("/")
    if not rel.startswith(f"{STORAGE_PREFIX}/"):
        raise ValueError("Invalid invoice storage path.")
    if ".." in rel.split("/"):
        raise ValueError("Invalid invoice storage path.")
    full = (private_file_root() / rel).resolve()
    root = private_file_root().resolve()
    if not str(full).startswith(str(root) + os.sep) and full != root:
        raise ValueError("Invalid invoice storage path.")
    return full


def user_can_access_invoice(user, invoice: CreditInvoice) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "user_type", None) == "IT_Support":
        return True
    return invoice.owner_user_id == user.pk


def _safe_original_filename(name: str | None) -> str:
    raw = (name or "invoice.pdf").strip() or "invoice.pdf"
    base = os.path.basename(raw)
    cleaned = _SAFE_NAME_RE.sub("_", base)[:200]
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned


def _read_uploaded_pdf(uploaded_file) -> tuple[bytes, str]:
    if uploaded_file is None:
        raise ValueError("Choose a PDF invoice to upload.")
    name = getattr(uploaded_file, "name", "") or ""
    ctype = (getattr(uploaded_file, "content_type", None) or "").lower()
    if not name.lower().endswith(".pdf") and "pdf" not in ctype:
        raise ValueError("Invoice must be a PDF file.")

    size = getattr(uploaded_file, "size", None)
    if size is not None and size > MAX_INVOICE_BYTES:
        raise ValueError(
            f"Invoice PDF must be at most {MAX_INVOICE_BYTES // (1024 * 1024)} MB."
        )

    chunks: list[bytes] = []
    total = 0
    for chunk in uploaded_file.chunks():
        total += len(chunk)
        if total > MAX_INVOICE_BYTES:
            raise ValueError(
                f"Invoice PDF must be at most {MAX_INVOICE_BYTES // (1024 * 1024)} MB."
            )
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data.startswith(_PDF_MAGIC):
        raise ValueError("Invoice file does not look like a valid PDF.")
    return data, _safe_original_filename(name)


def store_invoice_pdf(
    *,
    owner: UserProfile,
    uploaded_by: UserProfile | None,
    uploaded_file,
) -> CreditInvoice:
    """Persist an uploaded PDF as-is under private_files/credit_invoices/."""
    data, original_filename = _read_uploaded_pdf(uploaded_file)
    relative = f"{STORAGE_PREFIX}/user_{owner.pk}/{uuid.uuid4().hex}.pdf"
    dest = absolute_path_for_storage(relative)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

    return CreditInvoice.objects.create(
        owner_user=owner,
        uploaded_by=uploaded_by if getattr(uploaded_by, "pk", None) else None,
        storage_path=relative,
        original_filename=original_filename,
        content_type="application/pdf",
        byte_size=len(data),
        creation_date=timezone.now(),
    )


def invoice_for_ledger_row(row: CreditLedger) -> CreditInvoice | None:
    if row.invoice_id:
        return row.invoice
    purchase = getattr(row, "related_purchase", None)
    if purchase is not None and purchase.invoice_id:
        return purchase.invoice
    return None


def require_note_without_invoice(note: str | None, invoice) -> str:
    """Assignments without an invoice require a note; with invoice, note is optional."""
    text = (note or "").strip()
    if invoice is None and not text:
        raise ValueError(
            "A note is required when assigning credits without an invoice."
        )
    return text
