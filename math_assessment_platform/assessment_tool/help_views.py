"""Public Q&A pages and IT admin CRUD."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .help_qa import (
    RESTRICTION_CHOICES,
    article_is_visible,
    browse_all,
    browse_all_admin,
    browse_by_tag,
    content_format,
    content_for_editor,
    create_article,
    decode_content_body,
    delete_article,
    matched_tags_for_query,
    record_article_view,
    render_content_html,
    restriction_label,
    search_by_content,
    search_by_tags,
    search_by_titles,
    serialize_admin_article_result,
    serialize_article_result,
    tags_for_article,
    tags_for_articles,
    update_article,
    visible_qa_queryset,
)
from .models import QA


def _is_it_support(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "user_type", None) == "IT_Support"
    )


def _parse_exclude_ids(raw: str) -> list[int]:
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def _results_payload(articles, *, q: str, match_stage: str, tag_mode: str | None = None):
    tag_map = tags_for_articles([a.id for a in articles])
    results = []
    for article in articles:
        all_tags = tag_map.get(article.id, [])
        if tag_mode:
            matched = [t for t in all_tags if t.lower() == tag_mode.lower()] or all_tags
        elif q:
            matched = matched_tags_for_query(article.id, q, all_tags)
        else:
            matched = all_tags
        results.append(
            serialize_article_result(
                article,
                all_tags=all_tags,
                matched_tags=matched,
                match_stage=match_stage,
            )
        )
    return results


@require_GET
def help_view(request):
    return render(
        request,
        "assessment_tool/help.html",
        {
            "initial_tag": (request.GET.get("tag") or "").strip(),
            "initial_q": (request.GET.get("q") or "").strip(),
            "search_api_url": reverse("qa_search_api"),
        },
    )


@require_GET
def help_search_api(request):
    qs = visible_qa_queryset(request)
    tag = (request.GET.get("tag") or "").strip()
    q = (request.GET.get("q") or "").strip()
    stage = (request.GET.get("stage") or "").strip().lower()
    exclude_ids = _parse_exclude_ids(request.GET.get("exclude_ids") or "")

    if tag:
        articles = list(browse_by_tag(qs, tag))
        return JsonResponse(
            {
                "mode": "tag",
                "tag": tag,
                "stage": "tag",
                "results": _results_payload(
                    articles, q="", match_stage="tag", tag_mode=tag
                ),
            }
        )

    if not q:
        # Default browse: all visible, most viewed first (single stage).
        if stage and stage not in ("browse", "all", ""):
            return JsonResponse({"mode": "browse", "stage": stage, "results": []})
        articles = list(browse_all(qs))
        return JsonResponse(
            {
                "mode": "browse",
                "stage": "browse",
                "results": _results_payload(articles, q="", match_stage="browse"),
            }
        )

    if stage == "tags":
        articles = list(search_by_tags(qs, q, exclude_ids=exclude_ids))
        return JsonResponse(
            {
                "mode": "search",
                "stage": "tags",
                "q": q,
                "results": _results_payload(articles, q=q, match_stage="tags"),
            }
        )
    if stage == "titles":
        articles = list(search_by_titles(qs, q, exclude_ids=exclude_ids))
        return JsonResponse(
            {
                "mode": "search",
                "stage": "titles",
                "q": q,
                "results": _results_payload(articles, q=q, match_stage="titles"),
            }
        )
    if stage == "content":
        articles = list(search_by_content(qs, q, exclude_ids=exclude_ids))
        return JsonResponse(
            {
                "mode": "search",
                "stage": "content",
                "q": q,
                "results": _results_payload(articles, q=q, match_stage="content"),
            }
        )

    return JsonResponse(
        {"error": "Invalid stage. Use tags, titles, content, or tag=."},
        status=400,
    )


@require_GET
def help_detail_view(request, article_id):
    article = get_object_or_404(QA, pk=article_id)
    if not article_is_visible(article, request):
        raise Http404("Q&A article not found.")
    record_article_view(article)
    tags = tags_for_article(article)
    return render(
        request,
        "assessment_tool/help_detail.html",
        {
            "article": article,
            "tags": tags,
            "content_html": render_content_html(article.answer),
            "restriction_label": restriction_label(article.user_restriction_level),
        },
    )


def _admin_results_payload(
    articles, *, q: str, match_stage: str, tag_mode: str | None = None
):
    tag_map = tags_for_articles([a.id for a in articles])
    results = []
    for article in articles:
        all_tags = tag_map.get(article.id, [])
        if tag_mode:
            matched = [t for t in all_tags if t.lower() == tag_mode.lower()] or all_tags
        elif q:
            matched = matched_tags_for_query(article.id, q, all_tags)
        else:
            matched = all_tags
        results.append(
            serialize_admin_article_result(
                article,
                all_tags=all_tags,
                matched_tags=matched,
                match_stage=match_stage,
            )
        )
    return results


@login_required
@user_passes_test(_is_it_support, login_url="/dashboard/")
@require_http_methods(["GET", "POST"])
def help_admin_view(request):
    if request.method == "POST":
        action = request.POST.get("action") or "create"
        if action == "create":
            try:
                article = create_article(
                    title=request.POST.get("title") or "",
                    content=request.POST.get("content") or "",
                    restriction=request.POST.get("restriction") or "",
                    tags_raw=request.POST.get("tags") or "",
                )
                messages.success(request, f"Created Q&A article “{article.title}”.")
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect("qa_admin")

    return render(
        request,
        "assessment_tool/help_admin.html",
        {
            "restriction_choices": RESTRICTION_CHOICES,
            "admin_search_api_url": reverse("qa_admin_search_api"),
        },
    )


@login_required
@user_passes_test(_is_it_support, login_url="/dashboard/")
@require_GET
def help_admin_search_api(request):
    """IT-only search over all Q&A articles (no public tier filter)."""
    qs = QA.objects.all()
    tag = (request.GET.get("tag") or "").strip()
    q = (request.GET.get("q") or "").strip()
    stage = (request.GET.get("stage") or "").strip().lower()
    exclude_ids = _parse_exclude_ids(request.GET.get("exclude_ids") or "")

    if tag:
        articles = list(browse_by_tag(qs, tag))
        return JsonResponse(
            {
                "mode": "tag",
                "tag": tag,
                "stage": "tag",
                "results": _admin_results_payload(
                    articles, q="", match_stage="tag", tag_mode=tag
                ),
            }
        )

    if not q:
        if stage and stage not in ("browse", "all", ""):
            return JsonResponse({"mode": "browse", "stage": stage, "results": []})
        articles = list(browse_all_admin(qs))
        return JsonResponse(
            {
                "mode": "browse",
                "stage": "browse",
                "results": _admin_results_payload(
                    articles, q="", match_stage="browse"
                ),
            }
        )

    if stage == "tags":
        articles = list(search_by_tags(qs, q, exclude_ids=exclude_ids))
        return JsonResponse(
            {
                "mode": "search",
                "stage": "tags",
                "q": q,
                "results": _admin_results_payload(articles, q=q, match_stage="tags"),
            }
        )
    if stage == "titles":
        articles = list(search_by_titles(qs, q, exclude_ids=exclude_ids))
        return JsonResponse(
            {
                "mode": "search",
                "stage": "titles",
                "q": q,
                "results": _admin_results_payload(articles, q=q, match_stage="titles"),
            }
        )
    if stage == "content":
        articles = list(search_by_content(qs, q, exclude_ids=exclude_ids))
        return JsonResponse(
            {
                "mode": "search",
                "stage": "content",
                "q": q,
                "results": _admin_results_payload(articles, q=q, match_stage="content"),
            }
        )

    return JsonResponse(
        {"error": "Invalid stage. Use tags, titles, content, or tag=."},
        status=400,
    )


@login_required
@user_passes_test(_is_it_support, login_url="/dashboard/")
@require_http_methods(["GET", "POST"])
def help_admin_edit_view(request, article_id):
    article = get_object_or_404(QA, pk=article_id)
    if request.method == "POST":
        action = request.POST.get("action") or "update"
        if action == "delete":
            title = article.title
            delete_article(article)
            messages.success(request, f"Deleted Q&A article “{title}”.")
            return redirect("qa_admin")
        try:
            update_article(
                article,
                title=request.POST.get("title") or "",
                content=request.POST.get("content") or "",
                restriction=request.POST.get("restriction") or "",
                tags_raw=request.POST.get("tags") or "",
            )
            messages.success(request, "Q&A article updated.")
            return redirect("qa_admin_edit", article_id=article.id)
        except ValueError as exc:
            messages.error(request, str(exc))

    tags = tags_for_article(article)
    return render(
        request,
        "assessment_tool/help_admin_edit.html",
        {
            "article": article,
            "content_body": content_for_editor(article.answer),
            "content_format": content_format(article.answer),
            "tags_value": ", ".join(t.name for t in tags),
            "restriction_choices": RESTRICTION_CHOICES,
            "restriction_value": article.user_restriction_level or "",
            "restriction_label": restriction_label(article.user_restriction_level),
        },
    )


@login_required
@user_passes_test(_is_it_support, login_url="/dashboard/")
@require_POST
def help_admin_delete_api(request, article_id):
    """IT-only JSON delete for the admin article list."""
    article = get_object_or_404(QA, pk=article_id)
    title = article.title or "(untitled)"
    delete_article(article)
    return JsonResponse({"success": True, "id": article_id, "title": title})
