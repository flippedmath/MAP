"""
Collaboration ACL helpers: permission groups, branch sharing, effective perms.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from .folder_roots import (
    FOLDER_COLLABORATION,
    FOLDER_PUBLIC_LIBRARY,
    FOLDER_TRASH,
    FOLDER_WORKSPACE,
    user_root_path,
)
from .notifications import create_notification

logger = logging.getLogger(__name__)

PUBLIC_GROUP_NAME = "public"
ADMINS_GROUP_NAME = "admins"
SYSTEM_GROUP_NAMES = frozenset({PUBLIC_GROUP_NAME, ADMINS_GROUP_NAME})
PERM_OWNER = "owner"
PERM_EDIT = "edit"
PERM_READ_ONLY = "read_only"
PERM_RANK = {PERM_READ_ONLY: 1, PERM_EDIT: 2, PERM_OWNER: 3}
COLLAB_ELIGIBLE_TYPES = ("Teacher", "IT_Support")
TRASH_RETENTION = timedelta(days=30)


def _models():
    from . import models as m
    return m


def max_perm(*perms):
    best = None
    best_rank = 0
    for p in perms:
        if not p:
            continue
        r = PERM_RANK.get(p, 0)
        if r > best_rank:
            best, best_rank = p, r
    return best


def min_access(*perms):
    """Lowest among edit/read_only (owner treated as edit). Used for nested path caps."""
    best = None
    best_rank = 999
    for p in perms:
        if not p:
            continue
        access = PERM_EDIT if p == PERM_OWNER else p
        if access not in (PERM_EDIT, PERM_READ_ONLY):
            continue
        r = PERM_RANK[access]
        if r < best_rank:
            best, best_rank = access, r
    return best


def is_system_group(pg) -> bool:
    if pg is None:
        return False
    if getattr(pg, "system_protected", False):
        return True
    return (pg.name or "") in SYSTEM_GROUP_NAMES


def ensure_admins_group():
    """
    Create/repair the non-deletable ``admins`` group and enroll all IT_Support users.
    ``admins`` owns the system ``public`` group (via owner_pg_id), so public content
    is not tied to an individual user's Workspace.
    """
    m = _models()
    PermissionGroup = m.PermissionGroup
    UserProfile = m.UserProfile

    admins, _created = PermissionGroup.objects.get_or_create(
        name=ADMINS_GROUP_NAME,
        defaults={"owner": None, "system_protected": True},
    )
    dirty = []
    if not admins.system_protected:
        admins.system_protected = True
        dirty.append("system_protected")
    if admins.owner_id is not None:
        admins.owner = None
        dirty.append("owner")
    if dirty:
        admins.save(update_fields=dirty)

    for user in UserProfile.objects.filter(user_type="IT_Support"):
        upsert_group_membership(user, admins, PERM_OWNER)

    return admins


def ensure_public_group():
    """Create/repair the system ``public`` group owned by ``admins``; enroll Teachers / IT."""
    m = _models()
    UserProfile = m.UserProfile
    PermissionGroup = m.PermissionGroup

    admins = ensure_admins_group()

    pg, created = PermissionGroup.objects.get_or_create(
        name=PUBLIC_GROUP_NAME,
        defaults={
            "owner": None,
            "owner_pg": admins,
            "system_protected": True,
        },
    )
    dirty = []
    if not pg.system_protected:
        pg.system_protected = True
        dirty.append("system_protected")
    if pg.owner_id is not None:
        pg.owner = None
        dirty.append("owner")
    if pg.owner_pg_id != admins.id:
        pg.owner_pg = admins
        dirty.append("owner_pg")
    if dirty:
        pg.save(update_fields=dirty)

    # IT Support: edit on public (ownership of public is via admins group, not a user row).
    for user in UserProfile.objects.filter(user_type="IT_Support"):
        upsert_group_membership(user, pg, PERM_EDIT)

    for user in UserProfile.objects.filter(user_type="Teacher"):
        upsert_group_membership(user, pg, PERM_READ_ONLY)

    return pg


def enroll_user_in_public_if_eligible(user):
    if getattr(user, "user_type", None) not in COLLAB_ELIGIBLE_TYPES:
        return
    m = _models()
    if user.user_type == "IT_Support":
        ensure_admins_group()
        admins = m.PermissionGroup.objects.filter(name=ADMINS_GROUP_NAME).first()
        if admins:
            upsert_group_membership(user, admins, PERM_OWNER)
    pg = m.PermissionGroup.objects.filter(name=PUBLIC_GROUP_NAME).first()
    if pg is None:
        pg = ensure_public_group()
    if user.user_type == "IT_Support":
        upsert_group_membership(user, pg, PERM_EDIT)
    else:
        upsert_group_membership(user, pg, PERM_READ_ONLY)


def user_is_group_owner(user, pg) -> bool:
    """True if user is the personal owner or a member of the owning group (admins → public)."""
    if user is None or pg is None:
        return False
    if pg.owner_id and pg.owner_id == user.user_id:
        return True
    owner_pg_id = getattr(pg, "owner_pg_id", None)
    if not owner_pg_id:
        return False
    m = _models()
    owner_pg = m.PermissionGroup.objects.filter(pk=owner_pg_id).first()
    if owner_pg is None:
        return False
    role = get_group_membership(user, owner_pg)
    return role in (PERM_OWNER, PERM_EDIT)


def effective_group_role(user, pg) -> str | None:
    """Membership role, elevating to owner when the user owns the group (directly or via owner_pg)."""
    if user_is_group_owner(user, pg):
        return PERM_OWNER
    return get_group_membership(user, pg)


def user_can_manage_group(user, pg) -> bool:
    role = effective_group_role(user, pg)
    return role in (PERM_OWNER, PERM_EDIT)


def upsert_group_membership(user, permission_group, permissions: str):
    """Insert or update user_permission_group via raw SQL (composite PK)."""
    with connection.cursor() as c:
        c.execute(
            """
            INSERT INTO user_permission_group (user_id, pg_id, permissions)
            VALUES (%s, %s, %s::users_group_permission)
            ON CONFLICT (user_id, pg_id)
            DO UPDATE SET permissions = EXCLUDED.permissions
            """,
            [user.user_id, permission_group.id, permissions],
        )


def delete_group_membership(user, permission_group):
    with connection.cursor() as c:
        c.execute(
            "DELETE FROM user_permission_group WHERE user_id = %s AND pg_id = %s",
            [user.user_id, permission_group.id],
        )


def get_group_membership(user, permission_group):
    with connection.cursor() as c:
        c.execute(
            "SELECT permissions::text FROM user_permission_group WHERE user_id = %s AND pg_id = %s",
            [user.user_id, permission_group.id],
        )
        row = c.fetchone()
    return row[0] if row else None


def list_group_memberships_for_user(user, *, include_public: bool = True):
    """Named Manage Groups memberships (excludes auto-created per-branch Share: markers)."""
    sql = """
        SELECT upg.pg_id, upg.permissions::text, pg.name, pg.owner_id,
               pg.owner_pg_id, COALESCE(pg.system_protected, false)
        FROM user_permission_group upg
        JOIN permission_group pg ON pg.id = upg.pg_id
        WHERE upg.user_id = %s
          AND NOT EXISTS (
              SELECT 1 FROM branch_group bg WHERE bg.share_group_id = pg.id
          )
          AND pg.name NOT LIKE 'Share: %%'
    """
    params = [user.user_id]
    if not include_public:
        sql += " AND pg.name <> %s"
        params.append(PUBLIC_GROUP_NAME)
    sql += " ORDER BY pg.name"
    with connection.cursor() as c:
        c.execute(sql, params)
        rows = c.fetchall()
    out = []
    for r in rows:
        name = r[2]
        out.append(
            {
                "pg_id": r[0],
                "permissions": r[1],
                "name": name,
                "owner_id": r[3],
                "owner_pg_id": r[4],
                "system_protected": bool(r[5]),
                "is_public": name == PUBLIC_GROUP_NAME,
                "is_admins": name == ADMINS_GROUP_NAME,
                "is_system": name in SYSTEM_GROUP_NAMES or bool(r[5]),
            }
        )
    return out


def list_group_members(permission_group, *, viewer):
    """Member list with public / system-group visibility rules."""
    is_public = permission_group.name == PUBLIC_GROUP_NAME
    is_admins = permission_group.name == ADMINS_GROUP_NAME
    owner_id = permission_group.owner_id
    viewer_is_owner = user_is_group_owner(viewer, permission_group)

    with connection.cursor() as c:
        c.execute(
            """
            SELECT upg.user_id, upg.permissions::text,
                   u.username, u.user_email, u.user_first_name, u.user_last_name,
                   u.organization, u.user_type
            FROM user_permission_group upg
            JOIN user_profile u ON u.user_id = upg.user_id
            WHERE upg.pg_id = %s
            ORDER BY upg.permissions::text, u.username
            """,
            [permission_group.id],
        )
        rows = c.fetchall()

    members = []
    for r in rows:
        uid, perm, username, email, first, last, org, utype = r
        if is_public:
            if not viewer_is_owner:
                # Non-owners of public (Teachers): hide the membership roster.
                continue
            # Admins owning public: show edit IT members; hide read_only Teachers.
            if perm == PERM_READ_ONLY:
                continue
        members.append(
            {
                "user_id": uid,
                "permissions": perm,
                "username": username,
                "email": email,
                "first_name": first,
                "last_name": last,
                "organization": org,
                "user_type": utype,
                "is_owner": (
                    (owner_id is not None and uid == owner_id)
                    or (is_admins and perm == PERM_OWNER)
                ),
            }
        )
    return members


def list_subgroup_children(parent_pg_id):
    with connection.cursor() as c:
        c.execute(
            """
            SELECT s.child_pg_id, s.permissions::text, pg.name, pg.owner_id
            FROM permission_group_subgroup s
            JOIN permission_group pg ON pg.id = s.child_pg_id
            WHERE s.parent_pg_id = %s
            ORDER BY pg.name
            """,
            [parent_pg_id],
        )
        return [
            {
                "pg_id": r[0],
                "permissions": r[1],
                "name": r[2],
                "owner_id": r[3],
            }
            for r in c.fetchall()
        ]


def list_subgroup_edges():
    """All nesting edges as (parent_id, child_id, permissions)."""
    with connection.cursor() as c:
        c.execute(
            """
            SELECT parent_pg_id, child_pg_id, permissions::text
            FROM permission_group_subgroup
            """
        )
        return [(r[0], r[1], r[2]) for r in c.fetchall()]


def descendant_group_ids(root_pg_id) -> set[int]:
    """All nested descendants of root (not including root). Cycle-safe."""
    children_map = {}
    for parent_id, child_id, _perm in list_subgroup_edges():
        children_map.setdefault(parent_id, []).append(child_id)
    out = set()
    stack = list(children_map.get(root_pg_id, []))
    while stack:
        nid = stack.pop()
        if nid in out:
            continue
        out.add(nid)
        stack.extend(children_map.get(nid, []))
    return out


def ancestor_group_ids(pg_ids) -> set[int]:
    """All ancestor groups of the given ids (not including the seeds). Cycle-safe."""
    parents_map = {}
    for parent_id, child_id, _perm in list_subgroup_edges():
        parents_map.setdefault(child_id, []).append(parent_id)
    out = set()
    stack = list(pg_ids)
    seen = set(pg_ids)
    while stack:
        nid = stack.pop()
        for parent_id in parents_map.get(nid, []):
            if parent_id in seen:
                continue
            seen.add(parent_id)
            out.add(parent_id)
            stack.append(parent_id)
    return out


def would_create_subgroup_cycle(parent_pg_id, child_pg_id) -> bool:
    if parent_pg_id == child_pg_id:
        return True
    # Nesting child under parent is illegal if parent is already under child.
    return parent_pg_id in descendant_group_ids(child_pg_id)


def upsert_subgroup(parent_pg_id, child_pg_id, permissions: str):
    with connection.cursor() as c:
        c.execute(
            """
            INSERT INTO permission_group_subgroup (parent_pg_id, child_pg_id, permissions)
            VALUES (%s, %s, %s::users_group_permission)
            ON CONFLICT (parent_pg_id, child_pg_id)
            DO UPDATE SET permissions = EXCLUDED.permissions
            """,
            [parent_pg_id, child_pg_id, permissions],
        )


def delete_subgroup(parent_pg_id, child_pg_id):
    with connection.cursor() as c:
        c.execute(
            """
            DELETE FROM permission_group_subgroup
            WHERE parent_pg_id = %s AND child_pg_id = %s
            """,
            [parent_pg_id, child_pg_id],
        )


def user_access_via_group(user_id, root_pg_id, branch_grant: str) -> str | None:
    """
    Access a user gets from a branch grant on root_pg, expanding nested subgroups.

    Direct members of the root get the full branch grant (historical behavior).
    Nested members get min(branch_grant, edge permissions along the path).
    Across multiple paths, the highest edit/read_only wins.
    """
    if not branch_grant:
        return None
    top = PERM_EDIT if branch_grant == PERM_OWNER else branch_grant
    if top not in (PERM_EDIT, PERM_READ_ONLY):
        return None

    edges = list_subgroup_edges()
    children_map = {}
    for parent_id, child_id, edge_perm in edges:
        children_map.setdefault(parent_id, []).append((child_id, edge_perm))

    best = None
    with connection.cursor() as c:
        c.execute(
            "SELECT 1 FROM user_permission_group WHERE user_id = %s AND pg_id = %s",
            [user_id, root_pg_id],
        )
        if c.fetchone():
            best = top

        # BFS: (group_id, path_cap after entering that group via an edge)
        queue = deque()
        for child_id, edge_perm in children_map.get(root_pg_id, []):
            queue.append((child_id, min_access(top, edge_perm)))
        seen = {root_pg_id}

        while queue:
            pg_id, path_cap = queue.popleft()
            if pg_id in seen or not path_cap:
                continue
            seen.add(pg_id)
            c.execute(
                "SELECT 1 FROM user_permission_group WHERE user_id = %s AND pg_id = %s",
                [user_id, pg_id],
            )
            if c.fetchone():
                best = max_perm(best, path_cap)
            for child_id, edge_perm in children_map.get(pg_id, []):
                if child_id not in seen:
                    queue.append((child_id, min_access(path_cap, edge_perm)))
    return best


def expand_group_member_user_ids(root_pg_id) -> set[int]:
    """Direct + nested subgroup member user ids under root."""
    ids = {root_pg_id} | descendant_group_ids(root_pg_id)
    with connection.cursor() as c:
        c.execute(
            """
            SELECT DISTINCT user_id FROM user_permission_group
            WHERE pg_id = ANY(%s)
            """,
            [list(ids)],
        )
        return {r[0] for r in c.fetchall()}


def group_ids_for_user_branch_lookup(user) -> list[int]:
    """Groups that can grant the user branch access: direct memberships + ancestors."""
    with connection.cursor() as c:
        c.execute(
            "SELECT pg_id FROM user_permission_group WHERE user_id = %s",
            [user.user_id],
        )
        direct = [r[0] for r in c.fetchall()]
    return list(set(direct) | ancestor_group_ids(direct))


def group_has_non_owner_content(pg) -> bool:
    """True if group has any non-owner user member or any nested subgroup."""
    if is_system_group(pg):
        return True
    with connection.cursor() as c:
        if pg.owner_id is not None:
            c.execute(
                """
                SELECT 1 FROM user_permission_group
                WHERE pg_id = %s AND user_id <> %s
                LIMIT 1
                """,
                [pg.id, pg.owner_id],
            )
        else:
            c.execute(
                """
                SELECT 1 FROM user_permission_group
                WHERE pg_id = %s
                LIMIT 1
                """,
                [pg.id],
            )
        if c.fetchone():
            return True
        c.execute(
            "SELECT 1 FROM permission_group_subgroup WHERE parent_pg_id = %s LIMIT 1",
            [pg.id],
        )
        return bool(c.fetchone())


def delete_permission_group(pg):
    """Remove a named group and all memberships / nesting / branch ACL grants for it."""
    if is_system_group(pg):
        raise RuntimeError(f"Cannot delete system group '{pg.name}'.")
    with connection.cursor() as c:
        c.execute(
            "UPDATE branch_group SET share_group_id = NULL WHERE share_group_id = %s",
            [pg.id],
        )
        c.execute(
            """
            DELETE FROM users_group
            WHERE permission_group = %s AND user_id IS NULL
            """,
            [pg.id],
        )
        c.execute("DELETE FROM user_permission_group WHERE pg_id = %s", [pg.id])
        c.execute(
            """
            DELETE FROM permission_group_subgroup
            WHERE parent_pg_id = %s OR child_pg_id = %s
            """,
            [pg.id, pg.id],
        )
    pg.delete()


def cleanup_empty_owned_groups(user) -> list[str]:
    """
    Delete groups owned by user that have no members besides the owner and no subgroups.
    Skips system-protected groups (admins, public) and auto Share: markers.
    Returns deleted group names.
    """
    m = _models()
    deleted = []
    owned = list(m.PermissionGroup.objects.filter(owner=user))
    for pg in owned:
        if is_system_group(pg):
            continue
        if (pg.name or "").startswith("Share: "):
            continue
        if group_has_non_owner_content(pg):
            continue
        name = pg.name
        delete_permission_group(pg)
        deleted.append(name)
    return deleted


def workspace_folder(user):
    m = _models()
    root = m.BranchGroup.objects.filter(owner=user, parent__isnull=True).first()
    if not root:
        return None
    return m.BranchGroup.objects.filter(
        owner=user, parent=root, name=FOLDER_WORKSPACE
    ).first()


def trash_folder(user):
    m = _models()
    root = m.BranchGroup.objects.filter(owner=user, parent__isnull=True).first()
    if not root:
        return None
    return m.BranchGroup.objects.filter(
        owner=user, parent=root, name=FOLDER_TRASH
    ).first()


def collaboration_folder(user):
    m = _models()
    root = m.BranchGroup.objects.filter(owner=user, parent__isnull=True).first()
    if not root:
        return None
    return m.BranchGroup.objects.filter(
        owner=user, parent=root, name=FOLDER_COLLABORATION
    ).first()


def public_library_folder(user):
    m = _models()
    root = m.BranchGroup.objects.filter(owner=user, parent__isnull=True).first()
    if not root:
        return None
    return m.BranchGroup.objects.filter(
        owner=user, parent=root, name=FOLDER_PUBLIC_LIBRARY
    ).first()



def list_branch_acl(branch_id):
    with connection.cursor() as c:
        c.execute(
            """
            SELECT user_id, permission_group, permissions::text
            FROM users_group WHERE branch_id = %s
            """,
            [branch_id],
        )
        return [
            {"user_id": r[0], "permission_group_id": r[1], "permissions": r[2]}
            for r in c.fetchall()
        ]


def list_branches_acl(branch_ids):
    """ACL rows for many branches: {branch_id: [row, ...]}."""
    ids = [int(i) for i in branch_ids if i is not None]
    out = {i: [] for i in ids}
    if not ids:
        return out
    with connection.cursor() as c:
        c.execute(
            """
            SELECT branch_id, user_id, permission_group, permissions::text
            FROM users_group WHERE branch_id = ANY(%s)
            """,
            [ids],
        )
        for branch_id, user_id, pg_id, perm in c.fetchall():
            out.setdefault(branch_id, []).append(
                {"user_id": user_id, "permission_group_id": pg_id, "permissions": perm}
            )
    return out


def branch_acl_rows(branch):
    return list_branch_acl(branch.id)


def _ancestor_branch_chain(branch):
    """
    ``branch`` then parents up to the user root (inclusive).
    Does not create ACL rows — used only for inherited permission lookup.
    """
    if branch is None:
        return []
    m = _models()
    chain = []
    current = branch
    seen = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        chain.append(current)
        parent_id = current.parent_id
        if not parent_id:
            break
        current = (
            m.BranchGroup.objects.filter(pk=parent_id)
            .only("id", "owner", "parent_id", "share_group_id", "name")
            .first()
        )
    return chain


def _perm_from_acl_rows_for_user(user, rows) -> str | None:
    perms = []
    for row in rows or []:
        if row.get("user_id") == user.user_id:
            perms.append(row.get("permissions"))
        elif row.get("permission_group_id"):
            via = user_access_via_group(
                user.user_id, row["permission_group_id"], row.get("permissions")
            )
            if via:
                perms.append(via)
    return max_perm(*perms)


def effective_permission(user, branch) -> str | None:
    """
    Highest ACL for ``user`` on ``branch``, inheriting from ancestors.

    Grants live only on the shared ancestor (typically the share root). Descendants
    do not get duplicated ``users_group`` rows — access is resolved by walking
    parents while those ancestor grants still exist.
    """
    if branch is None or user is None:
        return None
    if branch.owner_id == user.user_id:
        return PERM_OWNER

    chain = _ancestor_branch_chain(branch)
    if not chain:
        return None

    for node in chain:
        if node.owner_id == user.user_id:
            return PERM_OWNER

    acl_by_id = list_branches_acl([n.id for n in chain])
    perms = []
    for node in chain:
        got = _perm_from_acl_rows_for_user(user, acl_by_id.get(node.id))
        if got:
            perms.append(got)
    return max_perm(*perms)


def can_edit_branch(user, branch) -> bool:
    p = effective_permission(user, branch)
    return PERM_RANK.get(p or "", 0) >= PERM_RANK[PERM_EDIT]


def can_read_branch(user, branch) -> bool:
    return effective_permission(user, branch) is not None


def share_root_has_non_owner_collaborators(branch) -> bool:
    for row in list_branch_acl(branch.id):
        if row["user_id"] and row["user_id"] != branch.owner_id:
            return True
        if row["permission_group_id"]:
            return True
    return False


def find_same_name_type_sibling(dest, src):
    """Sibling under ``dest`` with the same display name and folder_type as ``src``."""
    if dest is None or src is None:
        return None
    m = _models()
    return (
        m.BranchGroup.objects.filter(
            parent=dest,
            name=src.name,
            folder_type=src.folder_type,
        )
        .exclude(pk=src.pk)
        .first()
    )


def snapshot_branch_acl(branch) -> dict:
    return {
        "rows": list_branch_acl(branch.id),
        "share_group_id": getattr(branch, "share_group_id", None),
    }


def restore_branch_acl(branch, snapshot: dict | None):
    if not snapshot:
        return
    for row in snapshot.get("rows") or []:
        if row.get("user_id"):
            upsert_user_acl(branch.id, row["user_id"], row.get("permissions") or PERM_READ_ONLY)
        elif row.get("permission_group_id"):
            upsert_group_acl(
                branch.id,
                row["permission_group_id"],
                row.get("permissions") or PERM_READ_ONLY,
            )
    share_group_id = snapshot.get("share_group_id")
    if share_group_id:
        branch.share_group_id = share_group_id
        branch.save(update_fields=["share_group"])


def hard_delete_branch_tree(branch):
    """Permanently delete a branch and its descendants (depth-first)."""
    m = _models()
    for child in list(m.BranchGroup.objects.filter(parent=branch)):
        hard_delete_branch_tree(child)
    # Drop share_group link first so the permission_group row is not blocked.
    if getattr(branch, "share_group_id", None):
        branch.share_group = None
        branch.save(update_fields=["share_group"])
    branch.delete()


def replace_name_conflict_message(src, conflict) -> str:
    kind = (src.folder_type or "item").replace("_", " ")
    return (
        f'A {kind} named “{src.name}” already exists as a sibling in this folder. '
        "Delete and replace it with your copy? Collaboration permissions on the "
        "existing item (if any) will be kept on the replacement. Your Workspace "
        "original is unchanged."
    )


def branch_is_in_shared_subtree(branch) -> bool:
    """True if this branch or an ancestor is a share root with collaborators / share_group."""
    for node in _ancestor_branch_chain(branch):
        if getattr(node, "share_group_id", None):
            return True
        if share_root_has_non_owner_collaborators(node):
            return True
    return False


def shared_branch_id_set(branch_ids) -> set[int]:
    """Return ids among ``branch_ids`` that currently have non-owner collaborator ACL."""
    ids = [int(i) for i in branch_ids if i is not None]
    if not ids:
        return set()
    m = _models()
    owner_by_id = {
        b.id: b.owner_id
        for b in m.BranchGroup.objects.filter(id__in=ids).only("id", "owner")
    }
    shared = set()
    with connection.cursor() as c:
        c.execute(
            """
            SELECT branch_id, user_id, permission_group
            FROM users_group
            WHERE branch_id = ANY(%s)
            """,
            [ids],
        )
        for branch_id, user_id, permission_group_id in c.fetchall():
            owner_id = owner_by_id.get(branch_id)
            if permission_group_id:
                shared.add(branch_id)
            elif user_id and user_id != owner_id:
                shared.add(branch_id)
    return shared


def collaboration_share_roots_for_user(user):
    """Virtual Collaboration listing: non-public share roots user can access with ≥1 non-owner collab."""
    m = _models()
    Public = m.PermissionGroup.objects.filter(name=PUBLIC_GROUP_NAME).first()
    public_id = Public.id if Public else None

    member_pg_ids = group_ids_for_user_branch_lookup(user)

    with connection.cursor() as c:
        if member_pg_ids:
            c.execute(
                """
                SELECT DISTINCT branch_id FROM users_group
                WHERE user_id = %s OR permission_group = ANY(%s)
                """,
                [user.user_id, member_pg_ids],
            )
        else:
            c.execute(
                "SELECT DISTINCT branch_id FROM users_group WHERE user_id = %s",
                [user.user_id],
            )
        branch_ids = {r[0] for r in c.fetchall()}

        # Owners may lack a self ACL row on older shares; still list owned collab roots.
        c.execute(
            """
            SELECT DISTINCT bg.id
            FROM branch_group bg
            JOIN users_group ug ON ug.branch_id = bg.id
            WHERE bg.owner = %s
              AND (
                (ug.user_id IS NOT NULL AND ug.user_id <> bg.owner)
                OR ug.permission_group IS NOT NULL
              )
            """,
            [user.user_id],
        )
        branch_ids.update(r[0] for r in c.fetchall())

    roots = []
    for branch in m.BranchGroup.objects.filter(id__in=branch_ids).select_related("owner", "share_group"):
        rows = list_branch_acl(branch.id)
        # Public Library owns anything granted to the system "public" group.
        if public_id and any(r.get("permission_group_id") == public_id for r in rows):
            continue
        if public_id and branch.share_group_id == public_id:
            continue
        if not share_root_has_non_owner_collaborators(branch):
            continue
        if not can_read_branch(user, branch):
            continue
        roots.append(branch)
    return roots


def public_library_roots_for_user(user):
    m = _models()
    if user.user_type not in COLLAB_ELIGIBLE_TYPES:
        return []
    Public = m.PermissionGroup.objects.filter(name=PUBLIC_GROUP_NAME).first()
    if not Public:
        return []
    if not get_group_membership(user, Public):
        return []
    with connection.cursor() as c:
        c.execute(
            "SELECT branch_id FROM users_group WHERE permission_group = %s",
            [Public.id],
        )
        branch_ids = [r[0] for r in c.fetchall()]
    return list(m.BranchGroup.objects.filter(id__in=branch_ids).select_related("owner"))


def ensure_share_group_for_branch(branch, owner_user, name: str | None = None):
    """
    Legacy helper: previously created a per-branch PermissionGroup named \"Share: …\".

    Sharing now uses direct users_group ACL (and optional grants to real Manage Groups).
    Kept for any callers that still need a share_group_id marker; prefer not creating
    new auto groups for ordinary user shares.
    """
    m = _models()
    if branch.share_group_id:
        return branch.share_group
    pg = m.PermissionGroup.objects.create(
        name=name or f"Share: {branch.name}"[:255],
        owner=owner_user,
    )
    upsert_group_membership(owner_user, pg, PERM_OWNER)
    branch.share_group = pg
    branch.save(update_fields=["share_group"])
    upsert_user_acl(branch.id, owner_user.user_id, PERM_OWNER)
    return pg


def _delete_auto_share_marker_group(pg):
    """Remove an unused auto-created Share: … PermissionGroup after share_group is cleared."""
    if not pg or is_system_group(pg):
        return
    if not (pg.name or "").startswith("Share: "):
        return
    m = _models()
    if m.BranchGroup.objects.filter(share_group=pg).exists():
        return
    with connection.cursor() as c:
        c.execute(
            "SELECT 1 FROM users_group WHERE permission_group = %s LIMIT 1",
            [pg.id],
        )
        if c.fetchone():
            return
        c.execute("DELETE FROM user_permission_group WHERE pg_id = %s", [pg.id])
    pg.delete()


def upsert_user_acl(branch_id, user_id, permissions: str):
    with connection.cursor() as c:
        c.execute(
            """
            INSERT INTO users_group (branch_id, user_id, permission_group, permissions, creation_date)
            VALUES (%s, %s, NULL, %s::users_group_permission, NOW())
            ON CONFLICT (branch_id, user_id)
            DO UPDATE SET permissions = EXCLUDED.permissions
            """,
            [branch_id, user_id, permissions],
        )


def ensure_branch_owner_acl(branch):
    """Ensure the branch owner has an explicit owner row in users_group (needed for ACL UI + Collaboration listing)."""
    if not branch or not branch.owner_id:
        return
    upsert_user_acl(branch.id, branch.owner_id, PERM_OWNER)


def upsert_group_acl(branch_id, permission_group_id, permissions: str):
    # Group grants use user_id NULL; UNIQUE (branch_id, user_id) allows multiple NULLs in PG.
    with connection.cursor() as c:
        c.execute(
            """
            SELECT permissions::text FROM users_group
            WHERE branch_id = %s AND permission_group = %s AND user_id IS NULL
            """,
            [branch_id, permission_group_id],
        )
        row = c.fetchone()
        if row:
            c.execute(
                """
                UPDATE users_group SET permissions = %s::users_group_permission
                WHERE branch_id = %s AND permission_group = %s AND user_id IS NULL
                """,
                [permissions, branch_id, permission_group_id],
            )
        else:
            c.execute(
                """
                INSERT INTO users_group (branch_id, user_id, permission_group, permissions, creation_date)
                VALUES (%s, NULL, %s, %s::users_group_permission, NOW())
                """,
                [branch_id, permission_group_id, permissions],
            )


def force_upgrade_direct_acls_for_group_grant(branch, permission_group, group_branch_perm: str):
    if PERM_RANK.get(group_branch_perm, 0) < PERM_RANK[PERM_EDIT]:
        return
    target_perm = PERM_EDIT if group_branch_perm == PERM_OWNER else group_branch_perm
    member_ids = expand_group_member_user_ids(permission_group.id)
    for uid in member_ids:
        via = user_access_via_group(uid, permission_group.id, group_branch_perm)
        if via != PERM_EDIT and via != PERM_OWNER:
            continue
        with connection.cursor() as c:
            c.execute(
                """
                SELECT permissions::text FROM users_group
                WHERE branch_id = %s AND user_id = %s
                """,
                [branch.id, uid],
            )
            row = c.fetchone()
        if row and PERM_RANK.get(row[0], 0) < PERM_RANK[target_perm]:
            upsert_user_acl(branch.id, uid, target_perm)


def user_has_edit_via_group_on_branch(user, branch) -> tuple[bool, str | None]:
    m = _models()
    for row in list_branch_acl(branch.id):
        if not row["permission_group_id"]:
            continue
        if PERM_RANK.get(row["permissions"], 0) < PERM_RANK[PERM_EDIT]:
            continue
        via = user_access_via_group(
            user.user_id, row["permission_group_id"], row["permissions"]
        )
        if via in (PERM_EDIT, PERM_OWNER):
            pg = m.PermissionGroup.objects.filter(id=row["permission_group_id"]).first()
            return True, pg.name if pg else None
    return False, None


def grant_user_on_branch(branch, target_user, permissions: str, actor):
    via_edit, gname = user_has_edit_via_group_on_branch(target_user, branch)
    if via_edit and permissions == PERM_READ_ONLY:
        return {
            "ok": False,
            "error": (
                f"{target_user.username} already has edit access through group "
                f"'{gname}' and cannot be added as view-only."
            ),
            "code": "view_only_blocked",
            "group_name": gname,
        }

    with connection.cursor() as c:
        c.execute(
            "SELECT permissions::text FROM users_group WHERE branch_id = %s AND user_id = %s",
            [branch.id, target_user.user_id],
        )
        existing = c.fetchone()
    if existing:
        if PERM_RANK.get(permissions, 0) > PERM_RANK.get(existing[0], 0):
            upsert_user_acl(branch.id, target_user.user_id, permissions)
        elif permissions == PERM_READ_ONLY and PERM_RANK.get(existing[0], 0) >= PERM_RANK[PERM_EDIT]:
            return {
                "ok": False,
                "error": "User already has a higher permission on this item.",
                "code": "perm_conflict",
            }
        else:
            upsert_user_acl(branch.id, target_user.user_id, permissions)
        return {"ok": True, "created": False}

    upsert_user_acl(branch.id, target_user.user_id, permissions)
    return {"ok": True, "created": True}


def grant_group_on_branch(branch, permission_group, permissions: str):
    upsert_group_acl(branch.id, permission_group.id, permissions)
    force_upgrade_direct_acls_for_group_grant(branch, permission_group, permissions)
    return {"ok": True}


def unshare_branch(branch, owner_user):
    """Remove all collaborator ACL except owner."""
    removed_user_ids = set()
    rows = list_branch_acl(branch.id)
    with connection.cursor() as c:
        for row in rows:
            if row["user_id"] == owner_user.user_id and row["permissions"] == PERM_OWNER:
                continue
            if row["user_id"]:
                removed_user_ids.add(row["user_id"])
                c.execute(
                    "DELETE FROM users_group WHERE branch_id = %s AND user_id = %s",
                    [branch.id, row["user_id"]],
                )
            elif row["permission_group_id"]:
                for uid in expand_group_member_user_ids(row["permission_group_id"]):
                    if uid != owner_user.user_id:
                        removed_user_ids.add(uid)
                c.execute(
                    """
                    DELETE FROM users_group
                    WHERE branch_id = %s AND permission_group = %s AND user_id IS NULL
                    """,
                    [branch.id, row["permission_group_id"]],
                )
    upsert_user_acl(branch.id, owner_user.user_id, PERM_OWNER)
    if branch.share_group_id:
        pg = branch.share_group
        branch.share_group = None
        branch.save(update_fields=["share_group"])
        _delete_auto_share_marker_group(pg)
    return removed_user_ids


def revoke_branch_collaborator(branch, *, kind: str, user_id=None, permission_group_id=None, actor):
    """
    Remove one user or group grant from a branch ACL.
    Returns (removed_user_ids_for_notify, error_message_or_None).
    """
    if kind == "user":
        if not user_id:
            return set(), "Missing user_id."
        if user_id == branch.owner_id:
            return set(), "Cannot remove the owner."
        with connection.cursor() as c:
            c.execute(
                "SELECT permissions::text FROM users_group WHERE branch_id = %s AND user_id = %s",
                [branch.id, user_id],
            )
            row = c.fetchone()
            if not row:
                return set(), "User is not on this item's share list."
            if row[0] == PERM_OWNER:
                return set(), "Cannot remove the owner."
            c.execute(
                "DELETE FROM users_group WHERE branch_id = %s AND user_id = %s",
                [branch.id, user_id],
            )
        _clear_share_group_if_no_collaborators(branch)
        return {user_id}, None

    if kind == "group":
        if not permission_group_id:
            return set(), "Missing group id."
        found = False
        removed = set()
        with connection.cursor() as c:
            for row in list_branch_acl(branch.id):
                if row["permission_group_id"] == permission_group_id:
                    found = True
                    if row["permissions"] == PERM_OWNER:
                        return set(), "Cannot remove an owner grant."
                    break
            if not found:
                return set(), "Group is not on this item's share list."
            removed = {
                uid
                for uid in expand_group_member_user_ids(permission_group_id)
                if uid != branch.owner_id
            }
            c.execute(
                """
                DELETE FROM users_group
                WHERE branch_id = %s AND permission_group = %s AND user_id IS NULL
                """,
                [branch.id, permission_group_id],
            )
        _clear_share_group_if_no_collaborators(branch)
        return removed, None

    return set(), "Unknown kind."


def _clear_share_group_if_no_collaborators(branch):
    """When nobody else has ACL access, drop share-root status (leaves Workspace only)."""
    if share_root_has_non_owner_collaborators(branch):
        return
    if branch.share_group_id:
        pg = branch.share_group
        branch.share_group = None
        branch.save(update_fields=["share_group"])
        _delete_auto_share_marker_group(pg)


def move_share_roots_to_workspace(permission_group, new_owner):
    """On ownership transfer: move share-root trees into new owner's Workspace.

    System groups (public / admins) are never relocated into a personal Workspace —
    Public Library lists the actual shared branch rows via ACL, not a local copy.
    """
    if is_system_group(permission_group):
        return
    m = _models()
    dest = workspace_folder(new_owner)
    if not dest:
        raise RuntimeError("New owner has no Workspace folder.")
    roots = m.BranchGroup.objects.filter(share_group=permission_group)
    for root in roots:
        root.parent = dest
        root.owner = new_owner
        # Also re-owner descendants
        root.save(update_fields=["parent", "owner"])
        _reassign_subtree_owner(root, new_owner)


def _reassign_subtree_owner(node, new_owner):
    m = _models()
    children = list(m.BranchGroup.objects.filter(parent=node))
    for child in children:
        if child.owner_id != new_owner.user_id:
            child.owner = new_owner
            child.save(update_fields=["owner"])
        _reassign_subtree_owner(child, new_owner)


def notify_share_event(receiver, *, title, content, sender=None):
    return create_notification(
        receiver,
        title=title,
        content=content,
        reason="collaboration",
        sender=sender,
    )


def search_collab_users(query: str, *, exclude_user_id=None, limit=20):
    m = _models()
    q = (query or "").strip()
    if not q:
        return []
    qs = m.UserProfile.objects.filter(
        user_type__in=COLLAB_ELIGIBLE_TYPES
    ).filter(Q(username__icontains=q) | Q(user_email__icontains=q))
    if exclude_user_id:
        qs = qs.exclude(user_id=exclude_user_id)
    results = []
    for u in qs.order_by("username")[:limit]:
        results.append(
            {
                "user_id": u.user_id,
                "username": u.username,
                "email": u.user_email,
                "first_name": u.user_first_name,
                "last_name": u.user_last_name,
                "organization": u.organization,
                "user_type": u.user_type,
            }
        )
    return results


def purge_expired_trashed_branches() -> int:
    """Hard-delete trash roots with trashed_at older than retention."""
    m = _models()
    cutoff = timezone.now() - TRASH_RETENTION
    trash_parents = m.BranchGroup.objects.filter(name=FOLDER_TRASH, parent__isnull=False)
    deleted = 0
    for trash in trash_parents:
        stale = list(
            m.BranchGroup.objects.filter(parent=trash, trashed_at__lt=cutoff)
        )
        for node in stale:
            node.delete()  # CASCADE children via FK if configured
            deleted += 1
    return deleted
