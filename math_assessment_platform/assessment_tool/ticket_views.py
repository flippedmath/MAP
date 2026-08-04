"""Public Contact Us and IT Tickets console views."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .dashboard import user_display_name
from .models import ContactUs, Ticket, UserProfile
from . import tickets as ticket_lib


def _is_it_support(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "user_type", None) == "IT_Support"
    )


it_required = user_passes_test(_is_it_support, login_url="/login/")


def _form_defaults_from_user(user):
    if not getattr(user, "is_authenticated", False):
        return {
            "first_name": "",
            "respond_to_email": "",
            "username_display": None,
        }
    return {
        "first_name": (getattr(user, "user_first_name", None) or "").strip(),
        "respond_to_email": (getattr(user, "user_email", None) or "").strip(),
        "username_display": getattr(user, "username", None),
    }


def _serialize_discussion(row):
    return {
        "id": row.id,
        "email": row.commentor_email,
        "is_system": bool(row.is_system),
        "created": row.creation_date,
        "body_html": mark_safe(ticket_lib.comment_html(row.comment)),
        "author": (
            getattr(row.author_user, "username", None) if row.author_user_id else None
        ),
    }


@require_http_methods(["GET", "POST"])
def contact_us_view(request):
    defaults = _form_defaults_from_user(request.user)
    form = {
        "subject": "",
        "contact_purpose": "",
        "first_name": defaults["first_name"],
        "respond_to_email": defaults["respond_to_email"],
        "inquiry": "",
    }
    if request.method == "POST":
        form = {
            "subject": (request.POST.get("subject") or "").strip(),
            "contact_purpose": (request.POST.get("contact_purpose") or "").strip(),
            "first_name": (request.POST.get("first_name") or "").strip(),
            "respond_to_email": (request.POST.get("respond_to_email") or "").strip(),
            "inquiry": (request.POST.get("inquiry") or "").strip(),
        }
        try:
            ticket_lib.create_contact_us(
                subject=form["subject"],
                contact_purpose=form["contact_purpose"],
                first_name=form["first_name"],
                respond_to_email=form["respond_to_email"],
                inquiry=form["inquiry"],
                user=request.user if request.user.is_authenticated else None,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        else:
            messages.success(
                request,
                "Thanks — your message was received. IT Support will follow up.",
            )
            return redirect("contact_us")

    login_next = reverse("contact_us")
    return render(
        request,
        "assessment_tool/contact_us.html",
        {
            "form": form,
            "purposes": ticket_lib.CONTACT_PURPOSES,
            "username_display": defaults["username_display"],
            "is_authenticated": request.user.is_authenticated,
            "login_url": f"{reverse('login')}?next={login_next}",
            "max_subject": ticket_lib.MAX_SUBJECT,
            "max_first_name": ticket_lib.MAX_FIRST_NAME,
            "max_email": ticket_lib.MAX_EMAIL,
            "max_body": ticket_lib.MAX_BODY,
        },
    )


@it_required
@require_http_methods(["GET", "POST"])
def tickets_admin_view(request):
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "save_filter_defaults":
            filters = ticket_lib.filters_from_request_get(request.POST)
            ticket_lib.save_ticket_filter_defaults(
                user=request.user, filters=filters
            )
            messages.success(request, "Saved current filters as your default.")
            q = QueryDict(mutable=True)
            for key, value in filters.items():
                if value:
                    q[key] = value
            # Always keep sort/dir in the URL after save for a stable view.
            q["sort"] = filters.get("sort") or "last_activity"
            q["dir"] = filters.get("dir") or "desc"
            return redirect(f"{reverse('tickets_admin')}?{q.urlencode()}")
        if action == "clear_filter_defaults":
            ticket_lib.clear_ticket_filter_defaults(request.user)
            messages.success(request, "Cleared your saved filter defaults.")
            return redirect("tickets_admin")
        messages.error(request, "Unknown action.")
        return redirect("tickets_admin")

    saved_defaults = ticket_lib.get_ticket_filter_defaults(request.user)
    using_saved_defaults = False
    if request.GET:
        filters = ticket_lib.filters_from_request_get(request.GET)
    elif saved_defaults is not None:
        filters = saved_defaults
        using_saved_defaults = True
    else:
        filters = dict(ticket_lib.BUILTIN_FILTER_DEFAULTS)

    contacts = (
        ContactUs.objects.select_related("username")
        .order_by("-creation_date", "-id")
    )
    tickets_qs = Ticket.objects.select_related("username", "assigned_to")
    tickets_qs = ticket_lib.filter_tickets_queryset(tickets_qs, filters)
    ticket_rows = []
    for t in tickets_qs[:200]:
        ticket_rows.append(
            {
                "ticket": t,
                "purpose_label": ticket_lib.purpose_label(t.contact_purpose),
                "status_label": ticket_lib.status_label(t.status),
                "priority_label": ticket_lib.priority_label(t.priority),
                "requester": (
                    t.username.username if t.username_id else "—"
                ),
                "assignee": (
                    t.assigned_to.username if t.assigned_to_id else "—"
                ),
                "client_url": ticket_lib.ticket_client_path(t),
            }
        )
    contact_rows = []
    for c in contacts[:100]:
        contact_rows.append(
            {
                "contact": c,
                "purpose_label": ticket_lib.purpose_label(c.contact_purpose),
                "requester": (
                    c.username.username if c.username_id else "—"
                ),
            }
        )
    return render(
        request,
        "assessment_tool/tickets_admin.html",
        {
            "contact_rows": contact_rows,
            "ticket_rows": ticket_rows,
            "it_users": ticket_lib.it_support_users(),
            "statuses": ticket_lib.TICKET_STATUSES,
            "priorities": ticket_lib.TICKET_PRIORITIES,
            "purposes": ticket_lib.CONTACT_PURPOSES,
            "filters": filters,
            "has_saved_filter_defaults": saved_defaults is not None,
            "using_saved_filter_defaults": using_saved_defaults,
            "save_filter_defaults_url": reverse("tickets_admin"),
        },
    )


@it_required
@require_GET
def ticket_user_lookup_api(request):
    """Resolve username/email to a user profile for New ticket autofill."""
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse(
            {"found": False, "error": "Type at least 2 characters."}
        )
    user = UserProfile.objects.filter(
        Q(username__iexact=q) | Q(user_email__iexact=q)
    ).first()
    if user is None:
        return JsonResponse(
            {"found": False, "error": f"No account matches “{q}”."}
        )
    first_name = (user.user_first_name or "").strip()
    if not first_name:
        # Fall back so the required ticket field can still be filled.
        first_name = (user.user_display_name or user.username or "").strip()
    return JsonResponse(
        {
            "found": True,
            "user_id": user.pk,
            "username": user.username or "",
            "email": user.user_email or "",
            "first_name": first_name,
            "display_name": user_display_name(user),
            "user_type": user.user_type or "",
        }
    )


@it_required
@require_http_methods(["GET", "POST"])
def ticket_create_view(request):
    form = {
        "title": "",
        "contact_purpose": "general_question",
        "first_name": "",
        "respond_to_email": "",
        "body": "",
        "priority": "normal",
        "assigned_to": "",
        "notify_client": False,
        "username_id": "",
        "client_lookup": "",
        "linked_username": "",
    }
    if request.method == "POST":
        form = {
            "title": (request.POST.get("title") or "").strip(),
            "contact_purpose": (request.POST.get("contact_purpose") or "").strip(),
            "first_name": (request.POST.get("first_name") or "").strip(),
            "respond_to_email": (request.POST.get("respond_to_email") or "").strip(),
            "body": (request.POST.get("body") or "").strip(),
            "priority": (request.POST.get("priority") or "normal").strip(),
            "assigned_to": (request.POST.get("assigned_to") or "").strip(),
            "notify_client": request.POST.get("notify_client") == "on",
            "username_id": (request.POST.get("username_id") or "").strip(),
            "client_lookup": (request.POST.get("client_lookup") or "").strip(),
            "linked_username": (request.POST.get("linked_username") or "").strip(),
        }
        username = None
        if form["username_id"].isdigit():
            username = UserProfile.objects.filter(pk=int(form["username_id"])).first()
            if username:
                form["linked_username"] = username.username or form["linked_username"]
        try:
            ticket = ticket_lib.create_ticket(
                title=form["title"],
                contact_purpose=form["contact_purpose"],
                first_name=form["first_name"],
                respond_to_email=form["respond_to_email"],
                body=form["body"],
                username=username,
                assigned_to=ticket_lib._resolve_assignee(form["assigned_to"]),
                priority=form["priority"],
                created_by=request.user,
                notify_client=form["notify_client"],
            )
        except ValidationError as exc:
            messages.error(
                request,
                "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc),
            )
        else:
            messages.success(request, f"Ticket #{ticket.id} created.")
            return redirect("ticket_admin_detail", ticket_id=ticket.id)

    return render(
        request,
        "assessment_tool/ticket_form.html",
        {
            "mode": "create",
            "form": form,
            "purposes": ticket_lib.CONTACT_PURPOSES,
            "priorities": ticket_lib.TICKET_PRIORITIES,
            "it_users": ticket_lib.it_support_users(),
            "max_subject": ticket_lib.MAX_SUBJECT,
            "max_first_name": ticket_lib.MAX_FIRST_NAME,
            "max_email": ticket_lib.MAX_EMAIL,
            "max_body": ticket_lib.MAX_BODY,
            "ticket_user_lookup_url": reverse("ticket_user_lookup"),
        },
    )


@it_required
@require_http_methods(["GET", "POST"])
def contact_convert_view(request, contact_id: int):
    contact = get_object_or_404(ContactUs.objects.select_related("username"), pk=contact_id)
    form = {
        "title": contact.subject,
        "contact_purpose": contact.contact_purpose,
        "priority": "normal",
        "assigned_to": "",
        "notify_client": False,
    }
    if request.method == "POST":
        form = {
            "title": (request.POST.get("title") or "").strip(),
            "contact_purpose": (request.POST.get("contact_purpose") or "").strip(),
            "priority": (request.POST.get("priority") or "normal").strip(),
            "assigned_to": (request.POST.get("assigned_to") or "").strip(),
            "notify_client": request.POST.get("notify_client") == "on",
        }
        try:
            ticket = ticket_lib.convert_contact_to_ticket(
                contact=contact,
                created_by=request.user,
                title=form["title"],
                contact_purpose=form["contact_purpose"],
                assigned_to_id=form["assigned_to"] or None,
                priority=form["priority"],
                notify_client=form["notify_client"],
            )
        except ValidationError as exc:
            messages.error(
                request,
                "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc),
            )
        else:
            messages.success(
                request,
                f"Ticket #{ticket.id} created from Contact Us (submission deleted).",
            )
            return redirect("ticket_admin_detail", ticket_id=ticket.id)

    return render(
        request,
        "assessment_tool/ticket_form.html",
        {
            "mode": "convert",
            "contact": contact,
            "form": form,
            "purposes": ticket_lib.CONTACT_PURPOSES,
            "priorities": ticket_lib.TICKET_PRIORITIES,
            "it_users": ticket_lib.it_support_users(),
            "max_subject": ticket_lib.MAX_SUBJECT,
            "max_first_name": ticket_lib.MAX_FIRST_NAME,
            "max_email": ticket_lib.MAX_EMAIL,
            "max_body": ticket_lib.MAX_BODY,
        },
    )


@it_required
@require_POST
def contact_delete_view(request, contact_id: int):
    contact = get_object_or_404(ContactUs, pk=contact_id)
    ticket_lib.delete_contact(contact)
    messages.success(request, "Contact Us submission deleted.")
    return redirect("tickets_admin")


@it_required
@require_http_methods(["GET", "POST"])
def ticket_admin_detail_view(request, ticket_id: int):
    ticket = get_object_or_404(
        Ticket.objects.select_related("username", "assigned_to"),
        pk=ticket_id,
    )
    if request.method == "GET":
        ticket_lib.clear_admin_unread(ticket)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        try:
            if action == "priority":
                ticket_lib.set_ticket_priority(
                    ticket=ticket,
                    priority=request.POST.get("priority") or "",
                    actor=request.user,
                )
                messages.success(request, "Priority updated.")
            elif action == "assign":
                ticket_lib.set_ticket_assignee(
                    ticket=ticket,
                    assigned_to_id=request.POST.get("assigned_to"),
                    actor=request.user,
                )
                messages.success(request, "Assignee updated.")
            elif action == "status":
                ticket_lib.set_ticket_status(
                    ticket=ticket,
                    status=request.POST.get("status") or "",
                    actor=request.user,
                )
                messages.success(request, "Status updated.")
            elif action == "comment":
                ticket_lib.add_admin_comment(
                    ticket=ticket,
                    actor=request.user,
                    body=request.POST.get("body") or "",
                    notify_client=request.POST.get("notify_client") == "on",
                )
                messages.success(request, "Comment posted.")
            elif action == "delete_comment":
                ticket_lib.delete_discussion_comment(
                    ticket=ticket,
                    discussion_id=request.POST.get("discussion_id"),
                    actor=request.user,
                )
                messages.success(request, "Comment deleted.")
            elif action == "notify":
                ticket_lib.notify_ticket_client(ticket=ticket, kind="ticket_updated")
                messages.success(request, "Client notification stub sent.")
            elif action == "delete":
                ticket_lib.delete_ticket(ticket)
                messages.success(request, "Ticket deleted.")
                return redirect("tickets_admin")
            else:
                messages.error(request, "Unknown action.")
        except ValidationError as exc:
            messages.error(
                request,
                "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc),
            )
        return redirect("ticket_admin_detail", ticket_id=ticket.id)

    discussions = [
        _serialize_discussion(d) for d in ticket_lib.discussions_for_ticket(ticket)
    ]
    return render(
        request,
        "assessment_tool/ticket_detail_admin.html",
        {
            "ticket": ticket,
            "discussions": discussions,
            "purpose_label": ticket_lib.purpose_label(ticket.contact_purpose),
            "status_label": ticket_lib.status_label(ticket.status),
            "priority_label": ticket_lib.priority_label(ticket.priority),
            "statuses": ticket_lib.TICKET_STATUSES,
            "priorities": ticket_lib.TICKET_PRIORITIES,
            "it_users": ticket_lib.it_support_users(),
            "client_url": ticket_lib.ticket_client_absolute_url(request, ticket),
            "client_path": ticket_lib.ticket_client_path(ticket),
            "can_delete": ticket_lib.can_delete_ticket(ticket),
            "qa_search_url": reverse("ticket_qa_search_api"),
            "max_body": ticket_lib.MAX_BODY,
        },
    )


@it_required
@require_GET
def ticket_qa_search_api(request):
    q = (request.GET.get("q") or "").strip()
    results = ticket_lib.search_qa_articles(q, limit=15)
    return JsonResponse({"results": results})


@require_http_methods(["GET", "POST"])
def ticket_client_view(request, access_token: str):
    ticket = get_object_or_404(
        Ticket.objects.select_related("username", "assigned_to"),
        access_token=access_token,
    )
    if request.method == "POST":
        author = None
        if request.user.is_authenticated:
            if ticket.username_id and request.user.pk == ticket.username_id:
                author = request.user
            elif (
                getattr(request.user, "user_email", None)
                and (request.user.user_email or "").lower()
                == (ticket.respond_to_email or "").lower()
            ):
                author = request.user
        try:
            ticket_lib.add_client_comment(
                ticket=ticket,
                body=request.POST.get("body") or "",
                author_user=author,
            )
        except ValidationError as exc:
            messages.error(
                request,
                "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc),
            )
        else:
            messages.success(request, "Your comment was posted.")
        return redirect("ticket_client", access_token=access_token)

    discussions = [
        _serialize_discussion(d) for d in ticket_lib.discussions_for_ticket(ticket)
    ]
    return render(
        request,
        "assessment_tool/ticket_detail_client.html",
        {
            "ticket": ticket,
            "discussions": discussions,
            "purpose_label": ticket_lib.purpose_label(ticket.contact_purpose),
            "status_label": ticket_lib.status_label(ticket.status),
            "priority_label": ticket_lib.priority_label(ticket.priority),
            "show_username": bool(ticket.username_id),
            "username_display": (
                ticket.username.username if ticket.username_id else None
            ),
            "max_body": ticket_lib.MAX_BODY,
        },
    )
