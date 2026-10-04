"""Partner ledger reconciliation and invoice ageing (PRD 2.10, 3.7)."""

import db
import timeutil
from services.rounding import Decimal, round_half_up

RATIO_SCALE = 4
PARTNER_CREDIT_CEILING_CENTS = 750000
ZERO_RATIO = Decimal("0.0000")


def invoices_of(partner_id):
    return [inv for inv in db.all_rows("invoices") if inv["partner_id"] == partner_id]


def open_invoices(partner_id):
    return [inv for inv in invoices_of(partner_id) if inv["status"] in ("ISSUED", "OVERDUE")]


def paid_invoices(partner_id):
    return [inv for inv in invoices_of(partner_id) if inv["status"] == "PAID"]


def outstanding_balance_cents(partner_id):
    return sum(inv["total_amount_cents"] for inv in open_invoices(partner_id))


def billed_cents(partner_id):
    total = 0
    for inv in invoices_of(partner_id):
        if inv["status"] in ("ISSUED", "OVERDUE", "PAID"):
            total += inv["total_amount_cents"]
    return total


def collected_cents(partner_id):
    return sum(inv["amount_paid_cents"] for inv in paid_invoices(partner_id))


def collection_ratio(partner_id):
    billed = billed_cents(partner_id)
    if billed == 0:
        return ZERO_RATIO
    return round_half_up(Decimal(collected_cents(partner_id)) / Decimal(billed), RATIO_SCALE)


def on_time_payment_ratio(partner_id):
    """Paid amounts over the amounts issued for this partner (PRD 2.10)."""
    denominator = billed_cents(partner_id)
    if denominator == 0:
        return ZERO_RATIO
    ratio = round_half_up(Decimal(collected_cents(partner_id)) / Decimal(denominator), RATIO_SCALE)
    if ratio < ZERO_RATIO:
        ratio = ZERO_RATIO
    if ratio > Decimal("1.0000"):
        ratio = Decimal("1.0000")
    return ratio


def oldest_open_due_date(partner_id):
    due_dates = [inv["due_date"] for inv in open_invoices(partner_id) if inv["due_date"] is not None]
    if not due_dates:
        return None
    return min(due_dates)


def has_overdue(partner_id):
    return any(inv["status"] == "OVERDUE" for inv in invoices_of(partner_id))


def has_overdue_before_today(partner_id):
    today = timeutil.today()
    for inv in invoices_of(partner_id):
        if inv["status"] == "OVERDUE" and inv["due_date"] is not None and inv["due_date"].date() < today:
            return True
    return False


def has_overdue_beyond_days(partner_id, days):
    """An OVERDUE invoice whose due date is strictly more than `days` before
    the logical-clock date."""
    today = timeutil.today()
    for inv in invoices_of(partner_id):
        if inv["status"] != "OVERDUE" or inv["due_date"] is None:
            continue
        if (today - inv["due_date"].date()).days > days:
            return True
    return False


def credit_hold_condition(partner_id):
    return has_overdue_before_today(partner_id)


def derived_status(partner, partner_id):
    if partner["status"] == "INACTIVE":
        return "INACTIVE"
    if has_overdue_beyond_days(partner_id, 30):
        return "SUSPENDED"
    return "ACTIVE"


def apply_derived(partner):
    """Recompute every derived billing field in place; no version bump.

    Returns True when at least one value moved, so callers can decide whether
    the recomputation counts as a mutation of the owning row (PRD 2.4).
    """
    if partner is None:
        return False
    partner_id = partner["id"]
    values = {
        "outstanding_balance_cents": outstanding_balance_cents(partner_id),
        "billed_cents": billed_cents(partner_id),
        "collected_cents": collected_cents(partner_id),
        "collection_ratio": collection_ratio(partner_id),
        "on_time_payment_ratio": on_time_payment_ratio(partner_id),
        "oldest_open_due_date": oldest_open_due_date(partner_id),
        "credit_hold": credit_hold_condition(partner_id),
        "status": derived_status(partner, partner_id),
    }
    changed = False
    for key, value in values.items():
        if partner.get(key) != value:
            partner[key] = value
            changed = True
    return changed


def refresh_partner(partner):
    """Recompute derived fields and bump the row when something moved."""
    if partner is None:
        return None
    if apply_derived(partner):
        db.touch(partner)
    return partner


def age_invoice(invoice):
    """ISSUED -> OVERDUE once the logical-clock date passes the due date."""
    if invoice["status"] != "ISSUED" or invoice["due_date"] is None:
        return False
    if timeutil.today() > invoice["due_date"].date():
        invoice["status"] = "OVERDUE"
        db.touch(invoice)
        return True
    return False


def sweep_invoices():
    """Age every stale invoice and reconcile the partners they belong to.

    Runs when the logical clock advances and again whenever an invoice or its
    partner is read, so a stale ISSUED reading is never served (PRD 2.6/3.7).
    """
    aged_partners = set()
    for invoice in db.all_rows("invoices"):
        if age_invoice(invoice):
            aged_partners.add(invoice["partner_id"])
    for partner_id in aged_partners:
        refresh_partner(db.get("partners", partner_id))
