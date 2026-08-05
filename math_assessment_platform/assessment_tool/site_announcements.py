"""Site-wide announcement banners and post-login warnings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import Resolver404, resolve
from django.utils import timezone
from django.utils.html import escape

from .models import SiteAnnouncement

SESSION_POST_LOGIN_KEY = "site_announcement_post_login"

PAGE_LANDING = "landing"
PAGE_ABOUT = "about"
PAGE_LOGIN = "login"
PAGE_CONTACT = "contact_us"
PAGE_DASHBOARD = "dashboard"
PAGE_LOGIN_ONCE = "login_once"

PAGE_CHOICES: tuple[tuple[str, str, str], ...] = (
    (PAGE_LANDING, "Landing page", "show_on_landing"),
    (PAGE_ABOUT, "About page", "show_on_about"),
    (PAGE_LOGIN, "Login page", "show_on_login"),
    (PAGE_CONTACT, "Contact Us page", "show_on_contact_us"),
    (PAGE_DASHBOARD, "Dashboard", "show_on_dashboard"),
    (PAGE_LOGIN_ONCE, "Once when first logging in", "show_on_login_once"),
)

_URL_NAME_TO_PAGE = {
    "home": PAGE_LANDING,
    "about": PAGE_ABOUT,
    "login": PAGE_LOGIN,
    "contact_us": PAGE_CONTACT,
    "dashboard": PAGE_DASHBOARD,
}

MAX_TITLE = 255
MAX_MESSAGE = 2000
MAX_WARNING = 2000


@dataclass(frozen=True)
class AnnouncementDisplay:
    id: int
    title: str
    message: str
    is_high_priority: bool
    warning_message: str | None = None


def mark_post_login(request) -> None:
    """Call after a successful login so warnings / login-once banners can show."""
    request.session[SESSION_POST_LOGIN_KEY] = True


def consume_post_login(request) -> bool:
    if not request.session.pop(SESSION_POST_LOGIN_KEY, False):
        return False
    request.session.modified = True
    return True


def resolve_page_key(request) -> str | None:
    try:
        match = resolve(request.path_info)
    except Resolver404:
        return None
    return _URL_NAME_TO_PAGE.get(match.url_name)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.utc)
    return dt


def _in_banner_window(row: SiteAnnouncement, now: datetime) -> bool:
    starts = _aware(row.starts_at)
    ends = _aware(row.ends_at)
    if starts is not None and now < starts:
        return False
    if ends is not None and now > ends:
        return False
    return True


def _warning_active(row: SiteAnnouncement, now: datetime) -> bool:
    if not row.warning_enabled:
        return False
    msg = (row.warning_message or "").strip()
    if not msg:
        return False
    warn_start = _aware(row.warning_starts_at)
    if warn_start is not None and now < warn_start:
        return False
    ends = _aware(row.ends_at)
    if ends is not None and now > ends:
        return False
    return True


def _page_flag(row: SiteAnnouncement, page: str) -> bool:
    for key, _label, field in PAGE_CHOICES:
        if key == page:
            return bool(getattr(row, field, False))
    return False


def _to_display(row: SiteAnnouncement, *, warning: bool = False) -> AnnouncementDisplay:
    return AnnouncementDisplay(
        id=row.id,
        title=row.title or "",
        message=(row.message or "").strip(),
        is_high_priority=bool(row.is_high_priority),
        warning_message=(row.warning_message or "").strip() if warning else None,
    )


def active_banners_for_page(page: str | None, *, now: datetime | None = None) -> list[AnnouncementDisplay]:
    if not page:
        return []
    now = now or timezone.now()
    rows = (
        SiteAnnouncement.objects.filter(is_enabled=True)
        .order_by("-is_high_priority", "-modification_date", "-id")
    )
    out: list[AnnouncementDisplay] = []
    for row in rows:
        if not _page_flag(row, page):
            continue
        if not _in_banner_window(row, now):
            continue
        msg = (row.message or "").strip()
        if not msg:
            continue
        out.append(_to_display(row))
    return out


def active_login_warnings(*, now: datetime | None = None) -> list[AnnouncementDisplay]:
    now = now or timezone.now()
    rows = (
        SiteAnnouncement.objects.filter(is_enabled=True, warning_enabled=True)
        .order_by("-is_high_priority", "-modification_date", "-id")
    )
    out: list[AnnouncementDisplay] = []
    for row in rows:
        if not _warning_active(row, now):
            continue
        out.append(_to_display(row, warning=True))
    return out


def announcements_for_request(request) -> dict:
    """
    Context for templates: page banners + optional post-login notices.

    Post-login session flag is consumed on first authenticated page load after login.
    """
    page = resolve_page_key(request)
    banners = list(active_banners_for_page(page))
    warnings: list[AnnouncementDisplay] = []

    just_logged_in = consume_post_login(request)
    if just_logged_in:
        warnings = active_login_warnings()
        for item in active_banners_for_page(PAGE_LOGIN_ONCE):
            if item.id not in {b.id for b in banners}:
                banners.append(item)

    return {
        "site_announcement_banners": banners,
        "site_announcement_warnings": warnings,
    }


def schedule_status(row: SiteAnnouncement, *, now: datetime | None = None) -> str:
    now = now or timezone.now()
    if not row.is_enabled:
        return "off"
    starts = _aware(row.starts_at)
    ends = _aware(row.ends_at)
    if starts is None and ends is None:
        return "on"
    if starts is not None and now < starts:
        return "scheduled"
    if ends is not None and now > ends:
        return "expired"
    return "active"


def page_labels(row: SiteAnnouncement) -> list[str]:
    labels = []
    for _key, label, field in PAGE_CHOICES:
        if getattr(row, field, False):
            labels.append(label)
    return labels


def _parse_optional_dt(raw: str | None, *, field: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    # datetime-local: YYYY-MM-DDTHH:MM or with seconds
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            naive = datetime.strptime(text, fmt)
            return timezone.make_aware(naive, timezone.utc)
        except ValueError:
            continue
    raise ValidationError(f"{field}: enter a valid date/time (UTC).")


def _clean_text(raw: str | None, *, field: str, max_len: int, required: bool = False) -> str:
    text = (raw or "").strip()
    if required and not text:
        raise ValidationError(f"{field} is required.")
    if len(text) > max_len:
        raise ValidationError(f"{field} must be at most {max_len} characters.")
    return text


def parse_announcement_form(post) -> dict:
    title = _clean_text(post.get("title"), field="Title", max_len=MAX_TITLE, required=True)
    message = _clean_text(post.get("message"), field="Message", max_len=MAX_MESSAGE, required=True)
    is_enabled = post.get("is_enabled") == "on"
    is_high_priority = post.get("is_high_priority") == "on"
    starts_at = _parse_optional_dt(post.get("starts_at"), field="Start")
    ends_at = _parse_optional_dt(post.get("ends_at"), field="End")
    if starts_at and ends_at and ends_at < starts_at:
        raise ValidationError("End must be after start.")

    warning_enabled = post.get("warning_enabled") == "on"
    warning_message = _clean_text(
        post.get("warning_message"), field="Warning message", max_len=MAX_WARNING
    )
    warning_starts_at = _parse_optional_dt(
        post.get("warning_starts_at"), field="Warning start"
    )
    if warning_enabled and not warning_message:
        raise ValidationError("Warning message is required when the warning is on.")

    pages = {
        field: post.get(field) == "on"
        for _key, _label, field in PAGE_CHOICES
    }
    if not any(pages.values()) and not warning_enabled:
        raise ValidationError("Select at least one page, or enable the login warning.")

    return {
        "title": title,
        "message": message,
        "is_enabled": is_enabled,
        "is_high_priority": is_high_priority,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "warning_enabled": warning_enabled,
        "warning_message": warning_message or None,
        "warning_starts_at": warning_starts_at,
        **pages,
    }


@transaction.atomic
def create_announcement(*, data: dict, created_by=None) -> SiteAnnouncement:
    now = timezone.now()
    return SiteAnnouncement.objects.create(
        **data,
        created_by=created_by if getattr(created_by, "pk", None) else None,
        creation_date=now,
        modification_date=now,
    )


@transaction.atomic
def update_announcement(row: SiteAnnouncement, *, data: dict) -> SiteAnnouncement:
    for key, value in data.items():
        setattr(row, key, value)
    row.modification_date = timezone.now()
    row.save()
    return row


@transaction.atomic
def delete_announcement(row: SiteAnnouncement) -> None:
    row.delete()


def dt_local_value(dt: datetime | None) -> str:
    """Format for datetime-local input (UTC wall time)."""
    if dt is None:
        return ""
    aware = _aware(dt)
    if aware is None:
        return ""
    utc = aware.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M")


def message_html(text: str) -> str:
    """Plain text to safe HTML (preserve line breaks)."""
    return escape(text or "").replace("\n", "<br>")


_EXPORT_BOOL_FIELDS = (
    "is_enabled",
    "is_high_priority",
    "warning_enabled",
    "show_on_landing",
    "show_on_about",
    "show_on_login",
    "show_on_contact_us",
    "show_on_dashboard",
    "show_on_login_once",
)

_EXPORT_DT_FIELDS = ("starts_at", "ends_at", "warning_starts_at")


def _dt_iso(dt: datetime | None) -> str | None:
    aware = _aware(dt)
    if aware is None:
        return None
    return aware.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso_dt(raw) -> datetime | None:
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(f"Invalid datetime: {raw!r}") from exc
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.utc)
    return parsed.astimezone(timezone.utc)


def serialize_announcement(row: SiteAnnouncement) -> dict:
    """JSON-safe payload for dump/load across environments (matched by title)."""
    payload = {
        "title": row.title or "",
        "message": row.message or "",
        "warning_message": row.warning_message or None,
    }
    for field in _EXPORT_BOOL_FIELDS:
        payload[field] = bool(getattr(row, field, False))
    for field in _EXPORT_DT_FIELDS:
        payload[field] = _dt_iso(getattr(row, field, None))
    return payload


def export_announcements(*, titles: list[str] | None = None) -> list[dict]:
    qs = SiteAnnouncement.objects.order_by("id")
    if titles:
        wanted = {t.strip() for t in titles if t and t.strip()}
        qs = qs.filter(title__in=wanted)
    return [serialize_announcement(row) for row in qs]


def upsert_announcement_payload(
    payload: dict,
    *,
    is_enabled: bool | None = None,
) -> tuple[SiteAnnouncement, bool]:
    """
    Create or update by exact title.

    If ``is_enabled`` is provided, it overrides the payload's enabled flag
    (used when deploying so the operator can force on/off on live).
    """
    title = _clean_text(payload.get("title"), field="Title", max_len=MAX_TITLE, required=True)
    data = {
        "title": title,
        "message": _clean_text(
            payload.get("message"), field="Message", max_len=MAX_MESSAGE, required=True
        ),
        "is_high_priority": bool(payload.get("is_high_priority")),
        "starts_at": _parse_iso_dt(payload.get("starts_at")),
        "ends_at": _parse_iso_dt(payload.get("ends_at")),
        "warning_enabled": bool(payload.get("warning_enabled")),
        "warning_message": _clean_text(
            payload.get("warning_message"), field="Warning message", max_len=MAX_WARNING
        )
        or None,
        "warning_starts_at": _parse_iso_dt(payload.get("warning_starts_at")),
        "show_on_landing": bool(payload.get("show_on_landing")),
        "show_on_about": bool(payload.get("show_on_about")),
        "show_on_login": bool(payload.get("show_on_login")),
        "show_on_contact_us": bool(payload.get("show_on_contact_us")),
        "show_on_dashboard": bool(payload.get("show_on_dashboard")),
        "show_on_login_once": bool(payload.get("show_on_login_once")),
    }
    if is_enabled is None:
        data["is_enabled"] = bool(payload.get("is_enabled", True))
    else:
        data["is_enabled"] = bool(is_enabled)

    row = SiteAnnouncement.objects.filter(title=title).order_by("id").first()
    if row is None:
        return create_announcement(data=data), True
    return update_announcement(row, data=data), False


@transaction.atomic
def import_announcements(
    payloads: list[dict],
    *,
    enabled_overrides: dict[str, bool] | None = None,
) -> dict:
    """
    Upsert a list of serialized announcements.

    ``enabled_overrides`` maps title -> desired is_enabled on this environment.
    """
    overrides = enabled_overrides or {}
    created = 0
    updated = 0
    for payload in payloads:
        title = (payload.get("title") or "").strip()
        override = overrides.get(title)
        _row, was_created = upsert_announcement_payload(payload, is_enabled=override)
        if was_created:
            created += 1
        else:
            updated += 1
    return {"created": created, "updated": updated, "total": created + updated}
