"""
Upsert public Q&A articles linked from the About page.

Run on each environment that should show the About hub:

    python manage.py seed_about_qa_articles

Idempotent: matches on exact title, or on ``former_titles`` when a seed
article was renamed (updates in place so ``/qa/<id>/`` stays stable).
Articles are Public (user_restriction_level NULL) so anonymous users can read them.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from assessment_tool.about import ABOUT_ARTICLE_TITLES
from assessment_tool.about_qa_articles import iter_article_specs
from assessment_tool.help_qa import create_article, delete_article, update_article
from assessment_tool.models import QA


class Command(BaseCommand):
    help = (
        "Create or update the public About-linked Q&A feature articles "
        "(restriction Public / NULL)."
    )

    def handle(self, *args, **options):
        expected = set(ABOUT_ARTICLE_TITLES)
        seen = set()
        created = 0
        updated = 0
        removed_orphans = 0

        for spec in iter_article_specs():
            title = spec["title"]
            former_titles = tuple(spec.get("former_titles") or ())
            seen.add(title)
            tags_raw = ", ".join(spec["tags"])

            existing = (
                QA.objects.filter(title=title).order_by("id").first()
            )
            if existing is None and former_titles:
                existing = (
                    QA.objects.filter(title__in=former_titles)
                    .order_by("id")
                    .first()
                )

            if existing is None:
                article = create_article(
                    title=title,
                    content=spec["body"],
                    restriction="",
                    tags_raw=tags_raw,
                )
                created += 1
                self.stdout.write(
                    self.style.SUCCESS(f"Created id={article.id}: {title}")
                )
            else:
                old_title = existing.title
                article = update_article(
                    existing,
                    title=title,
                    content=spec["body"],
                    restriction="",
                    tags_raw=tags_raw,
                )
                updated += 1
                if old_title != title:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Updated id={article.id}: renamed "
                            f"{old_title!r} → {title!r}"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f"Updated id={article.id}: {title}")
                    )

            # If a rename left a duplicate under a former title, remove it.
            if former_titles:
                orphans = QA.objects.filter(title__in=former_titles).exclude(
                    pk=article.pk
                )
                for orphan in orphans:
                    orphan_id = orphan.pk
                    orphan_title = orphan.title
                    delete_article(orphan)
                    removed_orphans += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Removed orphan id={orphan_id}: {orphan_title!r}"
                        )
                    )

        missing_specs = expected - seen
        if missing_specs:
            self.stdout.write(
                self.style.ERROR(
                    "Specs missing for titles: " + "; ".join(sorted(missing_specs))
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. created={created} updated={updated} "
                f"removed_orphans={removed_orphans} total_specs={len(seen)}"
            )
        )
