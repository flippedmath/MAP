from django.core.management.base import BaseCommand
from assessment_tool.models import EntityType
from assessment_tool.util import get_entity_validator


class Command(BaseCommand):

    def handle(self, *args, **options):

        # Fetch your seeded schema format template
        entity_type_obj = EntityType.objects.get(name="randInt")
        blueprint = entity_type_obj.format_pattern # returns dictionary automatically due to TextField conversion or fallback parsing

        # Simulate an invalid user submission configuration (min > max)
        bad_submission = {
            "inputs": {
                "min": "25",
                "max": 5,
                "step": 1,
                "exclude": "2, 4, 6"
            }
        }

        validator = get_entity_validator("randInt", bad_submission, blueprint)
        print(validator.is_valid())  # Should print: False
        print(validator.errors)      # Should print: {'min': "Minimum bound (25) cannot be greater than maximum bound (5)."}
