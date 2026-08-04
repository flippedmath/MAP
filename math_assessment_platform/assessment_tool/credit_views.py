"""Teacher account credit actions and IT Support credit administration."""

from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_http_methods

from .account_settings import gender_label
from .credit_invoices import absolute_path_for_storage
from .credits import (
    LIST_UNIT_PRICE,
    CreditError,
    acquire_credits,
    admin_revoke_credits,
    attach_invoice_to_ledger,
    attach_invoice_to_purchase,
    complete_checkout_purchase,
    complete_purchase,
    create_pending_purchase,
    credit_discount_tiers,
    get_balance,
    ledger_reason_label,
    list_credit_packs,
    net_unreimbursed_seat_spend,
    parse_positive_credit_quantity,
    parse_purchase_approval_details,
    reject_purchase,
    resolve_admin_credit_target,
    resolve_teacher_lookup,
    teacher_is_unlocked,
    transfer_credits,
)
from .dashboard import user_display_name
from .models import CreditInvoice, CreditLedger, CreditPurchase, UserProfile


def _purchase_provider_label(provider: str | None) -> str:
    if provider == CreditPurchase.PROVIDER_CHECKOUT:
        return "Website checkout"
    if provider == CreditPurchase.PROVIDER_ALLOTMENT_REQUEST:
        return "Allotment request"
    if provider == CreditPurchase.PROVIDER_STUB:
        return "Legacy request"
    return provider or "—"


def _purchase_status_label(status: str | None) -> str:
    return {
        CreditPurchase.STATUS_PENDING: "Pending",
        CreditPurchase.STATUS_COMPLETED: "Completed",
        CreditPurchase.STATUS_CANCELED: "Canceled",
        CreditPurchase.STATUS_REJECTED: "Rejected",
    }.get(status or "", status or "—")


def _notify_allotment_decision(purchase: CreditPurchase, *, approved: bool) -> None:
    """Notify the teacher that IT approved or rejected their allotment request."""
    from .notifications import (
        REASON_CREDIT_ALLOTMENT_APPROVED,
        REASON_CREDIT_ALLOTMENT_REJECTED,
        create_notification,
    )

    user = purchase.user
    credits_path = reverse("account_settings") + "?tab=credits"
    notes = (purchase.approval_notes or "").strip()
    if approved:
        message = (
            f"Your credit allotment request #{purchase.pk} was approved. "
            f"{purchase.credits_gained or purchase.pack_size} credits have been added "
            "to your balance."
        )
        reason = REASON_CREDIT_ALLOTMENT_APPROVED
        title = "Credit allotment approved"
    else:
        message = (
            f"Your credit allotment request #{purchase.pk} was rejected. "
            "No credits were added."
        )
        reason = REASON_CREDIT_ALLOTMENT_REJECTED
        title = "Credit allotment rejected"
    create_notification(
        user,
        title=title,
        content={
            "message": message,
            "purchase_id": purchase.pk,
            "pack_size": purchase.pack_size,
            "credits_gained": purchase.credits_gained if approved else None,
            "total_amount": str(purchase.total_amount),
            "money_spent": str(purchase.money_spent) if purchase.money_spent is not None else None,
            "decision_notes": notes,
            "decision_status": "approved" if approved else "rejected",
            "credits_path": credits_path,
        },
        reason=reason,
        sender=purchase.approved_by,
    )


def _credits_admin_redirect(*, tab: str = "manage", teacher: str = ""):
    url = reverse("credits_admin")
    params = []
    if tab and tab != "manage":
        params.append(f"tab={tab}")
    if teacher:
        params.append(f"teacher={teacher}")
    if params:
        return redirect(url + "?" + "&".join(params))
    return redirect(url)


def _history_date_range(request):
    today = timezone.localdate()
    end = parse_date((request.GET.get("end") or "").strip()) or today
    start = parse_date((request.GET.get("start") or "").strip()) or (
        end - timedelta(days=90)
    )
    if start > end:
        start, end = end, start
    return start, end


