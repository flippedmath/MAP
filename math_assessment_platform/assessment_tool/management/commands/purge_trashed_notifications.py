"""
Permanently remove trashed notifications older than the retention window.

Run once daily via cron (independent of user requests), e.g.:

    15 3 * * * /path/to/math_assessment_platform/scripts/purge_trashed_notifications.sh

Or directly:

    15 3 * * * cd /path/to/math_assessment_platform && \\
      /path/to/.venv/bin/python manage.py purge_trashed_notifications
"""

from django.core.management.base import BaseCommand

from assessment_tool.notifications import (
    NOTIFICATION_TRASH_RETENTION,
    purge_expired_trashed_notifications,
)


class Command(BaseCommand):
    help = (
        "Permanently delete notification rows that have been in trash longer "
        f"than {NOTIFICATION_TRASH_RETENTION.days} days (all users). "
        "Schedule with cron; do not call from request handlers."
    )

    def handle(self, *args, **options):
        deleted = purge_expired_trashed_notifications()
        self.stdout.write(
            self.style.SUCCESS(
                f"Purged {deleted} trashed notification(s) older than "
                f"{NOTIFICATION_TRASH_RETENTION.days} days."
            )
        )
