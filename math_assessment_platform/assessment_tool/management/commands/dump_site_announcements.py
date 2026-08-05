"""
Export site_announcement rows as JSON (for push-to-live sync).

    python manage.py dump_site_announcements
    python manage.py dump_site_announcements -o /tmp/announcements.json
    python manage.py dump_site_announcements --title "Under Construction"
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from assessment_tool.site_announcements import export_announcements


class Command(BaseCommand):
    help = "Dump site announcements as JSON (matched by title on import)."

    def add_arguments(self, parser):
        parser.add_argument(
            "-o",
            "--output",
            default="",
            help="Write JSON to this path (default: stdout).",
        )
        parser.add_argument(
            "--title",
            action="append",
            default=[],
            help="Only include this title (repeatable).",
        )

    def handle(self, *args, **options):
        titles = options.get("title") or None
        payload = {
            "version": 1,
            "announcements": export_announcements(titles=titles),
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        out_path = (options.get("output") or "").strip()
        if out_path:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(text)
            self.stdout.write(self.style.SUCCESS(f"Wrote {len(payload['announcements'])} announcement(s) to {out_path}"))
        else:
            self.stdout.write(text)
