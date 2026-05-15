from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import pre_save, post_delete, post_save
from django.dispatch import receiver
from .models import BranchGroup, UserProfile, Course

@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    # Update the user record with the new session key
    user.last_session_key = request.session.session_key
    user.save(update_fields=['last_session_key'])


@receiver(pre_save, sender=BranchGroup)
def sync_name_to_order(sender, instance, **kwargs):
    # 1. Logic for protection
    username = instance.owner.username
    root_path = f"/Users/{username}_root/"
    
    # Try to calculate path, fallback to empty if it's a brand new unsaved object
    try:
        current_path = instance.get_parent_path() + instance.name + "/"
    except:
        current_path = ""

    protected_roots = [
        root_path,
        f"{root_path}Courses/",
        f"{root_path}Standalone Assessments/",
        f"{root_path}Shared for Collaboration/",
        f"{root_path}Student Generated Assessments by Course/",
        f"{root_path}Public/",
    ]

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
            order=f"{instance.username}_root", # default order to the name, it will cause it to sort alphabetically
        )

        # 2. Define the default sub-folders
        # NOTE: This should not be changed in order to conform with proper path naming restrictions
        default_folders = ['Courses', 'Standalone Assessments', 'Standalone Problems', 'Shared for Collaboration', 'Student Generated Assessments by Course', 'Public']

        # 3. Create each sub-folder nested under the root
        for folder_name in default_folders:
            BranchGroup.objects.create(
                name=folder_name,
                owner=instance,
                parent=root,
                folder_type="folder",
                order=folder_name, # default order to the name, it will cause it to sort alphabetically
            )

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