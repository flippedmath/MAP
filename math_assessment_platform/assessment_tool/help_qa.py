"""Help / Q&A article helpers: visibility, tags, view counts, staged search."""

from __future__ import annotations

import logging
import re
from html import escape as html_escape
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import parse_qs, urlparse

from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.html import escape, strip_tags
from django.utils.safestring import mark_safe

from .models import QA, QaTag, QaTagAssignment

logger = logging.getLogger(__name__)

RESTRICTION_RANK = {
    None: 0,
    "": 0,
    "Parent": 1,
    "Student": 2,
    "Teacher": 3,
    "IT_Support": 4,
}

RESTRICTION_CHOICES = (
    ("", "Public"),
    ("Parent", "Parent"),
    ("Student", "Student"),
    ("Teacher", "Teacher"),
    ("IT_Support", "IT Support"),
)

PAGE_SIZE = 10

_ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "ul",
        "ol",
        "li",
        "a",
        "iframe",
        "div",
        "h2",
        "h3",
        "h4",
    }
)
_ALLOWED_ATTRS = {
    "a": {"href", "title", "rel", "target"},
    "iframe": {"src", "title", "allow", "allowfullscreen", "frameborder", "loading"},
    "div": {"class"},
}
_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HREF_RE = re.compile(
    r"""<a\s+[^>]*href=["']([^"']+)["'][^>]*>.*?</a>""",
    re.I | re.S,
)
_BARE_YOUTUBE_RE = re.compile(
    r"(?<![\"\'=])(https?://(?:www\.)?(?:youtube\.com/(?:watch\?[^\s<\"']+|embed/[\w-]{11}|shorts/[\w-]{11})|youtu\.be/[\w-]{11}))",
    re.I,
)


def viewer_rank(user) -> int:
    if user is None or not getattr(user, "is_authenticated", False):
        return 0
    return RESTRICTION_RANK.get(getattr(user, "user_type", None), 0)


def restriction_rank(level) -> int:
    if level is None or level == "":
        return 0
    return RESTRICTION_RANK.get(level, 0)


def visible_levels_for_rank(rank: int) -> list:
    """Restriction values a viewer of this rank may see (including public/null)."""
    levels = [None]
    for name, value in RESTRICTION_RANK.items():
        if name and value <= rank:
            levels.append(name)
    return levels


def visible_qa_queryset(request) -> QuerySet:
    rank = viewer_rank(getattr(request, "user", None))
    levels = visible_levels_for_rank(rank)
    # null = public; named tiers at or below viewer rank (enum cannot be '')
    named = [lvl for lvl in levels if lvl]
    q = Q(user_restriction_level__isnull=True)
    if named:
        q |= Q(user_restriction_level__in=named)
    return QA.objects.filter(q)


def article_is_visible(article: QA, request) -> bool:
    return restriction_rank(article.user_restriction_level) <= viewer_rank(
        getattr(request, "user", None)
    )


def content_format(answer) -> str:
    if isinstance(answer, dict):
        fmt = (answer.get("format") or "").strip().lower()
        if fmt in ("html", "rich", "plain"):
            return fmt
    body = decode_content_body(answer)
    if re.search(r"</?(p|strong|em|u|ul|ol|li|a|br)\b", body, re.I):
        return "html"
    return "plain"


def youtube_video_id(url: str) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    if host in ("youtu.be", "www.youtu.be"):
        candidate = path.strip("/").split("/")[0]
    elif "youtube.com" in host or "youtube-nocookie.com" in host:
        if path.startswith("/embed/") or path.startswith("/shorts/"):
            candidate = path.strip("/").split("/")[1] if "/" in path.strip("/") else ""
        elif path.startswith("/watch"):
            candidate = (parse_qs(parsed.query).get("v") or [None])[0] or ""
        else:
            candidate = ""
    else:
        return None
    if candidate and _YOUTUBE_ID_RE.match(candidate):
        return candidate
    return None


def youtube_embed_html(video_id: str) -> str:
    src = f"https://www.youtube-nocookie.com/embed/{video_id}"
    return (
        f'<div class="help-youtube">'
        f'<iframe src="{src}" title="YouTube video" loading="lazy" '
        f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" '
        f'allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe>'
        f"</div>"
    )


def _is_safe_href(href: str) -> bool:
    value = (href or "").strip()
    if not value:
        return False
    lower = value.lower()
    if lower.startswith(("http://", "https://", "mailto:")):
        return True
    if lower.startswith(("/", "#")):
        return True
    return False