def _notify_allotment_request_submitted(user, purchase: CreditPurchase) -> None:
    """
    Teacher notification + urgent IT ticket for a pending allotment request.

    Credits stay pending until admin approval; this only notifies.
    """
    from urllib.parse import quote

    from django.core.exceptions import ValidationError

    from .notifications import (
        REASON_CREDIT_ALLOTMENT_PENDING,
        create_notification,
    )
    from .tickets import create_ticket

    credits_path = reverse("account_settings") + "?tab=credits"
    admin_credits_path = (
        reverse("credits_admin")
        + f"?tab=manage&teacher={quote(user.username or '')}"
    )
    message = (
        f"Your credit allotment request #{purchase.pk} for {purchase.pack_size} "
        f"credits is pending. Credits will be added only after IT Support approves "
        "the request."
    )
    create_notification(
        user,
        title="Credit allotment pending",
        content={
            "message": message,
            "purchase_id": purchase.pk,
            "pack_size": purchase.pack_size,
            "total_amount": str(purchase.total_amount),
            "credits_path": credits_path,
        },
        reason=REASON_CREDIT_ALLOTMENT_PENDING,
        sender=None,
    )

    first_name = (
        (getattr(user, "user_first_name", None) or "").strip()
        or (user.username or "Teacher")
    )[:255]
    email = (getattr(user, "user_email", None) or "").strip() or (
        f"{user.username or 'teacher'}@local"
    )
    body_parts = [
        f"Teacher {user.username} submitted a credit allotment request that "
        "bypassed checkout and requires IT approval before credits are granted.",
        "",
        f"Purchase ID: #{purchase.pk}",
        f"Credits requested: {purchase.pack_size}",
        f"Reference total: ${purchase.total_amount}",
    ]
    if purchase.note:
        body_parts.extend(["", f"Teacher note: {purchase.note}"])
    if purchase.invoice_id:
        body_parts.append(f"Invoice attached: yes (invoice #{purchase.invoice_id})")
    else:
        body_parts.append("Invoice attached: no")
    body_parts.extend(
        [
            "",
            "Credits admin (approve pending allotments):",
            admin_credits_path,
        ]
    )
    try:
        ticket = create_ticket(
            title=f"Credit allotment request #{purchase.pk} — {user.username}",
            contact_purpose="billing",
            first_name=first_name,
            respond_to_email=email,
            body="\n".join(body_parts),
            username=user,
            priority="urgent",
            status="new",
            created_by=user,
            notify_client=False,
            system_note=(
                f"Auto-created from credit allotment request #{purchase.pk}"
            ),
        )
        if not ticket.admin_unread:
            ticket.admin_unread = True
            ticket.save(update_fields=["admin_unread"])
    except ValidationError as exc:
        import logging

        logging.getLogger(__name__).exception(
            "Failed to create urgent ticket for allotment request #%s: %s",
            purchase.pk,
            exc,
        )


def _is_it_support(user) -> bool:
    return bool(user.is_authenticated and getattr(user, "user_type", None) == "IT_Support")


def _is_teacher_or_it(user) -> bool:
    return bool(
        user.is_authenticated
        and getattr(user, "user_type", None) in ("Teacher", "IT_Support")
    )


def credits_account_redirect():
    return redirect(reverse("account_settings") + "?tab=credits")


def _invoice_download_url(invoice: CreditInvoice | None) -> str | None:
    if not invoice or not invoice.pk:
        return None
    return reverse("credits_invoice_download", kwargs={"invoice_id": invoice.pk})


def _ledger_invoice(row: CreditLedger) -> CreditInvoice | None:
    from .credit_invoices import invoice_for_ledger_row

    return invoice_for_ledger_row(row)


def _store_optional_invoice(*, owner, actor, uploaded_file):
    from .credit_invoices import store_invoice_pdf

    if not uploaded_file:
        return None
    return store_invoice_pdf(
        owner=owner, uploaded_by=actor, uploaded_file=uploaded_file
    )


