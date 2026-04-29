from django.test.runner import DiscoverRunner
from django.apps import apps

# class ManagedModelTestRunner(DiscoverRunner):
#     """
#     Test runner that temporarily sets 'managed' to True on all models
#     BEFORE the test database is created/migrated.
#     """
#     def setup_databases(self, **kwargs):
#         from django.apps import apps
#         # Find all models set to managed = False
#         self.unmanaged_models = [
#             m for m in apps.get_models() if not m._meta.managed
#         ]
#         # Flip them to True BEFORE migrations run in the test DB
#         for m in self.unmanaged_models:
#             m._meta.managed = True
        
#         return super().setup_databases(**kwargs)

#     def teardown_databases(self, old_config, **kwargs):
#         # Reset them back to False after the test database is destroyed
#         for m in self.unmanaged_models:
#             m._meta.managed = False
#         super().teardown_databases(old_config, **kwargs)

class ManagedModelTestRunner(DiscoverRunner):
    def __init__(self, *args, **kwargs):
        # Flip managed to True globally as soon as the runner starts
        for model in apps.get_models():
            if not model._meta.managed:
                model._meta.managed = True
        super().__init__(*args, **kwargs)

    def setup_databases(self, **kwargs):
        return super().setup_databases(**kwargs)