def _is_safe_youtube_embed_src(src: str) -> bool:
    try:
        parsed = urlparse((src or "").strip())
    except Exception:
        return False
    host = (parsed.netloc or "").lower()
    if host not in ("www.youtube.com", "youtube.com", "www.youtube-nocookie.com", "youtube-nocookie.com"):
        return False
    parts = [p for p in (parsed.path or "").split("/") if p]
    if len(parts) != 2 or parts[0] != "embed":
        return False
    return bool(_YOUTUBE_ID_RE.match(parts[1]))


class _HelpHTMLSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag not in _ALLOWED_TAGS:
            return
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        allowed = _ALLOWED_ATTRS.get(tag, set())
        kept = []
        if tag == "a":
            href = attr_map.get("href", "")
            if not _is_safe_href(href):
                return
            kept.append(("href", href))
            kept.append(("rel", "noopener noreferrer"))
            kept.append(("target", "_blank"))
        elif tag == "iframe":
            src = attr_map.get("src", "")
            if not _is_safe_youtube_embed_src(src):
                return
            kept.append(("src", src))
            kept.append(("title", attr_map.get("title") or "YouTube video"))
            kept.append(("loading", "lazy"))
            kept.append(("allowfullscreen", "allowfullscreen"))
            kept.append(
                (
                    "allow",
                    "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share",
                )
            )
        elif tag == "div":
            cls = attr_map.get("class", "")
            if cls == "help-youtube":
                kept.append(("class", "help-youtube"))
            # skip unknown divs but still open containerless? skip entirely
            elif cls:
                return
        # void / normal
        if tag == "br":
            self._out.append("<br>")
            return
        attr_html = "".join(f' {k}="{html_escape(v, quote=True)}"' for k, v in kept)
        self._out.append(f"<{tag}{attr_html}>")
        self._stack.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "br" or tag not in _ALLOWED_TAGS:
            return
        if tag in self._stack:
            # close until matching
            while self._stack:
                top = self._stack.pop()
                self._out.append(f"</{top}>")
                if top == tag:
                    break

    def handle_data(self, data):
        if data:
            self._out.append(escape(data))

    def handle_entityref(self, name):
        self._out.append(f"&{name};")

    def handle_charref(self, name):
        self._out.append(f"&#{name};")

    def get_html(self) -> str:
        while self._stack:
            self._out.append(f"</{self._stack.pop()}>")
        return "".join(self._out)


def sanitize_help_html(raw_html: str) -> str:
    parser = _HelpHTMLSanitizer()
    try:
        parser.feed(raw_html or "")
        parser.close()
    except Exception:
        logger.exception("Failed to sanitize help HTML")
        return escape(strip_tags(raw_html or ""))
    return parser.get_html().strip()


def _embed_youtube_in_html(html: str) -> str:
    text = html or ""

    def replace_anchor(match: re.Match) -> str:
        href = match.group(1)
        vid = youtube_video_id(href)
        if not vid:
            return match.group(0)
        return youtube_embed_html(vid)

    text = _YOUTUBE_HREF_RE.sub(replace_anchor, text)

    def replace_bare(match: re.Match) -> str:
        url = match.group(1)
        # Skip if already inside an iframe src= just before (rough guard)
        start = match.start()
        window = text[max(0, start - 40) : start].lower()
        if "src=" in window or "<iframe" in window:
            return url
        vid = youtube_video_id(url)
        if not vid:
            return url
        return youtube_embed_html(vid)

    text = _BARE_YOUTUBE_RE.sub(replace_bare, text)
    return text


def is_blank_help_content(raw: str) -> bool:
    text = strip_tags(raw or "").replace("\xa0", " ").strip()
    if text:
        return False
    # Embed-only articles still count as content.
    return "help-youtube" not in (raw or "") and "<iframe" not in (raw or "").lower()


def encode_content(body: str) -> dict:
    raw = body or ""
    if is_blank_help_content(raw):
        raise ValueError("Content is required.")
    # Plain text without tags → store as escaped paragraphs for rich pipeline
    if not re.search(r"<[a-zA-Z]", raw):
        paragraphs = []
        for block in re.split(r"\n\s*\n", raw.strip()):
            lines = escape(block).replace("\n", "<br>\n")
            paragraphs.append(f"<p>{lines}</p>")
        html = "".join(paragraphs) or f"<p>{escape(raw)}</p>"
    else:
        html = raw
    cleaned = sanitize_help_html(html)
    cleaned = _embed_youtube_in_html(cleaned)
    cleaned = sanitize_help_html(cleaned)  # re-check iframes inserted
    if is_blank_help_content(cleaned):
        raise ValueError("Content is required.")
    return {"format": "html", "body": cleaned}


