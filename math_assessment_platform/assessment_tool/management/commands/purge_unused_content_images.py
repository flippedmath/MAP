"""
Permanently remove unused Quill/content images.

Candidate rows (maybe_unused_at set) are verified with a DB HTML scan daily.
A full sweep of all images runs on Sundays (or with --full).

Cron example:

    25 3 * * * /path/to/math_assessment_platform/scripts/purge_unused_content_images.sh
"""

from django.core.management.base import BaseCommand

from assessment_tool.content_images import (
    purge_unused_content_images,
    should_run_full_sweep,
)


class Command(BaseCommand):
    help = (
        "Delete content_image files with no remaining HTML references. "
        "By default only processes maybe_unused candidates; Sundays (or --full) "
        "scan all images past the upload grace period."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--full",
            action="store_true",
            help="Scan all content images (not only maybe_unused candidates).",
        )
        parser.add_argument(
            "--candidates-only",
            action="store_true",
            help="Never run a full sweep even on Sunday.",
        )

    def handle(self, *args, **options):
        full = bool(options.get("full"))
        if not full and not options.get("candidates_only"):
            full = should_run_full_sweep()
        result = purge_unused_content_images(full_sweep=full)
        self.stdout.write(
            self.style.SUCCESS(
                "content_image purge: scanned={scanned} deleted={deleted} "
                "cleared_still_used={cleared} full_sweep={full_sweep}".format(**result)
            )
        )
