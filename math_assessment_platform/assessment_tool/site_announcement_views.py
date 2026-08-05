"""IT admin CRUD for site-wide announcements."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_http_methods, require_POST

from .models import SiteAnnouncement
from . import site_announcements as ann_lib


def _is_it_support(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "user_type", None) == "IT_Support"
    )


it_required = user_passes_test(_is_it_support, login_url="/login/")


def _form_from_row(row: SiteAnnouncement | None) -> dict:
    if row is None:
        return {
            "title": "",
            "message": "",
            "is_enabled": True,
            "is_high_priority": False,
            "starts_at": "",
            "ends_at": "",
            "warning_enabled": False,
            "warning_message": "",
            "warning_starts_at": "",
            "show_on_landing": False,
            "show_on_about": False,
            "show_on_login": False,
            "show_on_contact_us": False,
            "show_on_dashboard": False,
            "show_on_login_once": False,
        }
    return {
        "title": row.title or "",
        "message": row.message or "",
        "is_enabled": bool(row.is_enabled),
        "is_high_priority": bool(row.is_high_priority),
        "starts_at": ann_lib.dt_local_value(row.starts_at),
        "ends_at": ann_lib.dt_local_value(row.ends_at),
        "warning_enabled": bool(row.warning_enabled),
        "warning_message": row.warning_message or "",
        "warning_starts_at": ann_lib.dt_local_value(row.warning_starts_at),
        "show_on_landing": bool(row.show_on_landing),
        "show_on_about": bool(row.show_on_about),
        "show_on_login": bool(row.show_on_login),
        "show_on_contact_us": bool(row.show_on_contact_us),
        "show_on_dashboard": bool(row.show_on_dashboard),
        "show_on_login_once": bool(row.show_on_login_once),
    }


def _form_from_post(post) -> dict:
    return {
        "title": (post.get("title") or "").strip(),
        "message": (post.get("message") or "").strip(),
        "is_enabled": post.get("is_enabled") == "on",
        "is_high_priority": post.get("is_high_priority") == "on",
        "starts_at": (post.get("starts_at") or "").strip(),
        "ends_at": (post.get("ends_at") or "").strip(),
        "warning_enabled": post.get("warning_enabled") == "on",
        "warning_message": (post.get("warning_message") or "").strip(),
        "warning_starts_at": (post.get("warning_starts_at") or "").strip(),
        "show_on_landing": post.get("show_on_landing") == "on",
        "show_on_about": post.get("show_on_about") == "on",
        "show_on_login": post.get("show_on_login") == "on",
        "show_on_contact_us": post.get("show_on_contact_us") == "on",
        "show_on_dashboard": post.get("show_on_dashboard") == "on",
        "show_on_login_once": post.get("show_on_login_once") == "on",
    }


@it_required
@require_http_methods(["GET", "POST"])
def site_announcements_admin_view(request):
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "create":
            form = _form_from_post(request.POST)
            try:
                data = ann_lib.parse_announcement_form(request.POST)
                row = ann_lib.create_announcement(data=data, created_by=request.user)
            except ValidationError as exc:
                messages.error(
                    request,
                    "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc),
                )
                return _render_list(request, create_form=form, show_create=True)
            messages.success(request, f"Announcement “{row.title}” created.")
            return redirect("site_announcements_admin")
        messages.error(request, "Unknown action.")
        return redirect("site_announcements_admin")

    return _render_list(request)


@it_required
@require_http_methods(["GET", "POST"])
def site_announcement_edit_view(request, announcement_id: int):
    row = get_object_or_404(SiteAnnouncement, pk=announcement_id)
    if request.method == "POST":
        form = _form_from_post(request.POST)
        try:
            data = ann_lib.parse_announcement_form(request.POST)
            ann_lib.update_announcement(row, data=data)
        except ValidationError as exc:
            messages.error(
                request,
                "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc),
            )
            return render(
                request,
                "assessment_tool/site_announcement_edit.html",
                _edit_context(row, form),
            )
        messages.success(request, "Announcement updated.")
        return redirect("site_announcements_admin")
    return render(
        request,
        "assessment_tool/site_announcement_edit.html",
        _edit_context(row, _form_from_row(row)),
    )


@it_required
@require_POST
def site_announcement_delete_view(request, announcement_id: int):
    row = get_object_or_404(SiteAnnouncement, pk=announcement_id)
    title = row.title
    ann_lib.delete_announcement(row)
    messages.success(request, f"Announcement “{title}” deleted.")
    return redirect("site_announcements_admin")


@it_required
@require_POST
def site_announcement_toggle_view(request, announcement_id: int):
    row = get_object_or_404(SiteAnnouncement, pk=announcement_id)
    row.is_enabled = not bool(row.is_enabled)
    row.modification_date = timezone.now()
    row.save(update_fields=["is_enabled", "modification_date"])
    state = "on" if row.is_enabled else "off"
    messages.success(request, f"Announcement “{row.title}” turned {state}.")
    return redirect("site_announcements_admin")


def _page_fields(form: dict) -> list[tuple[str, str, bool]]:
    return [
        (field, label, bool(form.get(field)))
        for _key, label, field in ann_lib.PAGE_CHOICES
    ]


def _edit_context(row: SiteAnnouncement, form: dict) -> dict:
    return {
        "announcement": row,
        "form": form,
        "page_fields": _page_fields(form),
        "max_title": ann_lib.MAX_TITLE,
        "max_message": ann_lib.MAX_MESSAGE,
        "max_warning": ann_lib.MAX_WARNING,
        "status": ann_lib.schedule_status(row),
    }


def _render_list(request, *, create_form=None, show_create=False):
    form = create_form or _form_from_row(None)
    rows = []
    for row in SiteAnnouncement.objects.order_by("-is_enabled", "-is_high_priority", "-id"):
        rows.append(
            {
                "row": row,
                "status": ann_lib.schedule_status(row),
                "pages": ann_lib.page_labels(row),
                "preview": mark_safe(ann_lib.message_html(row.message)),
            }
        )
    return render(
        request,
        "assessment_tool/site_announcements_admin.html",
        {
            "announcement_rows": rows,
            "create_form": form,
            "page_fields": _page_fields(form),
            "show_create": show_create,
            "max_title": ann_lib.MAX_TITLE,
            "max_message": ann_lib.MAX_MESSAGE,
            "max_warning": ann_lib.MAX_WARNING,
        },
    )
