"""About page helpers: canonical public Q&A titles and link resolution."""

from __future__ import annotations

from django.shortcuts import render
from django.urls import reverse

from .models import QA

# Exact titles used by seed_about_qa_articles and About page links (max 150 chars).
TITLE_MAP_AND_FLIPPEDMATH = "MAP and flippedmath.com"
TITLE_AUTHORING = "Authoring dynamic math problems in MAP"
TITLE_BLUEPRINTS = "Assessment blueprints: sections and randomized problem sets"
TITLE_PRACTICE_TEST = "Practice tests before students see an assessment"
TITLE_SYNC_PRINT = (
    "Synchronized forms, unique instances, and printable match-key answer keys"
)
TITLE_FOCUS_LOCK = "Focus lock and live teacher unlock"
TITLE_WINDOWS_TIMERS = "Assessment windows, timers, and autosave"
TITLE_HYBRID_GRADING = "Hybrid auto-grading and grading at scale"
TITLE_GRADES_CONTROL = "Grades control: weights, curves, retakes, and score release"
TITLE_EXPLORER = "Explorer, collaboration, and the Public Library"
TITLE_CREDITS = "Seat credits, course unlock, and student invites"
TITLE_ROLES = "Co-teachers, parents, and course roles"
TITLE_DATA_PRIVACY = "Data privacy: how MAP handles school and student information"

ABOUT_ARTICLE_TITLES = (
    TITLE_MAP_AND_FLIPPEDMATH,
    TITLE_AUTHORING,
    TITLE_BLUEPRINTS,
    TITLE_PRACTICE_TEST,
    TITLE_SYNC_PRINT,
    TITLE_FOCUS_LOCK,
    TITLE_WINDOWS_TIMERS,
    TITLE_HYBRID_GRADING,
    TITLE_GRADES_CONTROL,
    TITLE_EXPLORER,
    TITLE_CREDITS,
    TITLE_ROLES,
    TITLE_DATA_PRIVACY,
)

# About page claim blocks: short copy + canonical article title.
ABOUT_CLAIM_BLOCKS = (
    {
        "key": "authoring",
        "title": "Author once, generate many",
        "body": (
            "Build dynamic math problems with linked variables and answer fields. "
            "One authored problem can produce many valid instances with auto-checkable answers."
        ),
        "article_title": TITLE_AUTHORING,
    },
    {
        "key": "blueprints",
        "title": "Structured blueprints",
        "body": (
            "Assessments are sectioned blueprints with optional randomized problem banks—"
            "not a flat quiz list."
        ),
        "article_title": TITLE_BLUEPRINTS,
    },
    {
        "key": "practice",
        "title": "Practice before go-live",
        "body": (
            "Generate and take a private practice instance from setup so you catch issues "
            "before students ever see the assessment."
        ),
        "article_title": TITLE_PRACTICE_TEST,
    },
    {
        "key": "fairness",
        "title": "Fairness you can choose",
        "body": (
            "Run a synchronized class form or unique per-student instances. Print a frozen "
            "paper version with a matching answer key when you need it."
        ),
        "article_title": TITLE_SYNC_PRINT,
    },
    {
        "key": "integrity",
        "title": "Integrity without spyware",
        "body": (
            "Focus-leave lock pauses an attempt when a student leaves the tab, with live "
            "teacher unlock from the dashboard—no third-party lockdown browser required."
        ),
        "article_title": TITLE_FOCUS_LOCK,
    },
    {
        "key": "delivery",
        "title": "Windows, timers, and autosave",
        "body": (
            "Control when assessments open and close, choose timer modes, and rely on "
            "autosave while students work."
        ),
        "article_title": TITLE_WINDOWS_TIMERS,
    },
    {
        "key": "grading",
        "title": "Grading that scales",
        "body": (
            "Auto-grade what can be checked automatically, then finish open-ended work with "
            "manual and question-batch grading tools."
        ),
        "article_title": TITLE_HYBRID_GRADING,
    },
    {
        "key": "policies",
        "title": "Policy control for grades",
        "body": (
            "Set weights, curves, retake rules, and how scores are released to students—"
            "including individual retake grants."
        ),
        "article_title": TITLE_GRADES_CONTROL,
    },
    {
        "key": "explorer",
        "title": "A content workspace for departments",
        "body": (
            "Organize courses and problems in a finder-style Explorer, share with "
            "collaborators, browse the Public Library, and copy into your Workspace."
        ),
        "article_title": TITLE_EXPLORER,
    },
    {
        "key": "credits",
        "title": "Seat credits and invites",
        "body": (
            "Credits unlock inviting students and related classroom capacity. Each invite "
            "spends a seat token, with reimbursement rules for early removals."
        ),
        "article_title": TITLE_CREDITS,
    },
    {
        "key": "roles",
        "title": "Co-teachers, parents, and roles",
        "body": (
            "Invite co-teachers, grant parents grade visibility, and manage course "
            "lifecycle from developing draft through closed archive."
        ),
        "article_title": TITLE_ROLES,
    },
    {
        "key": "privacy",
        "title": "Built with school data privacy in mind",
        "body": (
            "Role-scoped access, invite-based enrollment, teacher-controlled score release, "
            "and course-limited parent grade links—without selling student data for ads."
        ),
        "article_title": TITLE_DATA_PRIVACY,
    },
)


def public_article_by_title(title: str) -> QA | None:
    """Return a public (unrestricted) Q&A row with this exact title, if any."""
    title = (title or "").strip()
    if not title:
        return None
    return (
        QA.objects.filter(title=title, user_restriction_level__isnull=True)
        .order_by("id")
        .first()
    )


def article_url_for_title(title: str, *, fallback: str | None = None) -> str:
    """Detail URL for a seeded public article, or fallback (default: Q&A index)."""
    article = public_article_by_title(title)
    if article is not None:
        return reverse("qa_detail", kwargs={"article_id": article.id})
    return fallback if fallback is not None else reverse("qa")


def about_page_context() -> dict:
    """Template context for the About hub."""
    claims = []
    for block in ABOUT_CLAIM_BLOCKS:
        claims.append(
            {
                **block,
                "learn_more_url": article_url_for_title(block["article_title"]),
            }
        )
    return {
        "about_claims": claims,
        "flippedmath_article_url": article_url_for_title(TITLE_MAP_AND_FLIPPEDMATH),
        "qa_index_url": reverse("qa"),
    }


def about_view(request):
    """Public About page: short claims linking to public Q&A articles."""
    return render(request, "assessment_tool/about.html", about_page_context())