def decode_content_body(answer) -> str:
    if answer is None:
        return ""
    if isinstance(answer, str):
        return answer
    if isinstance(answer, dict):
        body = answer.get("body")
        if body is None:
            return ""
        return str(body)
    return str(answer)


def content_plain_preview(answer, limit: int = 160) -> str:
    body = decode_content_body(answer)
    if content_format(answer) == "plain" and not re.search(r"<[a-zA-Z]", body):
        text = body
    else:
        text = strip_tags(body)
    text = " ".join(text.replace("\xa0", " ").split())
    return text[:limit]


def render_content_html(answer) -> str:
    body = decode_content_body(answer)
    fmt = content_format(answer)
    if fmt == "plain" and not re.search(r"<[a-zA-Z]", body):
        return mark_safe(escape(body).replace("\n", "<br>\n"))
    cleaned = sanitize_help_html(body)
    cleaned = _embed_youtube_in_html(cleaned)
    cleaned = sanitize_help_html(cleaned)
    return mark_safe(cleaned)


def content_for_editor(answer) -> str:
    """HTML suitable for Quill: turn stored YouTube embeds back into links."""
    body = decode_content_body(answer)
    body = re.sub(
        r'<div\s+class="help-youtube"\s*>\s*<iframe[^>]+src="https://www\.youtube(?:-nocookie)?\.com/embed/([A-Za-z0-9_-]{11})"[^>]*>.*?</iframe>\s*</div>',
        r'<p><a href="https://youtu.be/\1">https://youtu.be/\1</a></p>',
        body,
        flags=re.I | re.S,
    )
    return body


def normalize_tag_name(raw: str) -> str:
    cleaned = " ".join((raw or "").strip().split())
    return cleaned[:64]


def parse_tags_input(raw: str) -> list[str]:
    """Split comma-separated tags; normalize; drop empties; preserve order unique."""
    seen = set()
    out = []
    for part in (raw or "").split(","):
        name = normalize_tag_name(part)
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def tags_for_article(qa: QA) -> list[QaTag]:
    return list(
        QaTag.objects.filter(article_assignments__qa=qa).order_by(Lower("name"))
    )


def tags_for_articles(article_ids: Iterable[int]) -> dict[int, list[str]]:
    ids = list(article_ids)
    if not ids:
        return {}
    rows = (
        QaTagAssignment.objects.filter(qa_id__in=ids)
        .select_related("tag")
        .order_by(Lower("tag__name"))
    )
    mapping: dict[int, list[str]] = {i: [] for i in ids}
    for row in rows:
        mapping.setdefault(row.qa_id, []).append(row.tag.name)
    return mapping


@transaction.atomic
def set_article_tags(qa: QA, raw_tags) -> list[str]:
    if isinstance(raw_tags, str):
        names = parse_tags_input(raw_tags)
    else:
        names = []
        seen = set()
        for item in raw_tags or []:
            name = normalize_tag_name(str(item))
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(name)

    QaTagAssignment.objects.filter(qa=qa).delete()
    for name in names:
        tag = (
            QaTag.objects.annotate(name_lower=Lower("name"))
            .filter(name_lower=name.lower())
            .first()
        )
        if tag is None:
            tag = QaTag.objects.create(name=name)
        QaTagAssignment.objects.get_or_create(qa=qa, tag=tag)
    return names


def record_article_view(qa: QA) -> None:
    QA.objects.filter(pk=qa.pk).update(view_count=F("view_count") + 1)
    qa.view_count = (qa.view_count or 0) + 1


def _exclude_ids(qs: QuerySet, exclude_ids: Iterable[int] | None) -> QuerySet:
    ids = [int(x) for x in (exclude_ids or []) if str(x).isdigit() or isinstance(x, int)]
    if ids:
        return qs.exclude(pk__in=ids)
    return qs


def search_by_tags(qs: QuerySet, q: str, exclude_ids=None) -> QuerySet:
    term = (q or "").strip()
    if not term:
        return qs.none()
    matched_ids = (
        QaTagAssignment.objects.filter(tag__name__icontains=term)
        .values_list("qa_id", flat=True)
        .distinct()
    )
    return _exclude_ids(qs.filter(pk__in=matched_ids), exclude_ids).order_by(
        "-view_count", "id"
    )


