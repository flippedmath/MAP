"""
Teacher seat-credit balances, unlock/relock, packs, transfers, and ledger.

Credits are spent when a teacher sends a student invite. Void/revoke unused
invites and kicks within seven days reimburse and may relock the teacher.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Course, CreditInvoice, CreditLedger, CreditPurchase, UserProfile

_POSITIVE_INT_RE = re.compile(r"^[1-9]\d*$")
_MONEY_RE = re.compile(r"^\d+(\.\d{1,2})?$")

LIST_UNIT_PRICE = Decimal("100.00")

# Minimum quantity -> discount percent off list unit price (highest matching tier wins).
_CREDIT_DISCOUNT_TIERS: tuple[tuple[int, Decimal], ...] = (
    (1, Decimal("0")),
    (10, Decimal("15")),
    (30, Decimal("25")),
    (50, Decimal("35")),
    (100, Decimal("40")),
    (150, Decimal("45")),
)


@dataclass(frozen=True)
class CreditPack:
    size: int
    discount_percent: Decimal
    list_unit_price: Decimal
    unit_price: Decimal
    total_amount: Decimal


@dataclass(frozen=True)
class PurchaseApprovalDetails:
    """Admin-entered invoice details when verifying an allotment request."""

    money_spent: Decimal
    credits_gained: int
    invoice_dated: date
    paid_by: str
    payer_organization: str | None = None
    approval_notes: str | None = None


class CreditError(ValueError):
    """Raised for user-facing credit rule violations."""


def parse_positive_money_amount(raw) -> Decimal:
    """Require a positive money amount with at most two decimal places."""
    text = str(raw if raw is not None else "").strip().replace("$", "").replace(",", "")
    if not text or not _MONEY_RE.fullmatch(text):
        raise CreditError("Enter a valid money amount (e.g. 250.00).")
    try:
        amount = Decimal(text).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise CreditError("Enter a valid money amount (e.g. 250.00).") from exc
    if amount <= 0:
        raise CreditError("Money spent must be greater than zero.")
    return amount


def parse_invoice_date(raw) -> date:
    text = str(raw if raw is not None else "").strip()
    if not text:
        raise CreditError("Enter the invoice date.")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise CreditError("Enter the invoice date as YYYY-MM-DD.") from exc


def parse_purchase_approval_details(
    *,
    money_spent,
    credits_gained,
    invoice_dated,
    paid_by,
    payer_organization=None,
    approval_notes=None,
) -> PurchaseApprovalDetails:
    paid = (paid_by or "").strip()
    if not paid:
        raise CreditError("Enter who paid for the credits.")
    org = (payer_organization or "").strip() or None
    notes = (approval_notes or "").strip() or None
    return PurchaseApprovalDetails(
        money_spent=parse_positive_money_amount(money_spent),
        credits_gained=parse_positive_credit_quantity(credits_gained),
        invoice_dated=parse_invoice_date(invoice_dated),
        paid_by=paid[:255],
        payer_organization=(org[:255] if org else None),
        approval_notes=notes,
    )


def parse_positive_credit_quantity(raw) -> int:
    """
    Require a positive whole number of credits.

    Rejects negatives, zero, decimals, and non-numeric input so buy/purchase
    paths cannot create negative money or credit deltas.
    """
    if isinstance(raw, bool):
        raise CreditError("Enter a positive whole number of credits.")
    if isinstance(raw, int):
        if raw < 1:
            raise CreditError("Enter a positive whole number of credits.")
        return raw
    text = str(raw if raw is not None else "").strip()
    if not _POSITIVE_INT_RE.fullmatch(text):
        raise CreditError("Enter a positive whole number of credits.")
    return int(text)


def credit_discount_tiers() -> list[dict]:
    """Tier thresholds for UI (min quantity and discount percent)."""
    return [
        {"min_quantity": threshold, "discount_percent": str(pct)}
        for threshold, pct in _CREDIT_DISCOUNT_TIERS
    ]


def discount_percent_for_quantity(size: int) -> Decimal:
    size = parse_positive_credit_quantity(size)
    discount = Decimal("0")
    for threshold, pct in _CREDIT_DISCOUNT_TIERS:
        if size >= threshold:
            discount = pct
    return discount


def list_credit_packs() -> list[CreditPack]:
    """Reference quotes at each discount tier threshold (admin display)."""
    return [quote_pack(threshold) for threshold, _pct in _CREDIT_DISCOUNT_TIERS]


def quote_pack(size: int) -> CreditPack:
    """Quote any positive credit quantity using volume discount tiers."""
    size = parse_positive_credit_quantity(size)
    discount = discount_percent_for_quantity(size)
    unit = (LIST_UNIT_PRICE * (Decimal("100") - discount) / Decimal("100")).quantize(
        Decimal("0.01")
    )
    total = (unit * size).quantize(Decimal("0.01"))
    if unit <= 0 or total <= 0:
        raise CreditError("Quoted purchase amount must be positive.")
    return CreditPack(
        size=size,
        discount_percent=discount,
        list_unit_price=LIST_UNIT_PRICE,
        unit_price=unit,
        total_amount=total,
    )


def get_balance(user) -> int:
    return max(0, int(getattr(user, "user_credit", None) or 0))


def net_unreimbursed_seat_spend(user) -> int:
    debits = int(getattr(user, "lifetime_seat_debits", None) or 0)
    reimbursements = int(getattr(user, "lifetime_seat_reimbursements", None) or 0)
    return max(0, debits - reimbursements)


def compute_unlocked(user) -> bool:
    if getattr(user, "user_type", None) == "IT_Support":
        return True
    return get_balance(user) >= 1 or net_unreimbursed_seat_spend(user) > 0


def teacher_is_unlocked(user) -> bool:
    if getattr(user, "user_type", None) == "IT_Support":
        return True
    cached = getattr(user, "teacher_unlocked", None)
    if cached is not None:
        return bool(cached)
    return compute_unlocked(user)


def recompute_unlock(user) -> bool:
    unlocked = compute_unlocked(user)
    if getattr(user, "user_type", None) == "IT_Support":
        # Keep DB flag honest for IT rows that also hold credits.
        unlocked_flag = get_balance(user) >= 1 or net_unreimbursed_seat_spend(user) > 0
    else:
        unlocked_flag = unlocked
    if bool(getattr(user, "teacher_unlocked", False)) != unlocked_flag:
        user.teacher_unlocked = unlocked_flag
        user.save(update_fields=["teacher_unlocked"])
    return unlocked


def _locked_teacher_course_count(user) -> int:
    return (
        Course.objects.filter(owner=user)
        .exclude(status="deleted")
        .count()
    )


def assert_can_create_course(user) -> None:
    if getattr(user, "user_type", None) == "IT_Support":
        return
    if teacher_is_unlocked(user):
        return
    if _locked_teacher_course_count(user) >= 1:
        raise CreditError(
            "Free teacher accounts may only have one course. "
            "Buy or receive credits to unlock additional courses."
        )


def assert_can_invite(user) -> None:
    if getattr(user, "user_type", None) == "IT_Support":
        return
    if not teacher_is_unlocked(user):
        raise CreditError(
            "Student invitations require credits. "
            "Buy or receive at least one credit to unlock invitations."
        )
    if get_balance(user) < 1:
        raise CreditError(
            "You need at least one credit to invite a student. "
            "Buy credits or transfer unused invites back by voiding them."
        )


def assert_can_use_collab_groups(user) -> None:
    if getattr(user, "user_type", None) == "IT_Support":
        return
    if not teacher_is_unlocked(user):
        raise CreditError(
            "Collaboration groups require an unlocked teacher account. "
            "Buy or receive credits first. The Public Library remains available."
        )


def assert_can_print(user) -> bool:
    """Return whether the user may print assessments (feature gate helper)."""
    if getattr(user, "user_type", None) == "IT_Support":
        return True
    return teacher_is_unlocked(user)


def _lock_user(user_id: int) -> UserProfile:
    return UserProfile.objects.select_for_update().get(pk=user_id)


def _apply_delta(
    user: UserProfile,
    *,
    delta: int,
    reason: str,
    actor=None,
    note: str | None = None,
    related_invite_id: int | None = None,
    related_enrollment_id: int | None = None,
    related_purchase: CreditPurchase | None = None,
    invoice: CreditInvoice | None = None,
    acquired_delta: int = 0,
    seat_debit_delta: int = 0,
    seat_reimburse_delta: int = 0,
) -> CreditLedger:
    balance = get_balance(user)
    new_balance = balance + int(delta)
    if new_balance < 0:
        raise CreditError("Insufficient credits.")

    user.user_credit = new_balance
    if acquired_delta:
        user.lifetime_credits_acquired = (
            int(user.lifetime_credits_acquired or 0) + int(acquired_delta)
        )
    if seat_debit_delta:
        user.lifetime_seat_debits = (
            int(user.lifetime_seat_debits or 0) + int(seat_debit_delta)
        )
    if seat_reimburse_delta:
        user.lifetime_seat_reimbursements = (
            int(user.lifetime_seat_reimbursements or 0) + int(seat_reimburse_delta)
        )

    unlocked_flag = new_balance >= 1 or (
        int(user.lifetime_seat_debits or 0)
        - int(user.lifetime_seat_reimbursements or 0)
        > 0
    )
    user.teacher_unlocked = unlocked_flag
    user.save(
        update_fields=[
            "user_credit",
            "lifetime_credits_acquired",
            "lifetime_seat_debits",
            "lifetime_seat_reimbursements",
            "teacher_unlocked",
        ]
    )

    return CreditLedger.objects.create(
        user=user,
        delta=int(delta),
        balance_after=new_balance,
        reason=reason,
        actor_user=actor if getattr(actor, "pk", None) else None,
        related_invite_id=related_invite_id,
        related_enrollment_id=related_enrollment_id,
        related_purchase=related_purchase,
        invoice=invoice,
        note=(note or "")[:2000] or None,
        creation_date=timezone.now(),
    )


@transaction.atomic
def acquire_credits(
    user,
    amount: int,
    *,
    reason: str,
    actor=None,
    note: str | None = None,
    related_purchase: CreditPurchase | None = None,
    invoice: CreditInvoice | None = None,
) -> CreditLedger:
    amount = parse_positive_credit_quantity(amount)
    locked = _lock_user(user.pk)
    return _apply_delta(
        locked,
        delta=amount,
        reason=reason,
        actor=actor,
        note=note,
        related_purchase=related_purchase,
        invoice=invoice,
        acquired_delta=amount,
    )


@transaction.atomic
def admin_revoke_credits(
    user,
    amount: int,
    *,
    actor,
    note: str,
) -> CreditLedger:
    """
    Admin-only manual credit take-back.

    Teacher buy/purchase flows must never create negative quantities; use this
    from IT Support admin tools when credits need to be removed.
    """
    if getattr(actor, "user_type", None) != "IT_Support":
        raise CreditError("Only IT Support can revoke credits.")
    amount = parse_positive_credit_quantity(amount)
    note = (note or "").strip()
    if not note:
        raise CreditError("A note is required for admin credit changes.")
    locked = _lock_user(user.pk)
    if get_balance(locked) < amount:
        raise CreditError("Cannot revoke more credits than the teacher has.")
    # Allow revoke down to 0 even if it locks (admin override).
    return _apply_delta(
        locked,
        delta=-amount,
        reason=CreditLedger.REASON_ADMIN_REVOKE,
        actor=actor,
        note=note,
    )


@transaction.atomic
def spend_invite_credit(teacher, *, invite_id: int) -> CreditLedger | None:
    """
    Debit one seat credit for a newly created student invite.
    IT Support invites do not spend credits.
    """
    if getattr(teacher, "user_type", None) == "IT_Support":
        return None
    if CreditLedger.objects.filter(
        reason=CreditLedger.REASON_INVITE_SPEND,
        related_invite_id=invite_id,
    ).exists():
        return None

    locked = _lock_user(teacher.pk)
    if get_balance(locked) < 1:
        raise CreditError("You need at least one credit to invite a student.")
    return _apply_delta(
        locked,
        delta=-1,
        reason=CreditLedger.REASON_INVITE_SPEND,
        actor=teacher,
        related_invite_id=invite_id,
        note=f"Student invite #{invite_id}",
        seat_debit_delta=1,
    )


@transaction.atomic
def reimburse_invite_credit(*, invite_id: int, teacher, actor=None) -> CreditLedger | None:
    """Reimburse the seat credit for a voided/unused invite (idempotent)."""
    if CreditLedger.objects.filter(
        reason=CreditLedger.REASON_INVITE_VOID_REIMBURSE,
        related_invite_id=invite_id,
    ).exists():
        return None

    spend = (
        CreditLedger.objects.filter(
            reason=CreditLedger.REASON_INVITE_SPEND,
            related_invite_id=invite_id,
        )
        .select_related("user")
        .first()
    )
    if spend is None:
        return None

    beneficiary = spend.user
    locked = _lock_user(beneficiary.pk)
    return _apply_delta(
        locked,
        delta=1,
        reason=CreditLedger.REASON_INVITE_VOID_REIMBURSE,
        actor=actor or teacher,
        related_invite_id=invite_id,
        note=f"Reimburse unused invite #{invite_id}",
        seat_reimburse_delta=1,
    )


@transaction.atomic
def link_invite_spend_to_enrollment(*, invite_id: int, enrollment_id: int) -> int:
    return CreditLedger.objects.filter(
        reason=CreditLedger.REASON_INVITE_SPEND,
        related_invite_id=invite_id,
        related_enrollment_id__isnull=True,
    ).update(related_enrollment_id=enrollment_id)


@transaction.atomic
def reimburse_kick_credit(*, enrollment_id: int, actor=None) -> CreditLedger | None:
    if CreditLedger.objects.filter(
        reason=CreditLedger.REASON_KICK_REIMBURSE,
        related_enrollment_id=enrollment_id,
    ).exists():
        return None

    spend = (
        CreditLedger.objects.filter(
            reason=CreditLedger.REASON_INVITE_SPEND,
            related_enrollment_id=enrollment_id,
        )
        .select_related("user")
        .first()
    )
    if spend is None:
        return None

    locked = _lock_user(spend.user_id)
    return _apply_delta(
        locked,
        delta=1,
        reason=CreditLedger.REASON_KICK_REIMBURSE,
        actor=actor,
        related_enrollment_id=enrollment_id,
        related_invite_id=spend.related_invite_id,
        note=f"Reimburse kick within reimbursement window (enrollment #{enrollment_id})",
        seat_reimburse_delta=1,
    )


def _would_be_locked_after(user: UserProfile, balance_after: int) -> bool:
    if getattr(user, "user_type", None) == "IT_Support":
        return False
    net = net_unreimbursed_seat_spend(user)
    return balance_after < 1 and net < 1


@transaction.atomic
def transfer_credits(from_user, to_user, amount: int, *, note: str | None = None) -> tuple[CreditLedger, CreditLedger]:
    amount = parse_positive_credit_quantity(amount)
    if from_user.pk == to_user.pk:
        raise CreditError("Cannot transfer credits to yourself.")
    sender_type = getattr(from_user, "user_type", None)
    recipient_type = getattr(to_user, "user_type", None)
    if sender_type == "Teacher":
        if recipient_type != "Teacher":
            raise CreditError("Teachers can only transfer credits to other Teacher accounts.")
    elif sender_type == "IT_Support":
        if recipient_type not in ("Teacher", "IT_Support"):
            raise CreditError("Credits can only be sent to Teacher or IT Support accounts.")
    else:
        raise CreditError("Only Teacher or IT Support accounts can transfer credits.")

    ids = sorted([from_user.pk, to_user.pk])
    locked_map = {
        u.pk: u
        for u in UserProfile.objects.select_for_update().filter(pk__in=ids)
    }
    sender = locked_map[from_user.pk]
    recipient = locked_map[to_user.pk]

    if get_balance(sender) < amount:
        raise CreditError("Insufficient credits to transfer.")

    balance_after = get_balance(sender) - amount
    if _would_be_locked_after(sender, balance_after):
        raise CreditError(
            "You cannot transfer your last unlock credit while you have no "
            "unreimbursed student seats. Keep at least one credit, or use a seat "
            "invite that is not reimbursed before transferring the rest."
        )

    note_text = (note or "").strip() or None
    out_row = _apply_delta(
        sender,
        delta=-amount,
        reason=CreditLedger.REASON_TRANSFER_OUT,
        actor=sender,
        note=note_text or f"Transfer to {recipient.username}",
    )
    in_row = _apply_delta(
        recipient,
        delta=amount,
        reason=CreditLedger.REASON_TRANSFER_IN,
        actor=sender,
        note=note_text or f"Transfer from {sender.username}",
        acquired_delta=amount,
    )
    return out_row, in_row


@transaction.atomic
def create_pending_purchase(
    user,
    pack_size: int,
    *,
    note: str | None = None,
    invoice: CreditInvoice | None = None,
    provider: str = CreditPurchase.PROVIDER_ALLOTMENT_REQUEST,
) -> CreditPurchase:
    """Create a credit purchase/request row (pending until completed)."""
    pack = quote_pack(pack_size)
    if pack.size < 1 or pack.total_amount <= 0 or pack.unit_price <= 0:
        raise CreditError("Purchase quantity and amounts must be positive.")
    provider_value = (provider or CreditPurchase.PROVIDER_ALLOTMENT_REQUEST).strip()
    return CreditPurchase.objects.create(
        user=user,
        pack_size=pack.size,
        list_unit_price=pack.list_unit_price,
        unit_price=pack.unit_price,
        discount_percent=pack.discount_percent,
        total_amount=pack.total_amount,
        status=CreditPurchase.STATUS_PENDING,
        provider=provider_value,
        note=(note or "").strip() or None,
        invoice=invoice,
        creation_date=timezone.now(),
    )


def _apply_checkout_fulfillment_fields(purchase: CreditPurchase) -> list[str]:
    """Populate purchase-history fields for website checkout (no admin approval)."""
    credited = parse_positive_credit_quantity(purchase.pack_size)
    money = Decimal(purchase.total_amount).quantize(Decimal("0.01"))
    when = purchase.completed_at or timezone.now()
    invoice_day = when.date() if isinstance(when, datetime) else when
    org = (getattr(purchase.user, "organization", None) or "").strip() or None
    purchase.money_spent = money
    purchase.credits_gained = credited
    purchase.invoice_dated = invoice_day
    purchase.paid_by = "Website checkout"
    purchase.payer_organization = (org[:255] if org else None)
    purchase.approval_notes = None
    purchase.approved_by = None
    purchase.approved_at = None
    return [
        "money_spent",
        "credits_gained",
        "invoice_dated",
        "paid_by",
        "payer_organization",
        "approval_notes",
        "approved_by",
        "approved_at",
    ]


def _apply_admin_approval_fields(
    purchase: CreditPurchase,
    details: PurchaseApprovalDetails,
    *,
    approver,
) -> list[str]:
    """Store required invoice verification fields and record the approving admin."""
    credited = details.credits_gained
    money = details.money_spent
    pack = quote_pack(credited)
    # Keep pack_size in sync with credits granted; store actual money from invoice.
    purchase.pack_size = credited
    purchase.list_unit_price = pack.list_unit_price
    purchase.discount_percent = pack.discount_percent
    purchase.total_amount = money
    purchase.unit_price = (money / Decimal(credited)).quantize(Decimal("0.01"))
    purchase.money_spent = money
    purchase.credits_gained = credited
    purchase.invoice_dated = details.invoice_dated
    purchase.paid_by = details.paid_by
    purchase.payer_organization = details.payer_organization
    approver_name = getattr(approver, "username", None) or "IT Support"
    approver_line = f"Approved by {approver_name}"
    if details.approval_notes:
        purchase.approval_notes = f"{details.approval_notes}\n{approver_line}"
    else:
        purchase.approval_notes = approver_line
    purchase.approved_by = approver if getattr(approver, "pk", None) else None
    purchase.approved_at = timezone.now()
    return [
        "pack_size",
        "list_unit_price",
        "unit_price",
        "discount_percent",
        "total_amount",
        "money_spent",
        "credits_gained",
        "invoice_dated",
        "paid_by",
        "payer_organization",
        "approval_notes",
        "approved_by",
        "approved_at",
    ]


@transaction.atomic
def complete_checkout_purchase(
    user,
    pack_size: int,
    *,
    note: str | None = None,
) -> tuple[CreditPurchase, CreditLedger]:
    """
    Direct teacher checkout: quote, record purchase, and grant credits immediately.

    No admin validation — payment (or stub checkout) is treated as already settled.
    """
    purchase = create_pending_purchase(
        user,
        pack_size,
        note=note,
        provider=CreditPurchase.PROVIDER_CHECKOUT,
    )
    ledger = complete_purchase(
        purchase,
        actor=user,
        note=note or "Checkout purchase",
    )
    purchase.refresh_from_db()
    return purchase, ledger


@transaction.atomic
def complete_purchase(
    purchase: CreditPurchase,
    *,
    actor=None,
    note: str | None = None,
    pack_size: int | None = None,
    approval: PurchaseApprovalDetails | None = None,
) -> CreditLedger:
    """
    Fulfill a pending purchase by adding its credits.

    Allotment requests require ``approval`` details from the verifying admin.
    Website checkout auto-fills purchase-history fields without an approver.
    """
    purchase = CreditPurchase.objects.select_for_update().get(pk=purchase.pk)
    if purchase.status == CreditPurchase.STATUS_COMPLETED:
        existing = CreditLedger.objects.filter(
            reason=CreditLedger.REASON_PURCHASE,
            related_purchase=purchase,
        ).first()
        if existing:
            return existing
        raise CreditError("Purchase already completed without a ledger row.")
    if purchase.status == CreditPurchase.STATUS_CANCELED:
        raise CreditError("Canceled purchases cannot be completed.")
    if purchase.status == CreditPurchase.STATUS_REJECTED:
        raise CreditError("Rejected purchases cannot be completed.")

    needs_admin_approval = purchase.provider in (
        CreditPurchase.PROVIDER_ALLOTMENT_REQUEST,
        CreditPurchase.PROVIDER_STUB,
    )
    if needs_admin_approval and approval is None:
        raise CreditError(
            "Invoice approval details are required to verify this allotment request."
        )
    if not needs_admin_approval and approval is not None:
        raise CreditError("Website checkout purchases do not use invoice approval details.")

    update_fields = ["status", "completed_at", "note"]
    if approval is not None:
        if actor is None or getattr(actor, "user_type", None) != "IT_Support":
            raise CreditError("Only IT Support can verify allotment requests.")
        update_fields.extend(
            _apply_admin_approval_fields(purchase, approval, approver=actor)
        )
        credited = approval.credits_gained
        ledger_note = (
            purchase.approval_notes
            or note
            or f"Verified allotment of {credited} credits"
        )
    else:
        if pack_size is not None:
            pack = quote_pack(pack_size)
            purchase.pack_size = pack.size
            purchase.list_unit_price = pack.list_unit_price
            purchase.unit_price = pack.unit_price
            purchase.discount_percent = pack.discount_percent
            purchase.total_amount = pack.total_amount
            update_fields.extend(
                [
                    "pack_size",
                    "list_unit_price",
                    "unit_price",
                    "discount_percent",
                    "total_amount",
                ]
            )
        credited = parse_positive_credit_quantity(purchase.pack_size)
        if purchase.total_amount is None or Decimal(purchase.total_amount) <= 0:
            raise CreditError("Purchase total must be a positive amount.")
        if purchase.unit_price is None or Decimal(purchase.unit_price) <= 0:
            raise CreditError("Purchase unit price must be a positive amount.")
        purchase.status = CreditPurchase.STATUS_COMPLETED
        purchase.completed_at = timezone.now()
        update_fields.extend(_apply_checkout_fulfillment_fields(purchase))
        ledger_note = note or f"Completed pack of {credited}"
        if note:
            purchase.note = ((purchase.note or "") + "\n" + note).strip()
        purchase.save(update_fields=list(dict.fromkeys(update_fields)))
        return acquire_credits(
            purchase.user,
            credited,
            reason=CreditLedger.REASON_PURCHASE,
            actor=actor or purchase.user,
            note=ledger_note,
            related_purchase=purchase,
            invoice=purchase.invoice,
        )

    purchase.status = CreditPurchase.STATUS_COMPLETED
    purchase.completed_at = timezone.now()
    if approval.approval_notes:
        purchase.note = (
            ((purchase.note or "") + "\n" + approval.approval_notes).strip()
        )
    elif note:
        purchase.note = ((purchase.note or "") + "\n" + note).strip()
    purchase.save(update_fields=list(dict.fromkeys(update_fields)))

    return acquire_credits(
        purchase.user,
        credited,
        reason=CreditLedger.REASON_PURCHASE,
        actor=actor or purchase.user,
        note=ledger_note,
        related_purchase=purchase,
        invoice=purchase.invoice,
    )


@transaction.atomic
def cancel_purchase(
    purchase: CreditPurchase,
    *,
    actor=None,
    note: str | None = None,
) -> CreditPurchase:
    """Legacy cancel (optional note). Prefer ``reject_purchase`` for allotments."""
    purchase = CreditPurchase.objects.select_for_update().get(pk=purchase.pk)
    if purchase.status == CreditPurchase.STATUS_COMPLETED:
        raise CreditError("Completed purchases cannot be canceled.")
    if purchase.status in (
        CreditPurchase.STATUS_CANCELED,
        CreditPurchase.STATUS_REJECTED,
    ):
        return purchase
    purchase.status = CreditPurchase.STATUS_CANCELED
    cancel_note = (note or "").strip() or "Canceled by IT Support"
    actor_name = getattr(actor, "username", None) or "IT Support"
    purchase.note = (
        ((purchase.note or "") + f"\n[{actor_name}] {cancel_note}").strip()
    )
    purchase.save(update_fields=["status", "note"])
    return purchase


@transaction.atomic
def reject_purchase(
    purchase: CreditPurchase,
    *,
    actor,
    note: str,
) -> CreditPurchase:
    """
    Reject a pending allotment request. Requires a rejection reason note.
    No credits are granted. Decision is retained for admin/teacher history.
    """
    if actor is None or getattr(actor, "user_type", None) != "IT_Support":
        raise CreditError("Only IT Support can reject allotment requests.")
    reason = (note or "").strip()
    if not reason:
        raise CreditError("A rejection reason is required.")

    purchase = CreditPurchase.objects.select_for_update().get(pk=purchase.pk)
    if purchase.status == CreditPurchase.STATUS_COMPLETED:
        raise CreditError("Completed purchases cannot be rejected.")
    if purchase.status == CreditPurchase.STATUS_REJECTED:
        return purchase
    if purchase.status == CreditPurchase.STATUS_CANCELED:
        raise CreditError("Canceled purchases cannot be rejected.")
    if purchase.status != CreditPurchase.STATUS_PENDING:
        raise CreditError("Only pending requests can be rejected.")

    actor_name = getattr(actor, "username", None) or "IT Support"
    purchase.status = CreditPurchase.STATUS_REJECTED
    purchase.approval_notes = f"{reason}\nRejected by {actor_name}"
    purchase.approved_by = actor
    purchase.approved_at = timezone.now()
    purchase.note = (
        ((purchase.note or "") + f"\n[Rejected by {actor_name}] {reason}").strip()
    )
    purchase.save(
        update_fields=[
            "status",
            "approval_notes",
            "approved_by",
            "approved_at",
            "note",
        ]
    )
    return purchase


@transaction.atomic
def attach_invoice_to_purchase(
    purchase: CreditPurchase,
    invoice: CreditInvoice,
    *,
    replace: bool = False,
) -> CreditPurchase:
    """Link an invoice to a purchase; copy onto completed purchase ledger rows."""
    purchase = CreditPurchase.objects.select_for_update().get(pk=purchase.pk)
    if purchase.invoice_id and not replace:
        raise CreditError("This purchase already has an invoice attached.")
    if invoice.owner_user_id != purchase.user_id:
        raise CreditError("Invoice owner must match the purchase account.")
    purchase.invoice = invoice
    purchase.save(update_fields=["invoice"])
    if purchase.status == CreditPurchase.STATUS_COMPLETED:
        CreditLedger.objects.filter(
            related_purchase=purchase,
            invoice__isnull=True,
        ).update(invoice=invoice)
    return purchase


@transaction.atomic
def attach_invoice_to_ledger(
    ledger: CreditLedger,
    invoice: CreditInvoice,
    *,
    replace: bool = False,
) -> CreditLedger:
    ledger = CreditLedger.objects.select_for_update().get(pk=ledger.pk)
    if ledger.invoice_id and not replace:
        raise CreditError("This credit activity already has an invoice attached.")
    if invoice.owner_user_id != ledger.user_id:
        raise CreditError("Invoice owner must match the credit account.")
    ledger.invoice = invoice
    ledger.save(update_fields=["invoice"])
    if ledger.related_purchase_id:
        purchase = CreditPurchase.objects.select_for_update().filter(
            pk=ledger.related_purchase_id
        ).first()
        if purchase and (not purchase.invoice_id or replace):
            purchase.invoice = invoice
            purchase.save(update_fields=["invoice"])
    return ledger


def resolve_credit_user_lookup(
    raw: str,
    *,
    allowed_types: tuple[str, ...] = ("Teacher",),
) -> UserProfile:
    """Resolve username/email to a user restricted to ``allowed_types``."""
    value = (raw or "").strip()
    if not value:
        raise CreditError("Enter a username or email.")
    user = UserProfile.objects.filter(
        Q(username__iexact=value) | Q(user_email__iexact=value)
    ).first()
    if user is None:
        if allowed_types == ("Teacher",):
            raise CreditError(f"No Teacher account matches “{value}”.")
        raise CreditError(f"No matching account for “{value}”.")
    if user.user_type not in allowed_types:
        if allowed_types == ("Teacher",):
            raise CreditError(
                f"“{user.username}” is {user.user_type}, not a Teacher. "
                "Credits can only be transferred to Teacher accounts."
            )
        raise CreditError(
            f"“{user.username}” is {user.user_type}. "
            "Credits can only be sent to Teacher or IT Support accounts."
        )
    return user


def resolve_teacher_lookup(raw: str) -> UserProfile:
    """Teacher-only recipient lookup (peer transfers)."""
    return resolve_credit_user_lookup(raw, allowed_types=("Teacher",))


def resolve_admin_credit_target(raw: str) -> UserProfile:
    """IT Support grant/revoke targets: Teachers and other admins."""
    return resolve_credit_user_lookup(
        raw, allowed_types=("Teacher", "IT_Support")
    )


def ledger_reason_label(reason: str) -> str:
    return {
        CreditLedger.REASON_PURCHASE: "Purchase",
        CreditLedger.REASON_ADMIN_GRANT: "Admin grant",
        CreditLedger.REASON_ADMIN_REVOKE: "Admin revoke",
        CreditLedger.REASON_TRANSFER_IN: "Transfer received",
        CreditLedger.REASON_TRANSFER_OUT: "Transfer sent",
        CreditLedger.REASON_INVITE_SPEND: "Student invite",
        CreditLedger.REASON_INVITE_VOID_REIMBURSE: "Invite voided / unused",
        CreditLedger.REASON_KICK_REIMBURSE: "Student removed (≤7 days)",
        CreditLedger.REASON_ADJUSTMENT: "Adjustment",
    }.get(reason, reason)
