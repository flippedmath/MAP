"""
Canonical top-level explorer folder names under each user's ``{username}_root``.

Keep path strings and default-folder creation in sync via these constants.
"""

from __future__ import annotations

import re

FOLDER_COURSES = "Courses"
FOLDER_WORKSPACE = "Workspace"
FOLDER_COLLABORATION = "Collaboration"
FOLDER_STUDENT_PROVIDED = "Student Provided Assessments"
FOLDER_PUBLIC_LIBRARY = "Public Library"
FOLDER_TRASH = "Trash"

# Legacy names → current names (applied by setup_folders migrate).
FOLDER_RENAMES = {
    "Shared for Collaboration": FOLDER_COLLABORATION,
    "Student Generated Assessments by Course": FOLDER_STUDENT_PROVIDED,
    "Public": FOLDER_PUBLIC_LIBRARY,
}

# Folders merged into Workspace (contents moved, then legacy nodes removed).
WORKSPACE_LEGACY_SOURCES = (
    "Standalone Assessments",
    "Standalone Problems",
)

# Top-level system folders that cannot be renamed/deleted.
CORE_TOP_LEVEL_FOLDERS = frozenset(
    {
        FOLDER_COURSES,
        FOLDER_WORKSPACE,
        FOLDER_COLLABORATION,
        FOLDER_STUDENT_PROVIDED,
        FOLDER_PUBLIC_LIBRARY,
        FOLDER_TRASH,
        # legacy (still protected if a migrate hasn't run yet)
        "Standalone Assessments",
        "Standalone Problems",
        "Shared for Collaboration",
        "Student Generated Assessments by Course",
        "Public",
    }
)

# Paths under which "New Folder" is blocked (Workspace is intentionally omitted).
PROTECTED_SUBTREE_FOLDER_NAMES = (
    FOLDER_COURSES,
    FOLDER_COLLABORATION,
    FOLDER_STUDENT_PROVIDED,
    FOLDER_PUBLIC_LIBRARY,
    FOLDER_TRASH,
    # legacy
    "Standalone Assessments",
    "Shared for Collaboration",
    "Student Generated Assessments by Course",
    "Public",
)


def default_top_level_folders_for_user(user) -> list[str]:
    """Folders created under a new user's root (order is display-friendly)."""
    folders = [
        FOLDER_COURSES,
        FOLDER_WORKSPACE,
        FOLDER_COLLABORATION,
        FOLDER_PUBLIC_LIBRARY,
        FOLDER_TRASH,
    ]
    if getattr(user, "user_type", None) == "Student":
        # Keep Courses / Workspace / Collaboration / Student / Public / Trash grouping.
        folders = [
            FOLDER_COURSES,
            FOLDER_WORKSPACE,
            FOLDER_COLLABORATION,
            FOLDER_STUDENT_PROVIDED,
            FOLDER_PUBLIC_LIBRARY,
            FOLDER_TRASH,
        ]
    return folders


def user_root_path(username: str) -> str:
    return f"/Users/{username}_root/"


def protected_subtree_prefixes(username: str) -> list[str]:
    root = user_root_path(username)
    return [f"{root}{name}/" for name in PROTECTED_SUBTREE_FOLDER_NAMES]


def core_top_level_paths(username: str) -> list[str]:
    root = user_root_path(username)
    return [f"{root}{name}/" for name in sorted(CORE_TOP_LEVEL_FOLDERS)]


def student_provided_assessments_path(username: str, course_name: str | None = None) -> str:
    base = f"{user_root_path(username)}{FOLDER_STUDENT_PROVIDED}/"
    if course_name:
        return f"{base}{course_name}/"
    return base


# Match /Users/<username>_root/Workspace/ anywhere in a branch path.
_WORKSPACE_PATH_RE = re.compile(
    rf"/Users/[^/]+_root/{re.escape(FOLDER_WORKSPACE)}/"
)

WORKSPACE_COURSE_MANAGEMENT_MESSAGE = (
    "Course Management is not available for courses stored under Workspace. "
    "Move or publish the course under Courses before inviting students or teachers."
)


def branch_path_is_under_workspace(full_path: str | None) -> bool:
    """True when ``full_path`` is under a user-root Workspace folder."""
    if not full_path:
        return False
    return bool(_WORKSPACE_PATH_RE.search(full_path))


def branch_is_under_workspace(branch) -> bool:
    """True when ``branch`` is the Workspace folder or a descendant of it."""
    if branch is None:
        return False
    full_path = branch.get_parent_path() + branch.name + "/"
    return branch_path_is_under_workspace(full_path)


def course_is_under_workspace(course) -> bool:
    """True when the course's explorer folder lives under Workspace."""
    if course is None:
        return False
    branch = getattr(course, "branch_location", None)
    if branch is None:
        branch_id = getattr(course, "branch_location_id", None)
        if not branch_id:
            return False
        from .models import BranchGroup

        branch = BranchGroup.objects.filter(pk=branch_id).first()
    return branch_is_under_workspace(branch)