def search_by_titles(qs: QuerySet, q: str, exclude_ids=None) -> QuerySet:
    term = (q or "").strip()
    if not term:
        return qs.none()
    return _exclude_ids(qs.filter(title__icontains=term), exclude_ids).order_by(
        "-view_count", "id"
    )


def search_by_content(qs: QuerySet, q: str, exclude_ids=None) -> QuerySet:
    term = (q or "").strip()
    if not term:
        return qs.none()
    # Match plain-text body in JSON answer payload.
    filtered = qs.extra(
        where=["COALESCE(answer->>'body', answer::text) ILIKE %s"],
        params=[f"%{term}%"],
    )
    return _exclude_ids(filtered, exclude_ids).order_by("-view_count", "id")


def browse_by_tag(qs: QuerySet, tag_name: str) -> QuerySet:
    name = normalize_tag_name(tag_name)
    if not name:
        return qs.none()
    matched_ids = (
        QaTagAssignment.objects.filter(tag__name__iexact=name)
        .values_list("qa_id", flat=True)
        .distinct()
    )
    return qs.filter(pk__in=matched_ids).order_by("-view_count", "id")


def browse_all(qs: QuerySet) -> QuerySet:
    return qs.order_by("-view_count", "id")


def browse_all_admin(qs: QuerySet) -> QuerySet:
    """Admin list default: newest modifications first."""
    return qs.order_by("-modification_date", "-id")


def matched_tags_for_query(article_id: int, q: str, all_tags: list[str]) -> list[str]:
    term = (q or "").strip().lower()
    if not term:
        return []
    return [t for t in all_tags if term in t.lower()]


def serialize_article_result(
    article: QA,
    *,
    all_tags: list[str],
    matched_tags: list[str],
    match_stage: str,
) -> dict:
    return {
        "id": article.id,
        "title": article.title or "(untitled)",
        "view_count": article.view_count or 0,
        "restriction_label": restriction_label(article.user_restriction_level),
        "tags": all_tags,
        "matched_tags": matched_tags,
        "match_stage": match_stage,
        "detail_url": f"/qa/{article.id}/",
    }


def serialize_admin_article_result(
    article: QA,
    *,
    all_tags: list[str],
    matched_tags: list[str],
    match_stage: str,
) -> dict:
    preview = content_plain_preview(article.answer, 160)
    modified = article.modification_date
    return {
        "id": article.id,
        "title": article.title or "(untitled)",
        "view_count": article.view_count or 0,
        "restriction_label": restriction_label(article.user_restriction_level),
        "tags": all_tags,
        "matched_tags": matched_tags,
        "match_stage": match_stage,
        "content_preview": preview,
        "modification_date": (
            modified.strftime("%Y-%m-%d %H:%M") if modified is not None else "—"
        ),
        "detail_url": f"/qa/{article.id}/",
        "edit_url": f"/qa/admin/{article.id}/edit/",
    }


@transaction.atomic
def create_article(
    *,
    title: str,
    content: str,
    restriction: str | None,
    tags_raw: str,
) -> QA:
    title = (title or "").strip()[:150]
    if not title:
        raise ValueError("Title is required.")
    level = (restriction or "").strip() or None
    if level and level not in RESTRICTION_RANK:
        raise ValueError("Invalid user restriction level.")
    now = timezone.now()
    article = QA.objects.create(
        title=title,
        answer=encode_content(content),
        user_restriction_level=level,
        creation_date=now,
        modification_date=now,
        view_count=0,
    )
    set_article_tags(article, tags_raw)
    return article


@transaction.atomic
def update_article(
    article: QA,
    *,
    title: str,
    content: str,
    restriction: str | None,
    tags_raw: str,
) -> QA:
    title = (title or "").strip()[:150]
    if not title:
        raise ValueError("Title is required.")
    level = (restriction or "").strip() or None
    if level and level not in RESTRICTION_RANK:
        raise ValueError("Invalid user restriction level.")
    article.title = title
    article.answer = encode_content(content)
    article.user_restriction_level = level
    article.modification_date = timezone.now()
    article.save(
        update_fields=[
            "title",
            "answer",
            "user_restriction_level",
            "modification_date",
        ]
    )
    set_article_tags(article, tags_raw)
    return article


@transaction.atomic
def delete_article(article: QA) -> None:
    QaTagAssignment.objects.filter(qa=article).delete()
    article.delete()


def restriction_label(level) -> str:
    if not level:
        return "Public"
    for value, label in RESTRICTION_CHOICES:
        if value == level:
            return label
    return str(level)
