"""
Explorer / BranchGroup parent–child placement rules.

Canonical nesting for structural nodes:
  course      → assessment
  assessment  → aqg
  aqg         → cqd | problem
  cqd         → problem
  problem     → (nothing)

A plain folder may contain any node type (including aqg / cqd / problem),
but may not itself be nested under course / assessment / aqg / cqd / problem.
"""

from __future__ import annotations

_ALL_BRANCH_TYPES = frozenset(
    {"folder", "course", "assessment", "aqg", "cqd", "problem"}
)

ALLOWED_BRANCH_CHILDREN = {
    "folder": _ALL_BRANCH_TYPES,
    "course": frozenset({"assessment"}),
    "assessment": frozenset({"aqg"}),
    "aqg": frozenset({"cqd", "problem"}),
    "cqd": frozenset({"problem"}),
    "problem": frozenset(),
}

_FOLDER_TYPE_LABELS = {
    "folder": "folder",
    "course": "course",
    "assessment": "assessment",
    "aqg": "question group",
    "cqd": "problem set",
    "problem": "problem",
}


def normalize_folder_type(folder_type) -> str:
    value = (folder_type or "folder").strip().lower()
    return value or "folder"


def folder_type_label(folder_type) -> str:
    key = normalize_folder_type(folder_type)
    return _FOLDER_TYPE_LABELS.get(key, key)


def allowed_child_folder_types(parent_type) -> frozenset[str]:
    return ALLOWED_BRANCH_CHILDREN.get(normalize_folder_type(parent_type), frozenset())


def can_place_branch_under(parent_type, child_type) -> bool:
    """True when ``child_type`` may be a direct child of ``parent_type``."""
    return normalize_folder_type(child_type) in allowed_child_folder_types(parent_type)


def branch_placement_error(parent_type, child_type) -> str | None:
    """
    Return a user-facing error when placement is illegal, else None.
    """
    if can_place_branch_under(parent_type, child_type):
        return None

    parent = normalize_folder_type(parent_type)
    child = normalize_folder_type(child_type)
    parent_label = folder_type_label(parent)
    child_label = folder_type_label(child)
    allowed = allowed_child_folder_types(parent)

    if not allowed:
        return f"Nothing can be placed inside a {parent_label}."

    allowed_labels = ", ".join(folder_type_label(t) for t in sorted(allowed))
    return (
        f"Cannot place a {child_label} inside a {parent_label}. "
        f"Allowed here: {allowed_labels}."
    )


def parent_allows_new_folder(parent_type) -> bool:
    """Plain 'New Folder' only under another plain folder."""
    return can_place_branch_under(parent_type, "folder")
