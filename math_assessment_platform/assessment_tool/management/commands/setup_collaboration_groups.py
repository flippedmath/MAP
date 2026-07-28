from django.core.management.base import BaseCommand

from assessment_tool.collaboration import ensure_admins_group, ensure_public_group


class Command(BaseCommand):
    help = (
        "Ensure system permission groups: non-deletable 'admins' (all IT_Support) "
        "owns 'public' (Teachers read_only, IT_Support edit). Public is not owned "
        "by an individual user, so Public Library content is not relocated into a "
        "personal Workspace."
    )

    def handle(self, *args, **options):
        admins = ensure_admins_group()
        pg = ensure_public_group()
        self.stdout.write(
            self.style.SUCCESS(
                f"admins id={admins.id} (system_protected={admins.system_protected}); "
                f"public id={pg.id} owner_pg_id={pg.owner_pg_id} "
                f"owner_id={pg.owner_id} ready."
            )
        )
