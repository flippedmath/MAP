from django.core.management.base import BaseCommand
from assessment_tool.models import Assessment, BranchGroup
from django.db import transaction

class Command(BaseCommand):
    help = 'fix broken assessment links'

    def handle(self, *args, **options):
        # Find all assessments that have a branch_location entry
        assessments = Assessment.objects.select_related('course', 'branch_location').all()

        fixed_count = 0

        with transaction.atomic():
            for asm in assessments:
                course = asm.course
                asm_folder = asm.branch_location
                
                if not course or not asm_folder:
                    continue
                    
                # Get the target branch folder where the course lives
                course_folder = course.branch_location
                
                if not course_folder:
                    print(f"⚠️ Skipped: Course '{course.name}' does not have a branch folder assigned.")
                    continue
                    
                # Check if the assessment's folder parent is mismatched
                if asm_folder.parent_id != course_folder.id:
                    print(f"🔧 Healing: Re-linking Assessment '{asm.name}' back under Course '{course.name}'...")
                    
                    # Re-assign the parent relationship pointer safely
                    asm_folder.parent = course_folder
                    asm_folder.save()
                    
                    fixed_count += 1

        print(f"\n✅ Execution Finished. Successfully repaired {fixed_count} displaced assessment folder nodes.")