"""
Content-image uploads: optimize, store under media/content_images/, registry + GC.

Images are append-only. Replacing an image in Quill uploads a new file/URL so
historic StudentAssessmentProblem.body_html (and other copies) keep working.
"""

from __future__ import annotations

import io
import logging
import re
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection, transaction
from django.utils import timezone
from PIL import Image, ImageOps

from .models import ContentImage

logger = logging.getLogger(__name__)

CONTENT_IMAGE_URL_PREFIX = "/media/content_images/"
STORAGE_PREFIX = "content_images"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_CONTENT_SIDE = 1600
JPEG_QUALITY = 85
UPLOAD_GRACE = timedelta(hours=24)
FULL_SWEEP_WEEKDAY = 6  # Sunday (Mon=0 … Sun=6)

# Paths that may embed /media/content_images/… URLs in text/HTML.
_REFERENCE_SOURCES = (
    ("question_block", "content"),
    ("student_assessment_problem", "body_html"),
    ("assessment_synchronized_problem", "body_html"),
    ("course", "introduction"),
    ('"Q_A"', "answer"),
)

_IMG_URL_RE = re.compile(
    r"(?:/media/content_images/|content_images/)([A-Za-z0-9._\-/=]+)",
    re.IGNORECASE,
)


def extract_content_image_keys(html: str | None) -> set[str]:
    """Return storage_path keys (content_images/…) referenced in HTML/text."""
    if not html:
        return set()
    keys: set[str] = set()
    for match in _IMG_URL_RE.finditer(str(html)):
        rel = match.group(1).lstrip("/")
        if not rel:
            continue
        # Normalize to storage path used in ContentImage.storage_path
        if not rel.startswith(f"{STORAGE_PREFIX}/"):
            rel = f"{STORAGE_PREFIX}/{rel}"
        keys.add(rel.split("?", 1)[0])
    return keys


def public_url_for_storage_path(storage_path: str) -> str:
    media_url = (getattr(settings, "MEDIA_URL", "/media/") or "/media/").rstrip("/")
    path = storage_path.lstrip("/")
    return f"{media_url}/{path}"


def _has_alpha(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA"):
        return True
    if img.mode == "P" and "transparency" in img.info:
        return True
    return False


def optimize_image_bytes(
    raw: bytes,
    *,
    content_type: str | None = None,
    max_side: int = MAX_CONTENT_SIDE,
    quality: int = JPEG_QUALITY,
) -> tuple[bytes, str, str]:
    """
    Return (bytes, extension_without_dot, mime_type).

    SVG is stored as-is (size-capped by caller). Raster images are downscaled
    and re-encoded (JPEG unless transparency requires PNG).
    """
    ctype = (content_type or "").lower()
    if "svg" in ctype or (raw.lstrip().startswith(b"<") and b"<svg" in raw[:500].lower()):
        if len(raw) > MAX_UPLOAD_BYTES:
            raise ValueError("SVG image is too large.")
        return raw, "svg", "image/svg+xml"

    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)
    keep_png = _has_alpha(img)

    if img.width > max_side or img.height > max_side:
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    if keep_png:
        if img.mode not in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
        elif img.mode == "P":
            img = img.convert("RGBA")
        img.save(out, format="PNG", optimize=True)
        return out.getvalue(), "png", "image/png"

    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        converted = img.convert("RGBA") if img.mode != "RGBA" else img
        background.paste(converted, mask=converted.split()[-1])
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue(), "jpg", "image/jpeg"