def account_credits_context(user) -> dict:
    packs = list_credit_packs()
    ledger = (
        CreditLedger.objects.filter(user=user)
        .select_related(
            "actor_user",
            "invoice",
            "related_purchase",
            "related_purchase__invoice",
        )
        .order_by("-creation_date", "-pk")[:40]
    )
    ledger_rows = []
    for row in ledger:
        invoice = _ledger_invoice(row)
        ledger_rows.append(
            {
                "row": row,
                "reason_label": ledger_reason_label(row.reason),
                "actor": row.actor_user.username if row.actor_user_id else "—",
                "invoice_url": _invoice_download_url(invoice),
                "invoice_filename": (
                    invoice.original_filename if invoice else None
                ),
            }
        )
    pending_qs = (
        CreditPurchase.objects.filter(user=user, status=CreditPurchase.STATUS_PENDING)
        .filter(
            Q(provider=CreditPurchase.PROVIDER_ALLOTMENT_REQUEST)
            | Q(provider=CreditPurchase.PROVIDER_STUB)
        )
        .select_related("invoice")
        .order_by("-creation_date", "-pk")[:10]
    )
    pending_rows = [
        {
            "purchase": p,
            "invoice_url": _invoice_download_url(p.invoice),
            "invoice_filename": (
                p.invoice.original_filename if p.invoice_id else None
            ),
        }
        for p in pending_qs
    ]
    return {
        "credit_balance": get_balance(user),
        "teacher_credits_unlocked": teacher_is_unlocked(user),
        "net_unreimbursed_seats": net_unreimbursed_seat_spend(user),
        "credit_packs": packs,
        "credit_discount_tiers": credit_discount_tiers(),
        "credit_list_unit_price": str(LIST_UNIT_PRICE),
        "credit_ledger_rows": ledger_rows,
        "pending_purchases": pending_qs,
        "pending_purchase_rows": pending_rows,
        "show_credits_tab": _is_teacher_or_it(user),
        "transfer_lookup_url": reverse("credits_transfer_lookup"),
        "transfer_allows_it_support": getattr(user, "user_type", None) == "IT_Support",
    }


@login_required
def handle_account_credit_post(request):
    """Process Credits-tab POSTs from account settings. Returns redirect response."""
    if not _is_teacher_or_it(request.user):
        messages.error(request, "Credits are only available for Teacher accounts.")
        return credits_account_redirect()

    action = request.POST.get("action") or ""
    try:
        if action == "buy_credits":
            # Direct checkout: credits granted immediately; no admin validation.
            pack_size = parse_positive_credit_quantity(
                request.POST.get("pack_size")
            )
            note = (request.POST.get("note") or "").strip() or None
            purchase, _ledger = complete_checkout_purchase(
                request.user, pack_size, note=note
            )
            messages.success(
                request,
                f"Purchased {purchase.pack_size} credits (${purchase.total_amount}). "
                "Credits have been added to your balance.",
            )
        elif action == "request_credits":
            # Bypass checkout: pending only — credits granted after IT approval.
            from .credit_invoices import require_note_without_invoice

            pack_size = parse_positive_credit_quantity(
                request.POST.get("pack_size")
            )
            invoice = _store_optional_invoice(
                owner=request.user,
                actor=request.user,
                uploaded_file=request.FILES.get("invoice_pdf"),
            )
            note = require_note_without_invoice(request.POST.get("note"), invoice)
            purchase = create_pending_purchase(
                request.user,
                pack_size,
                note=note or None,
                invoice=invoice,
                provider=CreditPurchase.PROVIDER_ALLOTMENT_REQUEST,
            )
            _notify_allotment_request_submitted(request.user, purchase)
            messages.info(
                request,
                f"Credit allotment request #{purchase.pk} submitted for "
                f"{purchase.pack_size} credits (${purchase.total_amount}). "
                "Credits are pending and will be added only after IT Support "
                "approves the request.",
            )
        elif action == "attach_purchase_invoice":
            purchase = get_object_or_404(
                CreditPurchase,
                pk=request.POST.get("purchase_id"),
                user=request.user,
            )
            if purchase.status != CreditPurchase.STATUS_PENDING:
                raise CreditError("Only pending purchases can receive an invoice from you.")
            if purchase.invoice_id:
                raise CreditError("This purchase already has an invoice attached.")
            uploaded = request.FILES.get("invoice_pdf")
            if not uploaded:
                raise CreditError("Choose a PDF invoice to upload.")
            invoice = _store_optional_invoice(
                owner=request.user,
                actor=request.user,
                uploaded_file=uploaded,
            )
            attach_invoice_to_purchase(purchase, invoice)
            messages.success(request, f"Invoice attached to purchase #{purchase.pk}.")
        elif action == "transfer_credits":
            amount = parse_positive_credit_quantity(request.POST.get("amount"))
            if getattr(request.user, "user_type", None) == "IT_Support":
                recipient = resolve_admin_credit_target(
                    request.POST.get("recipient") or ""
                )
            else:
                recipient = resolve_teacher_lookup(
                    request.POST.get("recipient") or ""
                )
            note = (request.POST.get("note") or "").strip()
            transfer_credits(
                request.user, recipient, amount, note=note or None
            )
            messages.success(
                request,
                f"Transferred {amount} credit(s) to {recipient.username}.",
            )
        else:
            messages.error(request, "Unknown credits action.")
    except (CreditError, ValueError) as exc:
        messages.error(request, str(exc))
    return credits_account_redirect()


