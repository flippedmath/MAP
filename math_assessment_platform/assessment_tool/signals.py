from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import pre_save, post_delete, post_save
from django.dispatch import receiver

from .folder_roots import (
    protected_subtree_prefixes,
    default_top_level_folders_for_user,
    user_root_path,
)
from .collaboration import enroll_user_in_public_if_eligible
from .models import BranchGroup, UserProfile, Course, Problem


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    # Update the user record with the new session key
    user.last_session_key = request.session.session_key
    user.save(update_fields=['last_session_key'])


@receiver(pre_save, sender=BranchGroup)
def sync_name_to_order(sender, instance, **kwargs):

    # 🛑 FIX: If this folder belongs to an Assessment Question Group, 
    # BAIL OUT IMMEDIATELY. Do not overwrite its midpoint order code or touch its path!
    # Only implement this logic with 'course' folder_type
    if instance.folder_type in ['aqg', 'problem']:
        return

    # 1. Logic for protection
    username = instance.owner.username
    root_path = user_root_path(username)
    
    # Try to calculate path, fallback to empty if it's a brand new unsaved object
    try:
        current_path = instance.get_parent_path() + instance.name + "/"
    except Exception:
        current_path = ""

    protected_roots = [root_path] + protected_subtree_prefixes(username)

    is_protected = any(current_path.startswith(p) for p in protected_roots) if current_path else False

    # 2. Sync logic: If not protected OR if order is currently None
    if not is_protected or not instance.order:
        instance.order = instance.name


@receiver(post_save, sender=UserProfile)
def create_user_folder_structure(sender, instance, created, **kwargs):
    if created:
        # 1. Create the Master Root Folder
        root = BranchGroup.objects.create(
            name=f"{instance.username}_root",
            owner=instance,
            parent=None,
            folder_type="folder",
            order=f"{instance.username}_root",
        )

        # 2. Default sub-folders (student-only folder included when user_type is Student)
        for folder_name in default_top_level_folders_for_user(instance):
            BranchGroup.objects.create(
                name=folder_name,
                owner=instance,
                parent=root,
                folder_type="folder",
                order=folder_name,
            )

    # Teachers / IT Support: public membership; IT also joins non-deletable admins.
    if getattr(instance, "user_type", None) in ("Teacher", "IT_Support"):
        enroll_user_in_public_if_eligible(instance)


@receiver(post_delete, sender=Course)
def delete_course_image(sender, instance, **kwargs):
    """Deletes physical file from filesystem when Course object is deleted."""
    if instance.image:
        # 'save=False' prevents the model from trying to save itself during deletion
        # This triggers regardless of how the Course was deleted
        instance.image.delete(save=False)


@receiver(pre_save, sender=Course)
def delete_old_image_on_change(sender, instance, **kwargs):
    """Deletes old file from filesystem when a new image is uploaded."""
    if not instance.pk:
        return False

    try:
        old_file = Course.objects.get(pk=instance.pk).image
    except Course.DoesNotExist:
        return False

    new_file = instance.image
    if old_file and old_file != new_file:
        old_file.delete(save=False)


@receiver(post_delete, sender=Problem)
def clear_orphaned_problem_branch_node(sender, instance, **kwargs):
    """
    Ensures that if a Problem row is purged directly from outside the file manager interface,
    (such as a direct database query?), its accompanying BranchGroup tracking node is dropped along with it.
    """
    if instance.branch_location:
        try:
            instance.branch_location.delete()
        except Exception:
            pass
