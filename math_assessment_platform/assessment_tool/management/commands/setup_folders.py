from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from assessment_tool.models import BranchGroup

class Command(BaseCommand):
    help = 'Safely creates root and default sub-folders for all existing users'

    def handle(self, *args, **options):
        User = get_user_model()
        users = User.objects.all()
        
        self.stdout.write(f"Checking folder structures for {users.count()} users...")

        for user in users:
            # 1. Manually check for Root Folder
            root = BranchGroup.objects.filter(owner=user, parent__isnull=True).first()
            
            if not root:
                try:
                    # Generate a unique location, e.g., "admin_root"
                    root_location = f"{user.username}_root" 
                    root = BranchGroup.objects.create(
                        name=user.username,
                        owner=user,
                        parent=None,
                        location=root_location  # Added this
                    )
                    self.stdout.write(self.style.SUCCESS(f"Created root for {user.username}"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Failed to create root for {user.username}: {e}"))
                    continue

            # 2. Check and create Sub-folders
            default_names = ['courses', 'standalone assessments', 'standalone problems']
            for folder_name in default_names:
                exists = BranchGroup.objects.filter(
                    owner=user, 
                    parent=root, 
                    name=folder_name
                ).exists()
                
                if not exists:
                    try:
                        # Generate a unique sub-location, e.g., "admin/courses"
                        # Replacing spaces with underscores for safety
                        loc_name = folder_name.replace(" ", "_")
                        sub_location = f"{user.username}/{loc_name}"
                        
                        BranchGroup.objects.create(
                            name=folder_name,
                            owner=user,
                            parent=root,
                            location=sub_location  # Added this
                        )
                        self.stdout.write(f"  + Added '{folder_name}' to {user.username}")
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"  - Error adding '{folder_name}': {e}"))