def _basic_user_profile_payload(user: UserProfile) -> dict:
    """Public-ish profile fields for transfer recipient preview (no balances)."""
    return {
        "found": True,
        "user_id": user.pk,
        "username": user.username,
        "email": user.user_email or "",
        "display_name": user_display_name(user),
        "first_name": user.user_first_name or "",
        "last_name": user.user_last_name or "",
        "organization": user.organization or "",
        "gender": gender_label(user.gender),
        "user_type": user.user_type or "",
    }


def _teacher_credit_profile_payload(user: UserProfile) -> dict:
    ledger = (
        CreditLedger.objects.filter(user=user)
        .select_related(
            "actor_user",
            "invoice",
            "related_purchase",
            "related_purchase__invoice",
        )
        .order_by("-creation_date", "-pk")
    )
    transactions = []
    for row in ledger:
        created = row.creation_date
        invoice = _ledger_invoice(row)
        transactions.append(
            {
                "id": f"ledger-{row.pk}",
                "entry_kind": "ledger",
                "delta": row.delta,
                "balance_after": row.balance_after,
                "reason": row.reason,
                "reason_label": ledger_reason_label(row.reason),
                "status": None,
                "status_label": None,
                "actor": row.actor_user.username if row.actor_user_id else None,
                "note": row.note or "",
                "invoice_url": _invoice_download_url(invoice),
                "invoice_filename": (
                    invoice.original_filename if invoice else None
                ),
                "creation_date": created.isoformat() if created else None,
                "creation_date_display": (
                    created.strftime("%Y-%m-%d %H:%M:%S UTC") if created else "—"
                ),
                "sort_ts": created.timestamp() if created else 0,
            }
        )

    rejected = (
        CreditPurchase.objects.filter(
            user=user, status=CreditPurchase.STATUS_REJECTED
        )
        .select_related("invoice", "approved_by")
        .order_by("-approved_at", "-pk")
    )
    for purchase in rejected:
        decided = purchase.approved_at or purchase.creation_date
        invoice = purchase.invoice
        transactions.append(
            {
                "id": f"purchase-{purchase.pk}",
                "entry_kind": "purchase",
                "delta": 0,
                "balance_after": None,
                "reason": "allotment_rejected",
                "reason_label": "Allotment rejected",
                "status": purchase.status,
                "status_label": "Rejected",
                "actor": (
                    purchase.approved_by.username if purchase.approved_by_id else None
                ),
                "note": purchase.approval_notes or purchase.note or "",
                "invoice_url": _invoice_download_url(invoice),
                "invoice_filename": (
                    invoice.original_filename if invoice else None
                ),
                "pack_size": purchase.pack_size,
                "creation_date": decided.isoformat() if decided else None,
                "creation_date_display": (
                    decided.strftime("%Y-%m-%d %H:%M:%S UTC") if decided else "—"
                ),
                "sort_ts": decided.timestamp() if decided else 0,
            }
        )

    transactions.sort(key=lambda item: item.get("sort_ts") or 0, reverse=True)
    for item in transactions:
        item.pop("sort_ts", None)

    return {
        "found": True,
        "user_id": user.pk,
        "username": user.username,
        "email": user.user_email or "",
        "display_name": user_display_name(user),
        "first_name": user.user_first_name or "",
        "last_name": user.user_last_name or "",
        "organization": user.organization or "",
        "gender": gender_label(user.gender),
        "user_type": user.user_type or "",
        "credit_balance": get_balance(user),
        "unlocked": teacher_is_unlocked(user),
        "net_unreimbursed_seats": net_unreimbursed_seat_spend(user),
        "lifetime_credits_acquired": int(user.lifetime_credits_acquired or 0),
        "lifetime_seat_debits": int(user.lifetime_seat_debits or 0),
        "lifetime_seat_reimbursements": int(user.lifetime_seat_reimbursements or 0),
        "creation_date": (
            user.creation_date.isoformat() if user.creation_date else None
        ),
        "transactions": transactions,
    }


