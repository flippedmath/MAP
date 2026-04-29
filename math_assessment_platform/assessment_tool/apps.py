from django.apps import AppConfig


class AssessmentToolConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'assessment_tool'

    def ready(self):
        # Implicitly connect signals by importing them
        import assessment_tool.signals