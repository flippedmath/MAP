"""
Close upcoming assessments whose auto-open window has ended.

Force-submits open (non-retake) attempts the same way as a teacher close, or
throws unused assessments (no student started/submitted) without writing zeros.

Install on the **production server only** (every minute). Do not install on the
local Mac development machine.

    * * * * * /path/to/math_assessment_platform/scripts/close_expired_upcoming_assessments.sh # MAP:close_expired_upcoming_assessments
"""

from django.core.management.base import BaseCommand

from assessment_tool.student_attempts import close_expired_upcoming_assessments


class Command(BaseCommand):
    help = (
        "Set status=closed on upcoming assessments whose end_time has passed, "
        "and force-submit open class attempts. Schedule with cron; do not call "
        "from request handlers."
    )

    def handle(self, *args, **options):
        result = close_expired_upcoming_assessments()
        count = result.get("closed_count", 0)
        ids = result.get("closed_assessment_ids") or []
        if count:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Closed {count} expired upcoming assessment(s): {ids}"
                )
            )
        else:
            self.stdout.write("No expired upcoming assessments to close.")
