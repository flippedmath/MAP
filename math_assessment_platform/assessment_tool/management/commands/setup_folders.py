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
            
            # Generate a unique location, e.g., "admin_root"
            root_location = f"{user.username}_root" 
            if not root:
                try:
                    root = BranchGroup.objects.create(
                        name=root_location, # user.username,
                        owner=user,
                        parent=None,
                    )
                    self.stdout.write(self.style.SUCCESS(f"Created root for {user.username}"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Failed to create root for {user.username}: {e}"))
                    continue

            # 2. Check and create Sub-folders
            default_names = [['Courses', "C"], ['Standalone Assessments', "V"], ['Standalone Problems', "h"]]
            for folder_name in default_names:
                exists = BranchGroup.objects.filter(
                    owner=user, 
                    parent=root, 
                    name=folder_name[0],
                ).exists()
                
                if not exists:
                    try:
                        BranchGroup.objects.create(
                            name=folder_name[0],
                            owner=user,
                            parent=root,
                            order=folder_name[1]
                        )
                        self.stdout.write(f"  + Added '{folder_name[0]}' to {user.username} at order {folder_name[1]}")
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"  - Error adding '{folder_name[0]}': {e}"))