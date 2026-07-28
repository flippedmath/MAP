"""
Permanently remove trashed branch_group roots older than the retention window.

Run once daily via cron (independent of user requests), e.g.:

    20 3 * * * /path/to/math_assessment_platform/scripts/purge_trashed_branch_groups.sh

Marker for idempotent crontab install: # MAP:purge_trashed_branch_groups
"""

from django.core.management.base import BaseCommand

from assessment_tool.collaboration import TRASH_RETENTION, purge_expired_trashed_branches


class Command(BaseCommand):
    help = (
        "Permanently delete branch_group trees that have been in Trash longer "
        f"than {TRASH_RETENTION.days} days (all users). "
        "Schedule with cron; do not call from request handlers."
    )

    def handle(self, *args, **options):
        deleted = purge_expired_trashed_branches()
        self.stdout.write(
            self.style.SUCCESS(
                f"Purged {deleted} trashed branch root(s) older than "
                f"{TRASH_RETENTION.days} days."
            )
        )
