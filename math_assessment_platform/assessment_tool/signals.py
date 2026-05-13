from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import pre_save
from django.dispatch import receiver
from .models import BranchGroup

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