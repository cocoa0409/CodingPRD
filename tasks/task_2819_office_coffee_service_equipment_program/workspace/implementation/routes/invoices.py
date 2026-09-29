"""Invoice assembly, issuance and credits (PRD 3.8).

Draft assembly is not a read-only projection: it writes placements, assets and work
orders as it goes. Because an assembly that produces no billable line is refused
outright, every line and every side effect is staged first and committed only once
the draft is known to be non-empty.
"""
from datetime import timedelta

from flask import Blueprint

import calc
import lookup
import numbers_util
import serializers
import shape
from authz import (ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_CUSTOMER_CONTACT,
                   authenticate)
from envelope import created, ok
from errors import ApiError
from store import bump, db, insert, now, ordered, snapshot, touch
from timeutil import UTC

bp = Blueprint("invoices", __name__)

READ_ROLES = (ROLE_BILLING_SPECIALIST, ROLE_ACCOUNT_MANAGER, ROLE_CUSTOMER_CONTACT)

BILLABLE_LINE_TYPES = ("PRODUCT", "RENT", "SHORTFALL", "UNRETURNED_ASSET")
RENT_BILLABLE_PLACEMENT_STATUSES = ("ACTIVE", "RETRIEVAL_SCHEDULED")
BREADTH_MIN_CATEGORIES = 3
TIER_HIGH_BPS = 500
TIER_HIGH_FLOOR_CENTS = 100000
TIER_MID_BPS = 300
TIER_MID_FLOOR_CENTS = 50000
TIER_TWO_CATEGORY_BPS = 100
FREE_FREIGHT_THRESHOLD_CENTS = 50000
FREIGHT_FEE_CENTS = 2500
CREDITABLE_INVOICE_STATUSES = ("ISSUED", "PARTIALLY_CREDITED")


def _staged_line(site_id, line_type, amount_cents, product_id=None, qty_units=0,
                 unit_price_micros=0):
    return {
        "site_id": site_id,
        "target_line_id": None,
        "line_type": line_type,
        "product_id": product_id,
        "qty_units": qty_units,
        "unit_price_micros": unit_price_micros,
        "amount_cents": amount_cents,
        "credits_applied_cents": 0,
        "credit_reason": None,
    }


def _allied_discount_bps(allied_category_count, pre_freight_total_cents):
    """Tier selection of assembly step 4, keyed on the step-2 total and never on a
    post-discount one."""
    if allied_category_count >= BREADTH_MIN_CATEGORIES \
            and pre_freight_total_cents >= TIER_HIGH_FLOOR_CENTS:
        return TIER_HIGH_BPS
    if allied_category_count >= BREADTH_MIN_CATEGORIES \
            and pre_freight_total_cents >= TIER_MID_FLOOR_CENTS:
        return TIER_MID_BPS
    if allied_category_count == 2:
        return TIER_TWO_CATEGORY_BPS
    return 0


def _period_overlaps(account, site_id, period_start, period_end):
    """Closed intervals, so sharing a single endpoint instant counts as an overlap."""
    for invoice in db.invoices.values():
        if invoice["account_id"] != account["id"]:
            continue
        if invoice["invoice_status"] == "VOID":
            continue
        if site_id is not None and invoice["site_id"] != site_id:
            continue
        if period_start <= invoice["period_end"] and invoice["period_start"] <= period_end:
            return True
    return False


def _product_lines(sites, period_start, period_end, staged, subtotals, categories):
    """Assembly step 1 for PRODUCT lines: one per delivered visit line, priced from the
    snapshot taken at completion and rounded individually."""
    for site in sites:
        for visit in ordered([v for v in calc.site_visits(site["id"])
                              if v["visit_status"] == "COMPLETED"]):
            if not (period_start <= visit["window_start"] <= period_end):
                continue
            for line in visit.get("lines") or []:
                delivered = line.get("delivered_units") or 0
                if delivered <= 0:
                    continue
                price = line.get("effective_unit_price_micros") or 0
                amount = calc.line_amount_cents(delivered, price)
                staged.append(_staged_line(site["id"], "PRODUCT", amount,
                                           product_id=line["product_id"],
                                           qty_units=delivered,
                                           unit_price_micros=price))
                subtotals[site["id"]] = subtotals.get(site["id"], 0) + amount
                product = db.product_items.get(line["product_id"])
                if product is not None and product["category"] != "COFFEE":
                    categories.add(product["category"])