@login_required
@require_GET
def credits_invoice_download(request, invoice_id: int):
    """Serve a credit invoice PDF to the owner Teacher or IT Support only."""
    from .credit_invoices import user_can_access_invoice

    invoice = get_object_or_404(CreditInvoice, pk=invoice_id)
    if not user_can_access_invoice(request.user, invoice):
        raise Http404("Invoice not found.")
    path = absolute_path_for_storage(invoice.storage_path)
    if not path.is_file():
        raise Http404("Invoice file is missing.")
    filename = invoice.original_filename or f"credit-invoice-{invoice.pk}.pdf"
    response = FileResponse(
        path.open("rb"),
        content_type=invoice.content_type or "application/pdf",
        as_attachment=False,
        filename=filename,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@user_passes_test(_is_it_support, login_url="/dashboard/")
@require_GET
def credits_admin_lookup_api(request):
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"found": False, "error": "Type at least 2 characters."})
    try:
        target = resolve_admin_credit_target(q)
    except CreditError as exc:
        return JsonResponse({"found": False, "error": str(exc)})
    return JsonResponse(_teacher_credit_profile_payload(target))


@login_required
@require_GET
def credits_transfer_lookup_api(request):
    """Recipient preview for Account → Credits transfer (Teachers; IT may also match admins)."""
    if not _is_teacher_or_it(request.user):
        return JsonResponse({"found": False, "error": "Unauthorized."}, status=403)
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"found": False, "error": "Type at least 2 characters."})
    try:
        if getattr(request.user, "user_type", None) == "IT_Support":
            target = resolve_admin_credit_target(q)
        else:
            target = resolve_teacher_lookup(q)
    except CreditError as exc:
        return JsonResponse({"found": False, "error": str(exc)})
    if target.pk == request.user.pk:
        return JsonResponse(
            {"found": False, "error": "You cannot transfer credits to yourself."}
        )
    return JsonResponse(_basic_user_profile_payload(target))


