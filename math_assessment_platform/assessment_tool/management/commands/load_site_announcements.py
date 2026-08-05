"""
Import site_announcement rows from JSON produced by dump_site_announcements.

Upserts by exact title. Optional per-title enabled overrides:

    python manage.py load_site_announcements /tmp/announcements.json
    python manage.py load_site_announcements /tmp/announcements.json \\
        --enable "Under Construction" --disable "Maint window"
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from assessment_tool.site_announcements import import_announcements


class Command(BaseCommand):
    help = "Load site announcements from JSON (upsert by title)."

    def add_arguments(self, parser):
        parser.add_argument("path", help="JSON file from dump_site_announcements.")
        parser.add_argument(
            "--enable",
            action="append",
            default=[],
            dest="enable_titles",
            help="Force this title on (is_enabled=true). Repeatable.",
        )
        parser.add_argument(
            "--disable",
            action="append",
            default=[],
            dest="disable_titles",
            help="Force this title off (is_enabled=false). Repeatable.",
        )

    def handle(self, *args, **options):
        path = options["path"]
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except OSError as exc:
            raise CommandError(f"Could not read {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON in {path}: {exc}") from exc

        if isinstance(raw, dict):
            payloads = raw.get("announcements")
        elif isinstance(raw, list):
            payloads = raw
        else:
            raise CommandError("JSON must be a list or {announcements: [...]}.")

        if not isinstance(payloads, list):
            raise CommandError("announcements must be a list.")

        overrides: dict[str, bool] = {}
        for title in options.get("enable_titles") or []:
            t = (title or "").strip()
            if t:
                overrides[t] = True
        for title in options.get("disable_titles") or []:
            t = (title or "").strip()
            if t:
                overrides[t] = False

        result = import_announcements(payloads, enabled_overrides=overrides)
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported announcements: created={result['created']} "
                f"updated={result['updated']} total={result['total']}"
            )
        )
        if overrides:
            for title, enabled in sorted(overrides.items()):
                state = "on" if enabled else "off"
                self.stdout.write(f"  override: {title!r} → {state}")
