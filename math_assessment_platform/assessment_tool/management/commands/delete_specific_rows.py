from django.core.management.base import BaseCommand
from assessment_tool.models import Assessment, BranchGroup
from django.db import transaction
from assessment_tool.models import AssessmentQuestionGroup

class Command(BaseCommand):
    help = 'fix broken assessment links'

    def handle(self, *args, **options):

        # 1. Fetch the orphaned object
        aqg_id = 329  # 👈 Put your mismatched row ID here
        aqg = BranchGroup.objects.get(id=aqg_id)

        # 2. Delete it directly from the table row map
        aqg.delete()

        print(f"Successfully purged orphaned AQG ID {aqg_id} from the database.")