def _rent_lines(sites, period_start, period_end, staged, mutations):
    """One RENT line per RENTAL placement billable in the period whose prorated rent is
    non-zero. A LOAN placement never produces one."""
    for site in sites:
        for placement in ordered(calc.site_placements(site["id"])):
            if placement["terms_type"] != "RENTAL":
                continue
            if placement["placement_status"] not in RENT_BILLABLE_PLACEMENT_STATUSES:
                continue
            rent = calc.rent_charge_cents(placement, period_start, period_end)
            mutations.append(_set_rent(placement, rent))
            if rent != 0:
                staged.append(_staged_line(site["id"], "RENT", rent))


def _set_rent(placement, rent):
    def apply():
        before = snapshot(placement)
        placement["rent_charge_cents"] = rent
        touch(placement, before)
    return apply


def _shortfall_lines(sites, staged, mutations, emitted_placement_ids):
    """One SHORTFALL line per placement carrying an accrued fee."""
    for site in sites:
        for placement in ordered(calc.site_placements(site["id"])):
            if placement["compliance_status"] != "SHORTFALL_BILLED":
                continue
            if placement["shortfall_fee_cents"] <= 0:
                continue
            staged.append(_staged_line(site["id"], "SHORTFALL",
                                       placement["shortfall_fee_cents"]))
            emitted_placement_ids.append(placement["id"])
            mutations.append(_mark_shortfall_emitted(placement))


def _mark_shortfall_emitted(placement):
    def apply():
        # Internal bookkeeping only: once the accrual has reached an invoice it is the
        # invoice's business, so returning to MEETING_MINIMUM no longer clears it.
        placement["_shortfall_line_emitted"] = True
    return apply


def _unreturned_placement_lines(sites, staged, mutations):
    """A RETRIEVAL_SCHEDULED placement whose own retrieval_due_by is behind the current
    instant is billed for the equipment and moves to UNRETURNED_BILLED."""
    current = now()
    for site in sites:
        for placement in ordered(calc.site_placements(site["id"])):
            if placement["placement_status"] != "RETRIEVAL_SCHEDULED":
                continue
            due = placement.get("retrieval_due_by")
            if due is None or current <= due:
                continue
            asset = db.equipment_assets.get(placement["asset_id"])
            if asset is None:
                continue
            amount = calc.unreturned_asset_charge(asset, placement["placed_at"])
            staged.append(_staged_line(site["id"], "UNRETURNED_ASSET", amount))
            mutations.append(_bill_unreturned_placement(placement, asset, amount))


def _bill_unreturned_placement(placement, asset, amount):
    def apply():
        placement["unreturned_billed_cents"] = amount
        placement["placement_status"] = "UNRETURNED_BILLED"
        bump(placement)
        asset["asset_status"] = "UNRETURNED"
        bump(asset)
    return apply


def _loaner_writeoff_lines(sites, staged, mutations):
    """PRD 3.6: an OUT loaner past its due date is promoted to OVERDUE in this pass, and
    an OVERDUE loaner more than 30 days past due is written off with its own line."""
    today = now().astimezone(UTC).date()
    site_ids = [s["id"] for s in sites]
    for work_order in ordered([w for w in db.work_orders.values()
                               if w["site_id"] in site_ids]):
        status = work_order["loaner_status"]
        due_back = work_order.get("loaner_due_back_date")
        if due_back is None:
            continue
        due_back_date = due_back.astimezone(UTC).date()
        promoted = status == "OUT" and today > due_back_date
        if promoted:
            status = "OVERDUE"
        writes_off = (status == "OVERDUE"
                      and today > due_back_date + timedelta(days=calc.LOANER_WRITEOFF_DAYS))
        loaner = db.equipment_assets.get(work_order.get("loaner_asset_id"))
        if not writes_off or loaner is None:
            # A promotion that is not followed by a write-off still has to be recorded.
            if promoted:
                mutations.append(_promote_loaner_overdue(work_order))
            continue
        # The months in service are measured from loaner_out_date, not a placement date.
        amount = calc.unreturned_asset_charge(loaner, work_order["loaner_out_date"])
        staged.append(_staged_line(work_order["site_id"], "UNRETURNED_ASSET", amount))
        mutations.append(_write_off_loaner(work_order, loaner))


def _promote_loaner_overdue(work_order):
    def apply():
        work_order["loaner_status"] = "OVERDUE"
        bump(work_order)
    return apply


def _write_off_loaner(work_order, loaner):
    def apply():
        work_order["loaner_status"] = "WRITTEN_OFF"
        bump(work_order)
        loaner["asset_status"] = "UNRETURNED"
        bump(loaner)
    return apply