@login_required
@user_passes_test(_is_it_support, login_url="/dashboard/")
@require_http_methods(["GET", "POST"])
def credits_admin_view(request):
    from .credit_invoices import require_note_without_invoice

    focus_teacher = ""
    if request.method == "POST":
        action = request.POST.get("action") or ""
        try:
            if action == "grant":
                target = resolve_admin_credit_target(request.POST.get("target") or "")
                amount = parse_positive_credit_quantity(request.POST.get("amount"))
                invoice = _store_optional_invoice(
                    owner=target,
                    actor=request.user,
                    uploaded_file=request.FILES.get("invoice_pdf"),
                )
                note = require_note_without_invoice(
                    request.POST.get("note"), invoice
                )
                acquire_credits(
                    target,
                    amount,
                    reason=CreditLedger.REASON_ADMIN_GRANT,
                    actor=request.user,
                    note=note or None,
                    invoice=invoice,
                )
                messages.success(
                    request,
                    f"Granted {amount} credit(s) to {target.username}.",
                )
                focus_teacher = target.username
            elif action == "revoke":
                target = resolve_admin_credit_target(request.POST.get("target") or "")
                amount = parse_positive_credit_quantity(request.POST.get("amount"))
                note = (request.POST.get("note") or "").strip()
                admin_revoke_credits(
                    target, amount, actor=request.user, note=note
                )
                messages.success(
                    request,
                    f"Revoked {amount} credit(s) from {target.username}.",
                )
                focus_teacher = target.username
            elif action == "batch_grant":
                amount = parse_positive_credit_quantity(request.POST.get("amount"))
                note = (request.POST.get("note") or "").strip()
                if not note:
                    raise CreditError(
                        "A note is required for batch grants (no shared invoice)."
                    )
                raw_lines = (request.POST.get("targets") or "").replace(",", "\n")
                lines = [ln.strip() for ln in raw_lines.splitlines() if ln.strip()]
                if not lines:
                    raise CreditError("Enter at least one username or email.")
                ok = 0
                errors = []
                for line in lines:
                    try:
                        target = resolve_admin_credit_target(line)
                        acquire_credits(
                            target,
                            amount,
                            reason=CreditLedger.REASON_ADMIN_GRANT,
                            actor=request.user,
                            note=note,
                        )
                        ok += 1
                    except CreditError as exc:
                        errors.append(f"{line}: {exc}")
                if ok:
                    messages.success(
                        request, f"Granted {amount} credit(s) to {ok} account(s)."
                    )
                for err in errors[:20]:
                    messages.error(request, err)
            elif action == "complete_purchase":
                purchase = get_object_or_404(
                    CreditPurchase.objects.select_related("user", "invoice"),
                    pk=request.POST.get("purchase_id"),
                )
                uploaded = request.FILES.get("invoice_pdf")
                if uploaded:
                    invoice = _store_optional_invoice(
                        owner=purchase.user,
                        actor=request.user,
                        uploaded_file=uploaded,
                    )
                    attach_invoice_to_purchase(
                        purchase, invoice, replace=bool(purchase.invoice_id)
                    )
                    purchase.refresh_from_db()
                approval = parse_purchase_approval_details(
                    money_spent=request.POST.get("money_spent"),
                    credits_gained=request.POST.get("credits_gained")
                    or request.POST.get("pack_size"),
                    invoice_dated=request.POST.get("invoice_dated"),
                    paid_by=request.POST.get("paid_by"),
                    payer_organization=request.POST.get("payer_organization"),
                    approval_notes=request.POST.get("approval_notes"),
                )
                complete_purchase(
                    purchase,
                    actor=request.user,
                    approval=approval,
                )
                purchase.refresh_from_db()
                _notify_allotment_decision(purchase, approved=True)
                messages.success(
                    request,
                    f"Verified allotment #{purchase.pk} for {purchase.user.username} "
                    f"({purchase.credits_gained} credits, ${purchase.money_spent}).",
                )
                focus_teacher = purchase.user.username
            elif action == "reject_purchase":
                purchase = get_object_or_404(
                    CreditPurchase.objects.select_related("user", "invoice"),
                    pk=request.POST.get("purchase_id"),
                )
                note = (request.POST.get("rejection_note") or "").strip()
                reject_purchase(purchase, actor=request.user, note=note)
                purchase.refresh_from_db()
                _notify_allotment_decision(purchase, approved=False)
                messages.success(
                    request,
                    f"Rejected allotment #{purchase.pk} for {purchase.user.username}.",
                )
                focus_teacher = purchase.user.username
            elif action == "attach_purchase_invoice":
                purchase = get_object_or_404(
                    CreditPurchase.objects.select_related("user"),
                    pk=request.POST.get("purchase_id"),
                )
                uploaded = request.FILES.get("invoice_pdf")
                if not uploaded:
                    raise CreditError("Choose a PDF invoice to upload.")
                invoice = _store_optional_invoice(
                    owner=purchase.user,
                    actor=request.user,
                    uploaded_file=uploaded,
                )
                attach_invoice_to_purchase(
                    purchase, invoice, replace=bool(purchase.invoice_id)
                )
                messages.success(
                    request,
                    f"Invoice attached to purchase #{purchase.pk}.",
                )
                focus_teacher = purchase.user.username
            elif action == "attach_ledger_invoice":
                ledger = get_object_or_404(
                    CreditLedger.objects.select_related("user"),
                    pk=request.POST.get("ledger_id"),
                )
                uploaded = request.FILES.get("invoice_pdf")
                if not uploaded:
                    raise CreditError("Choose a PDF invoice to upload.")
                invoice = _store_optional_invoice(
                    owner=ledger.user,
                    actor=request.user,
                    uploaded_file=uploaded,
                )
                attach_invoice_to_ledger(
                    ledger, invoice, replace=bool(ledger.invoice_id)
                )
                messages.success(
                    request,
                    f"Invoice attached to credit activity #{ledger.pk}.",
                )
                focus_teacher = ledger.user.username
            else:
                messages.error(request, "Unknown admin action.")
        except (CreditError, ValueError) as exc:
            messages.error(request, str(exc))
        return _credits_admin_redirect(tab="manage", teacher=focus_teacher)

    active_tab = (request.GET.get("tab") or "manage").strip().lower()
    if active_tab not in ("manage", "history"):
        active_tab = "manage"

    history_start, history_end = _history_date_range(request)
    history_user = (request.GET.get("user") or "").strip()
    history_organization = (request.GET.get("organization") or "").strip()
    history_rows = []
    if active_tab == "history":
        # Include completed checkouts/allotments and rejected allotments.
        # Match date range on completion, decision, or creation time.
        history_qs = (
            CreditPurchase.objects.filter(
                status__in=(
                    CreditPurchase.STATUS_COMPLETED,
                    CreditPurchase.STATUS_REJECTED,
                )
            )
            .filter(
                Q(
                    completed_at__date__gte=history_start,
                    completed_at__date__lte=history_end,
                )
                | Q(
                    approved_at__date__gte=history_start,
                    approved_at__date__lte=history_end,
                )
                | Q(
                    completed_at__isnull=True,
                    approved_at__isnull=True,
                    creation_date__date__gte=history_start,
                    creation_date__date__lte=history_end,
                )
            )
            .select_related("user", "invoice", "approved_by")
        )
        if history_user:
            history_qs = history_qs.filter(
                Q(user__username__icontains=history_user)
                | Q(user__user_email__icontains=history_user)
            )
        if history_organization:
            history_qs = history_qs.filter(
                Q(payer_organization__icontains=history_organization)
                | Q(user__organization__icontains=history_organization)
            )
        history_qs = history_qs.order_by(
            "-completed_at", "-approved_at", "-creation_date", "-pk"
        )[:500]
        for p in history_qs:
            org = (p.payer_organization or "").strip() or (
                (p.user.organization or "").strip() if p.user_id else ""
            )
            history_rows.append(
                {
                    "purchase": p,
                    "provider_label": _purchase_provider_label(p.provider),
                    "status_label": _purchase_status_label(p.status),
                    "username": p.user.username if p.user_id else "—",
                    "organization_display": org or "—",
                    "invoice_url": _invoice_download_url(p.invoice),
                    "invoice_filename": (
                        p.invoice.original_filename if p.invoice_id else None
                    ),
                    "approver": (
                        p.approved_by.username if p.approved_by_id else "—"
                    ),
                }
            )

    ledger = (
        CreditLedger.objects.select_related(
            "user",
            "actor_user",
            "invoice",
            "related_purchase",
            "related_purchase__invoice",
        )
        .order_by("-creation_date", "-pk")[:100]
    )
    ledger_rows = []
    for row in ledger:
        invoice = _ledger_invoice(row)
        ledger_rows.append(
            {
                "row": row,
                "reason_label": ledger_reason_label(row.reason),
                "username": row.user.username if row.user_id else "—",
                "actor": row.actor_user.username if row.actor_user_id else "—",
                "invoice_url": _invoice_download_url(invoice),
                "invoice_filename": (
                    invoice.original_filename if invoice else None
                ),
                "can_attach_invoice": row.reason
                in (
                    CreditLedger.REASON_PURCHASE,
                    CreditLedger.REASON_ADMIN_GRANT,
                ),
            }
        )
    pending_purchases = (
        CreditPurchase.objects.filter(status=CreditPurchase.STATUS_PENDING)
        .filter(
            Q(provider=CreditPurchase.PROVIDER_ALLOTMENT_REQUEST)
            | Q(provider=CreditPurchase.PROVIDER_STUB)
        )
        .select_related("user", "invoice")
        .order_by("-creation_date", "-pk")[:50]
    )
    pending_rows = [
        {
            "purchase": p,
            "invoice_url": _invoice_download_url(p.invoice),
            "invoice_filename": (
                p.invoice.original_filename if p.invoice_id else None
            ),
        }
        for p in pending_purchases
    ]
    return render(
        request,
        "assessment_tool/credits_admin.html",
        {
            "credits_admin_tab": active_tab,
            "ledger_rows": ledger_rows,
            "pending_purchases": pending_purchases,
            "pending_purchase_rows": pending_rows,
            "purchase_history_rows": history_rows,
            "history_start": history_start.isoformat(),
            "history_end": history_end.isoformat(),
            "history_user": history_user,
            "history_organization": history_organization,
            "credit_packs": list_credit_packs(),
            "credits_lookup_url": reverse("credits_admin_lookup"),
            "initial_teacher_query": (request.GET.get("teacher") or "").strip(),
        },
    )