@transaction.atomic
def store_content_image(*, uploaded_by, raw_bytes: bytes, original_filename: str, content_type: str | None):
    if not raw_bytes:
        raise ValueError("Empty image upload.")
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError("Image exceeds the maximum upload size (10 MB).")

    optimized, ext, mime = optimize_image_bytes(raw_bytes, content_type=content_type)
    user_id = getattr(uploaded_by, "user_id", None) or getattr(uploaded_by, "pk", None) or "anon"
    filename = f"{uuid.uuid4().hex}.{ext}"
    storage_path = f"{STORAGE_PREFIX}/user_{user_id}/{filename}"

    saved_name = default_storage.save(storage_path, ContentFile(optimized))
    row = ContentImage.objects.create(
        storage_path=saved_name,
        original_filename=(original_filename or "")[:255] or None,
        content_type=mime,
        byte_size=len(optimized),
        uploaded_by=uploaded_by if getattr(uploaded_by, "pk", None) else None,
        creation_date=timezone.now(),
        maybe_unused_at=None,
    )
    return row


def note_removed_content_images(*, previous_html: str | None, new_html: str | None) -> int:
    """
    When HTML loses references to content images, mark them as purge candidates.
    Returns number of rows marked.
    """
    removed = extract_content_image_keys(previous_html) - extract_content_image_keys(new_html)
    if not removed:
        return 0
    now = timezone.now()
    updated = ContentImage.objects.filter(
        storage_path__in=removed,
        maybe_unused_at__isnull=True,
    ).update(maybe_unused_at=now)
    return updated


def clear_maybe_unused_for_keys(keys: set[str]) -> int:
    if not keys:
        return 0
    return ContentImage.objects.filter(
        storage_path__in=keys,
        maybe_unused_at__isnull=False,
    ).update(maybe_unused_at=None)


def track_content_image_html_change(*, previous_html: str | None, new_html: str | None) -> dict:
    """
    On save: mark dropped image URLs as purge candidates; clear flags for URLs
    still (or again) present in the new HTML.
    """
    marked = note_removed_content_images(previous_html=previous_html, new_html=new_html)
    cleared = clear_maybe_unused_for_keys(extract_content_image_keys(new_html))
    return {"marked": marked, "cleared": cleared}


def _scan_keys_in_database() -> set[str]:
    """Union of content_image storage paths found in known HTML/text columns."""
    found: set[str] = set()
    with connection.cursor() as cursor:
        for table, column in _REFERENCE_SOURCES:
            try:
                cursor.execute(
                    f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL "
                    f"AND {column}::text LIKE %s",
                    [f"%{STORAGE_PREFIX}%"],
                )
            except Exception:
                logger.exception("content_image scan failed for %s.%s", table, column)
                continue
            for (blob,) in cursor.fetchall():
                found |= extract_content_image_keys(blob)
    return found


def purge_unused_content_images(*, full_sweep: bool = False) -> dict:
    """
    Delete content images with no remaining HTML references.

    - Default: only rows with maybe_unused_at set (candidate queue).
    - full_sweep: consider all rows (still respects upload grace period).
    """
    now = timezone.now()
    grace_cutoff = now - UPLOAD_GRACE
    qs = ContentImage.objects.filter(creation_date__lte=grace_cutoff)
    if not full_sweep:
        qs = qs.filter(maybe_unused_at__isnull=False)

    candidates = list(qs)
    if not candidates:
        return {"scanned": 0, "deleted": 0, "cleared": 0, "full_sweep": full_sweep}

    referenced = _scan_keys_in_database()
    deleted = 0
    cleared = 0
    for row in candidates:
        if row.storage_path in referenced:
            if row.maybe_unused_at is not None:
                row.maybe_unused_at = None
                row.save(update_fields=["maybe_unused_at"])
                cleared += 1
            continue
        try:
            if default_storage.exists(row.storage_path):
                default_storage.delete(row.storage_path)
        except Exception:
            logger.exception("Failed deleting content image file %s", row.storage_path)
            continue
        row.delete()
        deleted += 1

    return {
        "scanned": len(candidates),
        "deleted": deleted,
        "cleared": cleared,
        "full_sweep": full_sweep,
    }


def should_run_full_sweep(now=None) -> bool:
    now = now or timezone.now()
    return now.weekday() == FULL_SWEEP_WEEKDAY