@bp.post("/ocs/consolidated-invoices")
def assemble_invoice():
    authenticate((ROLE_BILLING_SPECIALIST,))
    fields = shape.fields()
    account_id = fields.string("account_id", min_len=1)
    period_start = fields.instant("period_start")
    period_end = fields.instant("period_end")
    expected_account_version = fields.integer("expected_account_version")
    site_id = fields.string("site_id", required=False, min_len=1)

    account = lookup.account(account_id)
    requested_site = lookup.site(site_id) if site_id is not None else None

    # The order below is pinned by PRD 3.8: stale account, period well-formedness,
    # period overlap, site-in-account, billing-mode scope, empty invoice last.
    if expected_account_version != account["version"]:
        raise ApiError("ERR_STALE_ACCOUNT_VERSION",
                       "The account has moved on since it was last read.")
    if period_end <= period_start or period_end > now():
        raise ApiError("ERR_PERIOD_INVALID",
                       "The billing period must be well-formed and closed.")
    overlap_site = site_id if account["billing_mode"] == "PER_SITE" else None
    if _period_overlaps(account, overlap_site, period_start, period_end):
        raise ApiError("ERR_INVOICE_PERIOD_OVERLAP",
                       "Another invoice already covers an overlapping period.")
    if requested_site is not None and requested_site["account_id"] != account["id"]:
        raise ApiError("ERR_SITE_NOT_IN_ACCOUNT",
                       "The named site belongs to a different account.")
    if account["billing_mode"] == "CONSOLIDATED" and site_id is not None:
        raise ApiError("ERR_BILLING_MODE_MISMATCH",
                       "A CONSOLIDATED account is invoiced whole; site_id must be absent.")
    if account["billing_mode"] == "PER_SITE" and site_id is None:
        raise ApiError("ERR_BILLING_MODE_MISMATCH",
                       "A PER_SITE account is invoiced one site at a time; site_id is "
                       "required.")

    if requested_site is not None:
        sites = [requested_site]
    else:
        sites = ordered(calc.account_sites(account["id"]))

    staged = []
    mutations = []
    subtotals = {}
    categories = set()
    shortfall_placement_ids = []

    _product_lines(sites, period_start, period_end, staged, subtotals, categories)
    _rent_lines(sites, period_start, period_end, staged, mutations)
    _shortfall_lines(sites, staged, mutations, shortfall_placement_ids)
    _unreturned_placement_lines(sites, staged, mutations)
    _loaner_writeoff_lines(sites, staged, mutations)

    # Step 8's rejection is keyed on the billable lines: were it keyed on every row the
    # freight line would make an empty invoice impossible, and the code unreachable.
    if not [l for l in staged if l["line_type"] in BILLABLE_LINE_TYPES]:
        raise ApiError("ERR_NO_BILLABLE_LINES",
                       "The period produced nothing billable for this scope.")

    # Step 2: the one total the discount tier and the freight waiver are keyed on.
    pre_freight_total = sum(l["amount_cents"] for l in staged)
    allied_category_count = len(categories)
    allied_discount_bps = _allied_discount_bps(allied_category_count, pre_freight_total)

    # Step 5: one negative line per site with a non-zero result, rounded once per site.
    allied_discount_cents = 0
    for site in sites:
        subtotal = subtotals.get(site["id"], 0)
        discount = numbers_util.apply_bps(subtotal, allied_discount_bps)
        if discount != 0:
            staged.append(_staged_line(site["id"], "ALLIED_DISCOUNT", -discount))
            allied_discount_cents += discount

    # Step 6: an invoice that clears the threshold BEFORE the discount keeps free freight.
    freight_cents = 0 if pre_freight_total >= FREE_FREIGHT_THRESHOLD_CENTS \
        else FREIGHT_FEE_CENTS
    if freight_cents > 0:
        staged.append(_staged_line(None, "FREIGHT", freight_cents))

    total_cents = pre_freight_total - allied_discount_cents + freight_cents

    invoice = insert(db.invoices, {
        "account_id": account["id"],
        "site_id": site_id,
        "period_start": period_start,
        "period_end": period_end,
        "invoice_status": "DRAFT",
        "allied_category_count": allied_category_count,
        "allied_discount_bps": allied_discount_bps,
        "pre_freight_total_cents": pre_freight_total,
        "allied_discount_cents": allied_discount_cents,
        "freight_cents": freight_cents,
        "total_cents": total_cents,
        "line_count": len(staged),
        "issued_at": None,
        "_pre_credit_total_cents": total_cents,
        "_shortfall_placement_ids": shortfall_placement_ids,
    })
    for line in staged:
        line["invoice_id"] = invoice["id"]
        insert(db.invoice_lines, line)
    for mutation in mutations:
        mutation()
    bump(account)
    return created(serializers.invoice(invoice))


