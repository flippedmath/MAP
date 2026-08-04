"""JSON/HTML endpoints for Collaboration Manage Groups, Share, Copy, Move."""

from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.db import connection, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from .collaboration import (
    ADMINS_GROUP_NAME,
    PERM_EDIT,
    PERM_OWNER,
    PERM_READ_ONLY,
    PUBLIC_GROUP_NAME,
    SYSTEM_GROUP_NAMES,
    branch_is_in_shared_subtree,
    can_edit_branch,
    can_read_branch,
    cleanup_empty_owned_groups,
    delete_group_membership,
    delete_permission_group,
    delete_subgroup,
    effective_group_role,
    effective_permission,
    ensure_branch_owner_acl,
    expand_group_member_user_ids,
    find_same_name_type_sibling,
    get_group_membership,
    grant_group_on_branch,
    grant_user_on_branch,
    group_has_non_owner_content,
    hard_delete_branch_tree,
    is_system_group,
    list_branch_acl,
    list_group_members,
    list_group_memberships_for_user,
    list_subgroup_children,
    move_share_roots_to_workspace,
    notify_share_event,
    replace_name_conflict_message,
    restore_branch_acl,
    search_collab_users,
    share_root_has_non_owner_collaborators,
    snapshot_branch_acl,
    unshare_branch,
    upsert_group_acl,
    upsert_group_membership,
    upsert_subgroup,
    upsert_user_acl,
    user_can_manage_group,
    user_has_edit_via_group_on_branch,
    user_is_group_owner,
    workspace_folder,
    would_create_subgroup_cycle,
    revoke_branch_collaborator,
)
from .course_lifecycle import apply_course_status
from .folder_roots import (
    FOLDER_COLLABORATION,
    branch_is_under_courses,
    is_courses_root_folder,
)
from .models import BranchGroup, PermissionGroup, UserProfile
from .util import (
    clone_node_recursive,
    get_branch_related,
    get_valid_unique_name,
    resolve_unique_sibling_name,
    sync_branch_payload_parent_links,
)


def _require_teacher_or_it(user):
    return getattr(user, "user_type", None) in ("Teacher", "IT_Support")


def _credit_collab_denied(user):
    """Return an error message if the user cannot use private collab groups."""
    from .credits import CreditError, assert_can_use_collab_groups

    try:
        assert_can_use_collab_groups(user)
    except CreditError as exc:
        return str(exc)
    return None


def _serialize_branch_acl(branch_id):
    acl = []
    for row in list_branch_acl(branch_id):
        username = None
        pg_name = None
        if row["user_id"]:
            u = UserProfile.objects.filter(user_id=row["user_id"]).first()
            username = u.username if u else None
        if row["permission_group_id"]:
            pg = PermissionGroup.objects.filter(id=row["permission_group_id"]).first()
            pg_name = pg.name if pg else None
        acl.append(
            {
                "user_id": row["user_id"],
                "username": username,
                "permission_group_id": row["permission_group_id"],
                "permission_group_name": pg_name,
                "permissions": row["permissions"],
            }
        )
    return acl


