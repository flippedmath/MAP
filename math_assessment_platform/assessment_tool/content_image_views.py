"""Upload and garbage-collect Quill/content images."""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .content_images import (
    MAX_UPLOAD_BYTES,
    public_url_for_storage_path,
    store_content_image,
)

logger = logging.getLogger(__name__)

_ALLOWED_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
}


@login_required
@require_POST
def content_image_upload_view(request):
    """
    Accept a multipart image upload, optimize it, store under media/content_images/,
    and return { success, url, path, id }.
    """
    upload = request.FILES.get("image") or request.FILES.get("file")
    if upload is None:
        return JsonResponse({"success": False, "error": "No image file provided."}, status=400)

    content_type = (getattr(upload, "content_type", None) or "").split(";")[0].strip().lower()
    if content_type and content_type not in _ALLOWED_TYPES:
        # Some browsers omit type; still try if filename looks like an image.
        name = (getattr(upload, "name", "") or "").lower()
        if not any(name.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
            return JsonResponse(
                {"success": False, "error": "Unsupported image type."},
                status=400,
            )

    raw = upload.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        return JsonResponse(
            {"success": False, "error": "Image exceeds the maximum upload size (10 MB)."},
            status=400,
        )

    try:
        row = store_content_image(
            uploaded_by=request.user,
            raw_bytes=raw,
            original_filename=getattr(upload, "name", "") or "image",
            content_type=content_type or None,
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    except Exception:
        logger.exception("content_image upload failed for user_id=%s", getattr(request.user, "pk", None))
        return JsonResponse(
            {"success": False, "error": "Could not process that image."},
            status=500,
        )

    return JsonResponse(
        {
            "success": True,
            "id": row.pk,
            "path": row.storage_path,
            "url": public_url_for_storage_path(row.storage_path),
        }
    )