@bp.get("/ocs/consolidated-invoices")
def list_invoices():
    authenticate(READ_ROLES)
    rows = lookup.eq_filter(list(db.invoices.values()), "account_id")
    rows = lookup.eq_filter(rows, "site_id")
    rows = lookup.eq_filter(rows, "invoice_status")
    return lookup.listing(rows, serializers.invoice)


@bp.get("/ocs/consolidated-invoices/<invoice_id>")
def read_invoice(invoice_id):
    authenticate(READ_ROLES)
    return ok(serializers.invoice(lookup.invoice(invoice_id)))


@bp.post("/ocs/consolidated-invoices/<invoice_id>/issue")
def issue_invoice(invoice_id):
    authenticate((ROLE_BILLING_SPECIALIST,))
    invoice = lookup.invoice(invoice_id)
    account = db.accounts.get(invoice["account_id"])
    # Rung 11 precedes rung 18: a closed account refuses issuance before the invoice's
    # own lifecycle is consulted.
    if account is None or account["program_posture"] == "CLOSED":
        raise ApiError("ERR_ACCOUNT_NOT_OPERATING",
                       "A closed account cannot be invoiced.")
    if invoice["invoice_status"] != "DRAFT":
        raise ApiError("ERR_INVOICE_STATE_INVALID",
                       "Invoice state %s cannot be issued." % invoice["invoice_status"])
    if invoice["line_count"] < 1:
        raise ApiError("ERR_NO_BILLABLE_LINES", "An empty invoice cannot be issued.")

    invoice["invoice_status"] = "ISSUED"
    invoice["issued_at"] = now()
    bump(invoice)
    account["receivable_balance_cents"] = (account["receivable_balance_cents"]
                                          + invoice["total_cents"])
    account["allied_attachment_bps"] = calc.allied_attachment_bps(account["id"])
    bump(account)
    # The accrual has now been billed and must not be billed twice.
    for placement_id in invoice.get("_shortfall_placement_ids") or []:
        placement = db.equipment_placements.get(placement_id)
        if placement is not None and placement["shortfall_fee_cents"] != 0:
            placement["shortfall_fee_cents"] = 0
            bump(placement)
    return ok(serializers.invoice(invoice))


@bp.post("/ocs/consolidated-invoices/<invoice_id>/credit")
def credit_invoice(invoice_id):
    authenticate((ROLE_BILLING_SPECIALIST,))
    fields = shape.fields()
    target_line_id = fields.string("target_line_id", min_len=1)
    amount_cents = fields.integer("amount_cents")
    credit_reason = fields.string("credit_reason", min_len=1)

    invoice = lookup.invoice(invoice_id)
    target = lookup.invoice_line(target_line_id)
    if invoice["invoice_status"] not in CREDITABLE_INVOICE_STATUSES:
        raise ApiError("ERR_INVOICE_STATE_INVALID",
                       "Invoice state %s cannot be credited." % invoice["invoice_status"])
    if target["invoice_id"] != invoice["id"] or target["line_type"] == "CREDIT":
        raise ApiError("ERR_CREDIT_TARGET_MISMATCH",
                       "The target line must belong to this invoice and must not itself "
                       "be a credit.")
    credited = sum(-l["amount_cents"] for l in calc.invoice_lines_of(invoice["id"])
                   if l["line_type"] == "CREDIT")
    pre_credit_total = invoice.get("_pre_credit_total_cents", invoice["total_cents"])
    if amount_cents <= 0 or (credited + amount_cents) > pre_credit_total:
        raise ApiError("ERR_CREDIT_EXCEEDS_INVOICE_TOTAL",
                       "The credit must be positive and within the invoice total.")

    line = insert(db.invoice_lines, {
        "invoice_id": invoice["id"],
        # A credit line's site_id is null only when the line it credits had none.
        "site_id": target["site_id"],
        "target_line_id": target["id"],
        "line_type": "CREDIT",
        "product_id": None,
        "qty_units": 0,
        "unit_price_micros": 0,
        "amount_cents": -amount_cents,
        "credits_applied_cents": 0,
        "credit_reason": credit_reason,
    })
    target["credits_applied_cents"] = target["credits_applied_cents"] + amount_cents
    bump(target)
    invoice["total_cents"] = sum(l["amount_cents"]
                                for l in calc.invoice_lines_of(invoice["id"]))
    invoice["line_count"] = invoice["line_count"] + 1
    cumulative = credited + amount_cents
    invoice["invoice_status"] = ("FULLY_CREDITED" if cumulative == pre_credit_total
                                else "PARTIALLY_CREDITED")
    bump(invoice)
    account = db.accounts.get(invoice["account_id"])
    if account is not None:
        account["receivable_balance_cents"] = (account["receivable_balance_cents"]
                                              - amount_cents)
        bump(account)
    return created(serializers.invoice_line(line))