@login_required
@require_GET
def manage_groups_data(request):
    if not _require_teacher_or_it(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    groups = list_group_memberships_for_user(request.user, include_public=True)
    return JsonResponse({"groups": groups})


@login_required
@require_GET
def manage_group_detail(request, pg_id):
    if not _require_teacher_or_it(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    pg = get_object_or_404(PermissionGroup, id=pg_id)
    my_role = effective_group_role(request.user, pg)
    if not my_role:
        return JsonResponse({"error": "Not a member of this group."}, status=403)
    members = list_group_members(pg, viewer=request.user)
    subgroups = (
        list_subgroup_children(pg.id) if not is_system_group(pg) else []
    )
    return JsonResponse(
        {
            "id": pg.id,
            "name": pg.name,
            "owner_id": pg.owner_id,
            "owner_pg_id": getattr(pg, "owner_pg_id", None),
            "is_public": pg.name == PUBLIC_GROUP_NAME,
            "is_admins": pg.name == ADMINS_GROUP_NAME,
            "is_system": is_system_group(pg),
            "system_protected": bool(getattr(pg, "system_protected", False)),
            "my_role": my_role,
            "members": members,
            "subgroups": subgroups,
            "has_non_owner_content": group_has_non_owner_content(pg),
        }
    )


@login_required
@require_POST
def manage_group_create(request):
    if not _require_teacher_or_it(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    denied = _credit_collab_denied(request.user)
    if denied:
        return JsonResponse({"error": denied}, status=403)
    data = json.loads(request.body)
    name = (data.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "Group name is required."}, status=400)
    if name.lower() in {n.lower() for n in SYSTEM_GROUP_NAMES}:
        return JsonResponse({"error": "That group name is reserved."}, status=400)
    pg = PermissionGroup.objects.create(name=name, owner=request.user)
    upsert_group_membership(request.user, pg, PERM_OWNER)
    return JsonResponse({"ok": True, "id": pg.id, "name": pg.name})


@login_required
@require_POST
def manage_group_add_member(request, pg_id):
    if not _require_teacher_or_it(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    pg = get_object_or_404(PermissionGroup, id=pg_id)
    if not user_can_manage_group(request.user, pg):
        return JsonResponse({"error": "Need edit or owner to add members."}, status=403)
    data = json.loads(request.body)
    user_id = data.get("user_id")
    role = data.get("permissions") or PERM_READ_ONLY
    if role not in (PERM_EDIT, PERM_READ_ONLY):
        return JsonResponse({"error": "Invalid role."}, status=400)
    target = get_object_or_404(UserProfile, user_id=user_id)
    if target.user_type not in ("Teacher", "IT_Support"):
        return JsonResponse({"error": "Only Teachers and IT Support can join groups."}, status=400)
    # Public Library / system groups stay available; private groups need unlock.
    if not is_system_group(pg):
        denied = _credit_collab_denied(target)
        if denied:
            return JsonResponse({"error": denied}, status=403)
    existing = get_group_membership(target, pg)
    only_if_new = bool(data.get("only_if_new"))
    if existing and only_if_new:
        return JsonResponse(
            {"ok": True, "already_member": True, "permissions": existing, "user_id": target.user_id}
        )
    # System groups are auto-enrolled; never create new memberships manually.
    if is_system_group(pg) and not existing:
        return JsonResponse(
            {
                "error": (
                    f"Cannot manually add members to the '{pg.name}' group; "
                    "it is system-managed."
                )
            },
            status=400,
        )
    upsert_group_membership(target, pg, role)
    note = (data.get("note") or "").strip()
    content = {
        "group": pg.name,
        "permissions": role,
        "note": note,
        "added_by": request.user.username,
    }
    notify_share_event(
        target,
        title=f"Added to collaboration group '{pg.name}'",
        content=content,
        sender=request.user,
    )
    return JsonResponse({"ok": True})


@login_required
@require_POST
def manage_group_remove_member(request, pg_id):
    if not _require_teacher_or_it(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    pg = get_object_or_404(PermissionGroup, id=pg_id)
    data = json.loads(request.body)
    user_id = data.get("user_id")
    target = get_object_or_404(UserProfile, user_id=user_id)
    my_role = effective_group_role(request.user, pg)
    self_leave = target.user_id == request.user.user_id

    if is_system_group(pg):
        if self_leave:
            return JsonResponse(
                {"error": f"Cannot leave the '{pg.name}' group."}, status=400
            )
        return JsonResponse(
            {
                "error": (
                    f"Cannot remove members from the '{pg.name}' group; "
                    "it is system-managed."
                )
            },
            status=400,
        )
    if target.user_id == pg.owner_id or user_is_group_owner(target, pg):
        return JsonResponse({"error": "Cannot remove the group owner."}, status=400)

    if self_leave:
        if my_role == PERM_OWNER:
            return JsonResponse({"error": "Transfer ownership before leaving."}, status=400)
    else:
        if not user_can_manage_group(request.user, pg):
            return JsonResponse({"error": "Need edit or owner to remove members."}, status=403)

    delete_group_membership(target, pg)
    notify_share_event(
        target,
        title=f"Removed from collaboration group '{pg.name}'",
        content={"group": pg.name, "removed_by": request.user.username},
        sender=request.user,
    )
    return JsonResponse({"ok": True})


@login_required
@require_POST
def manage_group_transfer_owner(request, pg_id):
    if not _require_teacher_or_it(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    pg = get_object_or_404(PermissionGroup, id=pg_id)
    if is_system_group(pg):
        return JsonResponse(
            {"error": f"Cannot transfer ownership of the '{pg.name}' group."},
            status=400,
        )
    if not user_is_group_owner(request.user, pg):
        return JsonResponse({"error": "Only the owner can transfer ownership."}, status=403)
    data = json.loads(request.body)
    new_owner = get_object_or_404(UserProfile, user_id=data.get("user_id"))
    if get_group_membership(new_owner, pg) != PERM_EDIT:
        return JsonResponse({"error": "New owner must currently have edit access."}, status=400)
    with transaction.atomic():
        old = request.user
        pg.owner = new_owner
        pg.save(update_fields=["owner"])
        upsert_group_membership(new_owner, pg, PERM_OWNER)
        upsert_group_membership(old, pg, PERM_EDIT)
        move_share_roots_to_workspace(pg, new_owner)
    notify_share_event(
        new_owner,
        title=f"You are now owner of '{pg.name}'",
        content={
            "group": pg.name,
            "message": "Shared files for this group were moved into your Workspace.",
        },
        sender=old,
    )
    notify_share_event(
        old,
        title=f"Ownership of '{pg.name}' transferred",
        content={
            "group": pg.name,
            "new_owner": new_owner.username,
            "message": "Core shared files were moved to the new owner's Workspace.",
        },
        sender=old,
    )
    return JsonResponse({"ok": True})


@login_required
@require_POST
def manage_group_add_subgroup(request, pg_id):
    if not _require_teacher_or_it(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    parent = get_object_or_404(PermissionGroup, id=pg_id)
    if is_system_group(parent):
        return JsonResponse(
            {"error": f"Cannot add subgroups to the '{parent.name}' group."},
            status=400,
        )
    if not user_can_manage_group(request.user, parent):
        return JsonResponse({"error": "Need edit or owner to add subgroups."}, status=403)
    data = json.loads(request.body)
    child_id = data.get("child_pg_id")
    role = data.get("permissions") or PERM_READ_ONLY
    if role not in (PERM_EDIT, PERM_READ_ONLY):
        return JsonResponse({"error": "Invalid role."}, status=400)
    child = get_object_or_404(PermissionGroup, id=child_id)
    if is_system_group(child):
        return JsonResponse(
            {"error": f"Cannot nest the '{child.name}' group."}, status=400
        )
    if (child.name or "").startswith("Share: "):
        return JsonResponse({"error": "Cannot nest system share marker groups."}, status=400)
    if not get_group_membership(request.user, child) and not user_is_group_owner(
        request.user, child
    ):
        return JsonResponse({"error": "You must be a member of the subgroup to add it."}, status=403)
    if would_create_subgroup_cycle(parent.id, child.id):
        return JsonResponse(
            {
                "error": "Cannot add a group to itself or to one of its own subgroups.",
                "code": "subgroup_cycle",
            },
            status=400,
        )
    existing = [s for s in list_subgroup_children(parent.id) if s["pg_id"] == child.id]
    only_if_new = bool(data.get("only_if_new"))
    if existing and only_if_new:
        return JsonResponse(
            {
                "ok": True,
                "already_member": True,
                "permissions": existing[0]["permissions"],
                "child_pg_id": child.id,
            }
        )
    upsert_subgroup(parent.id, child.id, role)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def manage_group_remove_subgroup(request, pg_id):
    if not _require_teacher_or_it(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    parent = get_object_or_404(PermissionGroup, id=pg_id)
    if not user_can_manage_group(request.user, parent):
        return JsonResponse({"error": "Need edit or owner to remove subgroups."}, status=403)
    data = json.loads(request.body)
    child_id = data.get("child_pg_id")
    if not child_id:
        return JsonResponse({"error": "Missing child_pg_id."}, status=400)
    delete_subgroup(parent.id, child_id)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def manage_group_delete(request, pg_id):
    if not _require_teacher_or_it(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    pg = get_object_or_404(PermissionGroup, id=pg_id)
    if is_system_group(pg):
        return JsonResponse(
            {"error": f"Cannot delete the '{pg.name}' group."}, status=400
        )
    if not user_is_group_owner(request.user, pg):
        return JsonResponse({"error": "Only the owner can delete this group."}, status=403)
    name = pg.name
    delete_permission_group(pg)
    return JsonResponse({"ok": True, "deleted": name})


@login_required
@require_POST
def manage_groups_cleanup_empty(request):
    if not _require_teacher_or_it(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    deleted = cleanup_empty_owned_groups(request.user)
    return JsonResponse({"ok": True, "deleted": deleted})


@login_required
@require_GET
def collab_user_search(request):
    if not _require_teacher_or_it(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    q = request.GET.get("q", "")
    results = search_collab_users(q, exclude_user_id=request.user.user_id)
    if not results and q.strip():
        return JsonResponse({"results": [], "not_found": True, "query": q.strip()})
    return JsonResponse({"results": results, "not_found": False})


@login_required
@require_GET
def share_item_context(request, branch_id):
    branch = get_object_or_404(BranchGroup, id=branch_id)
    if not can_edit_branch(request.user, branch):
        return JsonResponse({"error": "Need edit access to share."}, status=403)
    if share_root_has_non_owner_collaborators(branch):
        ensure_branch_owner_acl(branch)
    my_groups = list_group_memberships_for_user(request.user, include_public=False)
    return JsonResponse(
        {
            "branch_id": branch.id,
            "name": branch.name,
            "owner_id": branch.owner_id,
            "my_perm": effective_permission(request.user, branch),
            "is_owner": branch.owner_id == request.user.user_id
            or effective_permission(request.user, branch) == PERM_OWNER,
            "has_collaborators": share_root_has_non_owner_collaborators(branch),
            "my_groups": my_groups,
            "acl": _serialize_branch_acl(branch.id),
            "public_available": True,
        }
    )


@login_required
@require_POST
def share_item_grant(request, branch_id):
    branch = get_object_or_404(BranchGroup, id=branch_id)
    if not can_edit_branch(request.user, branch):
        return JsonResponse({"error": "Need edit access to share."}, status=403)
    data = json.loads(request.body)
    note = (data.get("note") or "").strip()
    permissions = data.get("permissions") or PERM_READ_ONLY
    if permissions not in (PERM_EDIT, PERM_READ_ONLY):
        return JsonResponse({"error": "Invalid permissions."}, status=400)

    ensure_branch_owner_acl(branch)

    grants = data.get("grants") or []
    notified = []
    for g in grants:
        kind = g.get("kind")
        if kind == "user":
            target = get_object_or_404(UserProfile, user_id=g.get("user_id"))
            grant_perm = g.get("permissions") or permissions
            with connection.cursor() as c:
                c.execute(
                    "SELECT permissions::text FROM users_group WHERE branch_id = %s AND user_id = %s",
                    [branch.id, target.user_id],
                )
                existing_acl = c.fetchone()
            if existing_acl:
                return JsonResponse(
                    {
                        "ok": False,
                        "error": f"{target.username} already has access on this item ({existing_acl[0]}).",
                        "code": "already_shared",
                    },
                    status=400,
                )
            result = grant_user_on_branch(branch, target, permissions=grant_perm, actor=request.user)
            if not result.get("ok"):
                return JsonResponse(result, status=400)
            notify_share_event(
                target,
                title=f"Shared: {branch.name}",
                content={
                    "item": branch.name,
                    "permissions": grant_perm,
                    "note": note,
                    "from": request.user.username,
                },
                sender=request.user,
            )
            notified.append(target.username)
        elif kind == "group":
            pg_id = g.get("pg_id")
            if pg_id == "public" or pg_id is None and g.get("_public"):
                pg = PermissionGroup.objects.filter(name=PUBLIC_GROUP_NAME).first()
            else:
                pg = get_object_or_404(PermissionGroup, id=pg_id)
            if not pg:
                return JsonResponse({"error": "public group is not set up."}, status=400)
            if pg.name != PUBLIC_GROUP_NAME and not get_group_membership(request.user, pg):
                return JsonResponse({"error": f"You are not a member of '{pg.name}'."}, status=403)
            grant_perm = g.get("permissions") or permissions
            for row in list_branch_acl(branch.id):
                if row["permission_group_id"] == pg.id:
                    return JsonResponse(
                        {
                            "ok": False,
                            "error": f"Group '{pg.name}' already has access on this item.",
                            "code": "already_shared",
                        },
                        status=400,
                    )
            grant_group_on_branch(branch, pg, grant_perm)
            for uid in expand_group_member_user_ids(pg.id):
                if uid == request.user.user_id:
                    continue
                u = UserProfile.objects.filter(user_id=uid).first()
                if u:
                    notify_share_event(
                        u,
                        title=f"Shared via group '{pg.name}': {branch.name}",
                        content={
                            "item": branch.name,
                            "group": pg.name,
                            "permissions": grant_perm,
                            "note": note,
                            "from": request.user.username,
                        },
                        sender=request.user,
                    )
            notified.append(pg.name)
        else:
            return JsonResponse({"error": "Unknown grant kind."}, status=400)

    return JsonResponse({"ok": True, "notified": notified, "acl": _serialize_branch_acl(branch.id)})


@login_required
@require_POST
def share_item_update_perm(request, branch_id):
    """Change edit / view-only for an existing collaborator on a share root."""
    branch = get_object_or_404(BranchGroup, id=branch_id)
    if not can_edit_branch(request.user, branch):
        return JsonResponse({"error": "Need edit access to share."}, status=403)
    data = json.loads(request.body)
    permissions = data.get("permissions")
    if permissions not in (PERM_EDIT, PERM_READ_ONLY):
        return JsonResponse({"error": "Invalid permissions."}, status=400)
    kind = data.get("kind")

    if kind == "user":
        target = get_object_or_404(UserProfile, user_id=data.get("user_id"))
        if target.user_id == branch.owner_id:
            return JsonResponse({"error": "Cannot change the owner's permission."}, status=400)
        with connection.cursor() as c:
            c.execute(
                "SELECT permissions::text FROM users_group WHERE branch_id = %s AND user_id = %s",
                [branch.id, target.user_id],
            )
            existing = c.fetchone()
        if not existing:
            return JsonResponse({"error": "User is not on this item's share list."}, status=400)
        if existing[0] == PERM_OWNER:
            return JsonResponse({"error": "Cannot change owner permission."}, status=400)
        if permissions == PERM_READ_ONLY:
            via_edit, gname = user_has_edit_via_group_on_branch(target, branch)
            if via_edit:
                return JsonResponse(
                    {
                        "ok": False,
                        "error": (
                            f"{target.username} already has edit access through group "
                            f"'{gname}' and cannot be set to view-only."
                        ),
                        "code": "view_only_blocked",
                    },
                    status=400,
                )
        upsert_user_acl(branch.id, target.user_id, permissions)
    elif kind == "group":
        pg_id = data.get("pg_id")
        if pg_id == "public":
            pg = PermissionGroup.objects.filter(name=PUBLIC_GROUP_NAME).first()
        else:
            pg = get_object_or_404(PermissionGroup, id=pg_id)
        if not pg:
            return JsonResponse({"error": "Group not found."}, status=400)
        found = False
        for row in list_branch_acl(branch.id):
            if row["permission_group_id"] == pg.id:
                found = True
                if row["permissions"] == PERM_OWNER:
                    return JsonResponse({"error": "Cannot change owner permission."}, status=400)
                break
        if not found:
            return JsonResponse({"error": "Group is not on this item's share list."}, status=400)
        upsert_group_acl(branch.id, pg.id, permissions)
    else:
        return JsonResponse({"error": "Unknown kind."}, status=400)

    return JsonResponse({"ok": True, "acl": _serialize_branch_acl(branch.id)})


@login_required
@require_POST
def share_item_unshare(request, branch_id):
    branch = get_object_or_404(BranchGroup, id=branch_id)
    if branch.owner_id != request.user.user_id and effective_permission(request.user, branch) != PERM_OWNER:
        return JsonResponse({"error": "Only the owner can unshare."}, status=403)
    data = json.loads(request.body) if request.body else {}
    if share_root_has_non_owner_collaborators(branch) and not data.get("confirmed"):
        return JsonResponse(
            {
                "ok": False,
                "needs_confirm": True,
                "message": (
                    "This will remove access for all other users and groups. "
                    "The item will leave Collaboration / Public Library and remain only in your Workspace."
                ),
            }
        )
    removed = unshare_branch(branch, request.user)
    for uid in removed:
        u = UserProfile.objects.filter(user_id=uid).first()
        if u:
            notify_share_event(
                u,
                title=f"Access removed: {branch.name}",
                content={"item": branch.name, "by": request.user.username},
                sender=request.user,
            )
    return JsonResponse({"ok": True, "acl": _serialize_branch_acl(branch.id)})


@login_required
@require_POST
def share_item_revoke(request, branch_id):
    """Remove one user or group from the share ACL."""
    branch = get_object_or_404(BranchGroup, id=branch_id)
    if not can_edit_branch(request.user, branch):
        return JsonResponse({"error": "Need edit access to share."}, status=403)
    data = json.loads(request.body) if request.body else {}
    kind = data.get("kind")
    pg_id = data.get("pg_id")
    if pg_id == "public":
        public = PermissionGroup.objects.filter(name=PUBLIC_GROUP_NAME).first()
        pg_id = public.id if public else None
    removed, err = revoke_branch_collaborator(
        branch,
        kind=kind,
        user_id=data.get("user_id"),
        permission_group_id=pg_id,
        actor=request.user,
    )
    if err:
        return JsonResponse({"error": err}, status=400)
    for uid in removed:
        u = UserProfile.objects.filter(user_id=uid).first()
        if u:
            notify_share_event(
                u,
                title=f"Access removed: {branch.name}",
                content={"item": branch.name, "by": request.user.username},
                sender=request.user,
            )
    return JsonResponse({"ok": True, "acl": _serialize_branch_acl(branch.id)})


@login_required
@require_POST
def share_item_leave(request, branch_id):
    from django.db import connection

    branch = get_object_or_404(BranchGroup, id=branch_id)
    if branch.owner_id == request.user.user_id:
        return JsonResponse({"error": "Owner cannot leave; transfer ownership or unshare."}, status=400)
    with connection.cursor() as c:
        c.execute(
            "SELECT permissions::text FROM users_group WHERE branch_id = %s AND user_id = %s",
            [branch.id, request.user.user_id],
        )
        row = c.fetchone()
        if not row:
            return JsonResponse(
                {
                    "error": (
                        "Your access is through a group. Leave that group in Manage Groups "
                        "to drop collaboration access."
                    )
                },
                status=400,
            )
        c.execute(
            "DELETE FROM users_group WHERE branch_id = %s AND user_id = %s",
            [branch.id, request.user.user_id],
        )
    return JsonResponse({"ok": True})


@login_required
@require_POST
def copy_to_workspace(request):
    if not _require_teacher_or_it(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    data = json.loads(request.body)
    branch_id = data.get("branch_id")
    src = get_object_or_404(BranchGroup, id=branch_id)
    if src.owner_id != request.user.user_id and not can_read_branch(request.user, src):
        return JsonResponse({"error": "Permission denied."}, status=403)
    dest = workspace_folder(request.user)
    if not dest:
        return JsonResponse({"error": "Workspace folder missing."}, status=400)
    try:
        with transaction.atomic():
            new_node = clone_node_recursive(
                src, dest, request.user, context={"course": None, "assessment": None, "aqg": None, "cqd": None},
                starter_node=True,
            )
    except Exception as exc:
        return JsonResponse(
            {"error": f"Copy failed while cloning “{src.name}”: {exc}"},
            status=500,
        )
    if hasattr(new_node, "status_code"):
        return new_node
    return JsonResponse({"ok": True, "id": new_node.id, "name": new_node.name})


@login_required
@require_POST
def move_item(request):
    """Move within Workspace / into owned Courses, or deep-copy into Collaboration.

    Same name + same type under a shared / Collaboration destination prompts
    delete-and-replace (ACL on the replaced node is preserved).

    Courses rules:
    - Plain folders cannot be moved into the Courses subtree.
    - The Courses root accepts only course nodes (set to closed on arrival).
    - Content may be moved into an owned course tree; child structure is kept.
    """
    if not _require_teacher_or_it(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    data = json.loads(request.body)
    branch_id = data.get("branch_id")
    dest_id = data.get("dest_parent_id")
    confirmed = bool(data.get("confirmed"))
    replace_confirmed = bool(data.get("replace_confirmed"))
    src = get_object_or_404(
        BranchGroup.objects.select_related(
            "parent", "course", "assessment", "aqg", "cqd", "problem"
        ),
        id=branch_id,
    )
    dest = get_object_or_404(
        BranchGroup.objects.select_related(
            "parent", "course", "assessment", "aqg", "cqd", "problem"
        ),
        id=dest_id,
    )

    if src.owner_id != request.user.user_id:
        return JsonResponse({"error": "You can only move items you own."}, status=403)
    if not can_edit_branch(request.user, dest) and dest.owner_id != request.user.user_id:
        return JsonResponse({"error": "Need edit access on destination."}, status=403)

    # Hierarchy checks — course→assessment→aqg→cqd|problem nesting only.
    from .branch_hierarchy import branch_placement_error, normalize_folder_type

    placement_err = branch_placement_error(dest.folder_type, src.folder_type)
    if placement_err:
        return JsonResponse({"error": placement_err}, status=400)

    dest_under_courses = branch_is_under_courses(dest)
    dest_is_courses_root = is_courses_root_folder(dest)
    src_type = normalize_folder_type(src.folder_type)

    if dest_under_courses or dest_is_courses_root:
        if src_type == "folder":
            return JsonResponse(
                {
                    "error": (
                        "Plain folders cannot be moved into Courses. "
                        "Move a course, or place content inside a course you own."
                    )
                },
                status=400,
            )
        if dest_is_courses_root and src_type != "course":
            return JsonResponse(
                {
                    "error": (
                        "Only courses can be placed directly in the Courses folder. "
                        "Open a course you own to move assessments or problems into it."
                    )
                },
                status=400,
            )
        # Content into a course tree must target a course the user owns (IT may assist).
        if not dest_is_courses_root:
            course_owner_id = None
            walker = dest
            seen = set()
            while walker is not None and walker.id not in seen:
                seen.add(walker.id)
                if normalize_folder_type(walker.folder_type) == "course":
                    course = get_branch_related(walker, "course")
                    course_owner_id = getattr(course, "owner_id", None)
                    break
                walker = walker.parent
            is_it = getattr(request.user, "user_type", None) == "IT_Support"
            if course_owner_id is None:
                return JsonResponse(
                    {"error": "Destination is not inside a course you own."},
                    status=400,
                )
            if course_owner_id != request.user.user_id and not is_it:
                return JsonResponse(
                    {"error": "You can only move content into courses you own."},
                    status=403,
                )

    dest_path = dest.get_parent_path() + dest.name + "/"
    under_collab = f"/{request.user.username}_root/{FOLDER_COLLABORATION}/" in dest_path or (
        dest.name == FOLDER_COLLABORATION
    )
    is_shared_dest = branch_is_in_shared_subtree(dest)
    # Sibling under the Move-here parent (same name + same folder_type) — not "into" the item.
    conflict = find_same_name_type_sibling(dest, src)
    # Collaboration context: dest is shared/under Collaboration, or the name clash is a shared item
    # (share roots often sit under Workspace while appearing in the Collaboration listing).
    conflict_is_shared = bool(
        conflict
        and (
            branch_is_in_shared_subtree(conflict)
            or share_root_has_non_owner_collaborators(conflict)
            or getattr(conflict, "share_group_id", None)
        )
    )
    is_collab_copy = under_collab or (is_shared_dest and dest.owner_id != request.user.user_id)
    # Offer delete-and-replace for collab/shared destinations, or when clashing with a shared sibling.
    use_replace_flow = bool(conflict) and (
        is_collab_copy or is_shared_dest or conflict_is_shared or under_collab
    )

    def _replace_prompt(*, copy_mode: bool):
        return JsonResponse(
            {
                "ok": False,
                "needs_confirm": True,
                "replace": True,
                "copy": copy_mode,
                "conflict_id": conflict.id if conflict else None,
                "message": replace_name_conflict_message(src, conflict),
            }
        )

    if is_collab_copy:
        if use_replace_flow and not replace_confirmed:
            return _replace_prompt(copy_mode=True)
        if not conflict and not confirmed:
            return JsonResponse(
                {
                    "ok": False,
                    "needs_confirm": True,
                    "copy": True,
                    "replace": False,
                    "message": (
                        "This will copy the item into the Collaboration destination. "
                        "Your local Workspace copy is kept. Anyone with access to the "
                        "destination will have the same permissions on the copy."
                    ),
                }
            )
        with transaction.atomic():
            if conflict and replace_confirmed:
                acl_snap = snapshot_branch_acl(conflict)
                hard_delete_branch_tree(conflict)
                new_node = clone_node_recursive(
                    src,
                    dest,
                    dest.owner,
                    context={"course": None, "assessment": None, "aqg": None, "cqd": None},
                    starter_node=True,
                    force_name=src.name,
                )
                if hasattr(new_node, "status_code"):
                    return new_node
                restore_branch_acl(new_node, acl_snap)
                return JsonResponse(
                    {"ok": True, "action": "replaced", "id": getattr(new_node, "id", None)}
                )
            new_node = clone_node_recursive(
                src,
                dest,
                dest.owner,
                context={"course": None, "assessment": None, "aqg": None, "cqd": None},
                starter_node=True,
            )
            if hasattr(new_node, "status_code"):
                return new_node
        return JsonResponse({"ok": True, "action": "copied", "id": getattr(new_node, "id", None)})

    # Owned shared destination, or replacing a shared sibling under a normal parent (e.g. Workspace)
    if is_shared_dest or (use_replace_flow and conflict_is_shared):
        if use_replace_flow and not replace_confirmed:
            return _replace_prompt(copy_mode=False)
        if is_shared_dest and not conflict and not confirmed:
            return JsonResponse(
                {
                    "ok": False,
                    "needs_confirm": True,
                    "copy": False,
                    "replace": False,
                    "message": (
                        "This folder is shared. Anyone with access will have the same "
                        "permissions on the item you are adding."
                    ),
                }
            )

    # Moving a course into Courses parks it as closed (reactivate from the Courses page).
    moving_course_into_courses = dest_is_courses_root and src_type == "course"
    if moving_course_into_courses and not confirmed and not replace_confirmed:
        return JsonResponse(
            {
                "ok": False,
                "needs_confirm": True,
                "copy": False,
                "replace": False,
                "close_course": True,
                "message": (
                    "Move this course into Courses? It will be set to Closed. "
                    "Reactivate it from the Courses page when you are ready. "
                    "Assessments and nested content stay with the course; this is a move, "
                    "not a copy, so existing enrollments are unchanged."
                ),
            }
        )

    # Reject moves into self or into a descendant (would create an unreachable cycle).
    if dest.id == src.id:
        return JsonResponse({"error": "Cannot move an item into itself."}, status=400)
    ancestor = dest
    seen = set()
    while ancestor is not None:
        if ancestor.id == src.id:
            return JsonResponse(
                {"error": "Cannot move an item into one of its own subfolders."},
                status=400,
            )
        if ancestor.id in seen:
            break
        seen.add(ancestor.id)
        ancestor = ancestor.parent

    with transaction.atomic():
        if conflict and replace_confirmed and (is_shared_dest or conflict_is_shared):
            acl_snap = snapshot_branch_acl(conflict)
            hard_delete_branch_tree(conflict)
            src.parent = dest
            src.order = src.name
            src.save(update_fields=["parent", "name", "order"])
            # If the conflict carried share-root ACL, reattach it to the moved item.
            restore_branch_acl(src, acl_snap)
            sync_branch_payload_parent_links(src, dest)
            if moving_course_into_courses:
                course = get_branch_related(src, "course")
                if course is not None:
                    apply_course_status(course, "closed")
            return JsonResponse({"ok": True, "action": "replaced", "id": src.id})

        unique_name, error = resolve_unique_sibling_name(dest, src.name, exclude_id=src.id)
        if error:
            return JsonResponse({"error": error}, status=400)
        src.parent = dest
        if src.name != unique_name:
            src.name = unique_name
            src.order = unique_name
            src.save(update_fields=["parent", "name", "order"])
        else:
            src.save(update_fields=["parent"])
        sync_branch_payload_parent_links(src, dest)
        if moving_course_into_courses:
            course = get_branch_related(src, "course")
            if course is not None:
                apply_course_status(course, "closed")
    return JsonResponse({"ok": True, "action": "moved"})


@login_required
@require_POST
def reorder_siblings(request):
    """Reorder a branch among siblings via midpoint order."""
    from .util import calculate_midpoint_order

    data = json.loads(request.body)
    branch_id = data.get("branch_id")
    before_id = data.get("before_id")  # insert before this sibling; null = end
    branch = get_object_or_404(BranchGroup, id=branch_id)
    if branch.owner_id != request.user.user_id:
        return JsonResponse({"error": "Permission denied."}, status=403)
    if branch.parent and branch.parent.parent_id is None and branch.name in (
        "Trash",
        "Courses",
        "Collaboration",
        "Public Library",
        "Workspace",
        "Student Provided Assessments",
    ):
        # Allow Workspace sibling reorder among non-system? System folders locked.
        if branch.name != "Workspace" and branch.parent.parent_id is None:
            # top-level system folders cannot be reordered except we pin Trash
            pass

    parent = branch.parent
    if parent and parent.parent_id is None and branch.name == "Trash":
        return JsonResponse({"error": "Trash stays at the bottom."}, status=400)

    siblings = list(
        BranchGroup.objects.filter(parent=parent).exclude(id=branch.id).order_by("order")
    )
    if parent and parent.parent_id is None:
        siblings = [s for s in siblings if s.name != "Trash"]

    if before_id:
        before = next((s for s in siblings if s.id == int(before_id)), None)
        idx = siblings.index(before) if before else len(siblings)
    else:
        idx = len(siblings)

    prev_order = siblings[idx - 1].order if idx > 0 else ""
    next_order = siblings[idx].order if idx < len(siblings) else ""
    branch.order = calculate_midpoint_order(prev_order or "", next_order or "")
    branch.save(update_fields=["order"])
    return JsonResponse({"ok": True, "order": branch.order})


@login_required
@require_GET
def branch_preview(request, branch_id):
    """Preview pane for folders, including trash origin path."""
    branch = get_object_or_404(BranchGroup, id=branch_id)
    if branch.owner_id != request.user.user_id and not can_read_branch(request.user, branch):
        return JsonResponse({"error": "Permission denied."}, status=403)
    origin = None
    if branch.previous_parent_id:
        pp = branch.previous_parent
        origin = pp.get_parent_path() + pp.name + "/"
    return render(
        request,
        "assessment_tool/partials/folder_preview.html",
        {
            "branch": branch,
            "origin_path": origin,
            "trashed_at": branch.trashed_at,
        },
    )
