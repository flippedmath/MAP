"""
Explorer open-in-view / open-in-edit mode helpers.

When a Teacher/IT user opens a course or assessment from the explorer with
``?mode=view``, the session is marked view-only so content save endpoints
reject mutations until they open something with ``?mode=edit`` (or clear).
"""

from __future__ import annotations

import re

from django.http import JsonResponse

SESSION_KEY = "explorer_content_view_only"

VIEW_ONLY_MESSAGE = (
    "You are in view-only mode and cannot save edits. "
    "Open the item in Edit mode from the explorer to make changes."
)

# Mutating requests under these path patterns are blocked while view-only.
_BLOCKED_PATH = re.compile(
    r"^/("
    r"api/problem/"
    r"|problem/\d+/"
    r"|add-cqd-ajax/"
    r"|update-cqd-"
    r"|courses/\d+/?$"
    r"|courses/api/"
    r"|course/\d+/(management|assessments|assessment)/"
    r"|course/api/"
    r"|assessment/api/"
    r")"
)

# Ephemeral practice-test assembly/grading — not content saves.
_ALLOWED_WHILE_VIEW_ONLY = re.compile(
    r"^/course/\d+/assessment/\d+/setup/practice-test/(start|grade)/?$"
)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def apply_explorer_mode_from_request(request, *, allow_edit: bool | None = None) -> bool | None:
    """
    If ``mode`` query param is present, update the session flag.

    When ``mode=edit`` but ``allow_edit`` is False (caller lacks edit ACL),
    force view-only so save endpoints stay blocked.

    Returns True/False for the resulting view-only state, or None if unchanged.
    """
    mode = (request.GET.get("mode") or "").strip().lower()
    if mode == "view":
        request.session[SESSION_KEY] = True
        return True
    if mode == "edit":
        if allow_edit is False:
            request.session[SESSION_KEY] = True
            return True
        request.session[SESSION_KEY] = False
        return False
    return None


def force_content_view_only(request) -> None:
    request.session[SESSION_KEY] = True


def clear_content_view_only(request) -> None:
    request.session[SESSION_KEY] = False


def is_content_view_only(request) -> bool:
    return bool(request.session.get(SESSION_KEY))


def view_only_json_response():
    return JsonResponse(
        {"success": False, "ok": False, "error": VIEW_ONLY_MESSAGE, "code": "content_view_only"},
        status=403,
    )


def path_is_content_mutation(path: str) -> bool:
    return bool(_BLOCKED_PATH.match(path or ""))


def path_is_view_only_allowed(path: str) -> bool:
    return bool(_ALLOWED_WHILE_VIEW_ONLY.match(path or ""))


def should_block_content_mutation(request) -> bool:
    if request.method in _SAFE_METHODS:
        return False
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return False
    if not is_content_view_only(request):
        return False
    if path_is_view_only_allowed(request.path):
        return False
    return path_is_content_mutation(request.path)
