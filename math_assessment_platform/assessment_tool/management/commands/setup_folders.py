from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction

from assessment_tool.folder_roots import (
    FOLDER_RENAMES,
    FOLDER_WORKSPACE,
    WORKSPACE_LEGACY_SOURCES,
    default_top_level_folders_for_user,
)
from assessment_tool.models import BranchGroup
from assessment_tool.util import get_valid_unique_name


class Command(BaseCommand):
    help = (
        "Safely creates/migrates root and default sub-folders for all users "
        "(Workspace merge, Collaboration/Public Library renames, student-only folder)."
    )

    def handle(self, *args, **options):
        User = get_user_model()
        users = User.objects.all()

        self.stdout.write(f"Checking folder structures for {users.count()} users...")

        for user in users:
            root = BranchGroup.objects.filter(owner=user, parent__isnull=True).first()
            root_location = f"{user.username}_root"
            if not root:
                try:
                    root = BranchGroup.objects.create(
                        name=root_location,
                        owner=user,
                        parent=None,
                    )
                    self.stdout.write(self.style.SUCCESS(f"Created root for {user.username}"))
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"Failed to create root for {user.username}: {e}")
                    )
                    continue

            try:
                with transaction.atomic():
                    self._migrate_user_folders(user, root)
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Migration failed for {user.username}: {e}")
                )

    def _migrate_user_folders(self, user, root):
        # 1. Simple renames
        for old_name, new_name in FOLDER_RENAMES.items():
            old = BranchGroup.objects.filter(
                owner=user, parent=root, name=old_name
            ).first()
            if not old:
                continue
            conflict = BranchGroup.objects.filter(
                owner=user, parent=root, name=new_name
            ).exclude(pk=old.pk).first()
            if conflict:
                self._move_children(old, conflict)
                old.delete()
                self.stdout.write(
                    f"  ~ Merged '{old_name}' into existing '{new_name}' for {user.username}"
                )
            else:
                old.name = new_name
                old.order = new_name
                old.save(update_fields=["name", "order"])
                self.stdout.write(
                    f"  ~ Renamed '{old_name}' → '{new_name}' for {user.username}"
                )

        # 2. Merge Standalone Assessments / Problems into Workspace
        workspace = BranchGroup.objects.filter(
            owner=user, parent=root, name=FOLDER_WORKSPACE
        ).first()
        legacy_nodes = list(
            BranchGroup.objects.filter(
                owner=user, parent=root, name__in=WORKSPACE_LEGACY_SOURCES
            )
        )
        if workspace is None and legacy_nodes:
            primary = legacy_nodes[0]
            primary.name = FOLDER_WORKSPACE
            primary.order = FOLDER_WORKSPACE
            primary.save(update_fields=["name", "order"])
            workspace = primary
            legacy_nodes = legacy_nodes[1:]
            self.stdout.write(
                f"  ~ Created Workspace from legacy folder for {user.username}"
            )

        if workspace is None:
            workspace = BranchGroup.objects.create(
                name=FOLDER_WORKSPACE,
                owner=user,
                parent=root,
                folder_type="folder",
                order=FOLDER_WORKSPACE,
            )
            self.stdout.write(f"  + Added '{FOLDER_WORKSPACE}' to {user.username}")

        for old in legacy_nodes:
            if old.pk == workspace.pk:
                continue
            self._move_children(old, workspace)
            old.delete()
            self.stdout.write(
                f"  ~ Merged '{old.name}' into Workspace for {user.username}"
            )

        # 3. Ensure required defaults exist (student-only folder included by helper)
        for folder_name in default_top_level_folders_for_user(user):
            exists = BranchGroup.objects.filter(
                owner=user, parent=root, name=folder_name
            ).exists()
            if exists:
                continue
            BranchGroup.objects.create(
                name=folder_name,
                owner=user,
                parent=root,
                folder_type="folder",
                order=folder_name,
            )
            self.stdout.write(f"  + Added '{folder_name}' to {user.username}")

        # 4. Non-students: leave Student Provided Assessments if present (hidden in UI)
        #    so we do not destroy any accidental content; explorer filters it out.

    def _move_children(self, source, dest):
        for child in BranchGroup.objects.filter(parent=source):
            requested = (child.name or "").strip() or "Unnamed"
            unique_name, error = get_valid_unique_name(
                BranchGroup, dest, requested, exclude_id=child.pk
            )
            if error or not unique_name:
                # Invalid legacy names (underscores, parens, null): sanitize then uniquify.
                safe_base = "".join(
                    ch if ch.isalnum() or ch == " " else " " for ch in requested
                )
                safe_base = " ".join(safe_base.split()) or "Unnamed"
                unique_name, error = get_valid_unique_name(
                    BranchGroup, dest, safe_base, exclude_id=child.pk
                )
                if error or not unique_name:
                    unique_name = f"Unnamed {child.pk}"
            child.parent = dest
            if child.name != unique_name:
                child.name = unique_name
                child.order = unique_name
                child.save(update_fields=["parent", "name", "order"])
            else:
                child.save(update_fields=["parent"])
