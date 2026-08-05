"""Template context processors for assessment_tool."""

from .notifications import user_has_unread_notifications
from .view_mode import is_content_view_only


def notifications(request):
    has_unread = False
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        try:
            has_unread = user_has_unread_notifications(user)
        except Exception:
            has_unread = False
    return {"has_unread_notifications": has_unread}


def content_view_only(request):
    return {"content_view_only": is_content_view_only(request)}


def site_announcements(request):
    try:
        from .site_announcements import announcements_for_request

        return announcements_for_request(request)
    except Exception:
        return {
            "site_announcement_banners": [],
            "site_announcement_warnings": [],
        }
