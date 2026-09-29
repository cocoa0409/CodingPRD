"""Consortium settlement, the copyright report, the sweep and the clock."""
from flask import Blueprint

from db import base_row, db, iso_ms, now, touch
from errors import ApiError
from middleware import (ACCOUNTANT, ADMIN, ILL_STAFF, PARTNER_AGENT, auth,
                        get_invoice, get_lending_charge, get_partner, own_invoice,
                        own_partner_id)
from response import ok, ok_row
from routes.common import filter_eq, list_response
from services import calc, derive, sweep
from validate import (bad, body, opt_str, q_enum, q_int, q_str, raw_id, req_enum,
                      req_instant, req_int, req_str)

bp = Blueprint("finance", __name__)

SERVICE_TYPES = ("LOAN", "COPY")
CHARGE_STATUSES = ("OPEN", "INVOICED")
INVOICE_STATUSES = ("DRAFT", "ISSUED", "PAID", "DISPUTED", "SUPERSEDED")
SETTLE_ACTIONS = ("PAY", "DISPUTE", "REINSTATE")


@bp.route("/ill/lending-charges", methods=["POST"])
def create_lending_charge():
    auth(ACCOUNTANT, ILL_STAFF)
    data = body()
    # rung 32
    ref = raw_id(data, "partner_id")
    if ref is not None and ref not in db.partners:
        raise ApiError("ERR_PARTNER_NOT_FOUND")
    # rung 35
    partner_id = req_str(data, "partner_id")
    item_title = req_str(data, "item_title")
    service_type = req_enum(data, "service_type", SERVICE_TYPES)
    charge_cents = req_int(data, "charge_cents", 0)
    incurred_at = req_instant(data, "incurred_at")
    partner = db.partners[partner_id]
    row = base_row()
    row.update({
        "partner_id": partner_id,
        "item_title": item_title,
        "service_type": service_type,
        "charge_cents": charge_cents,
        "incurred_at": incurred_at,
        "status": "OPEN",
    })
    db.lending_charges[row["id"]] = row
    derive.recompute_partner(partner)
    return ok_row(row, 201)


@bp.route("/ill/lending-charges/<charge_id>", methods=["GET"])
def get_one_lending_charge(charge_id):
    auth(ACCOUNTANT, ILL_STAFF, ADMIN)
    return ok_row(get_lending_charge(charge_id))


@bp.route("/ill/partners/<partner_id>/lending-charges", methods=["GET"])
def list_partner_lending_charges(partner_id):
    user_id, role = auth(PARTNER_AGENT, ACCOUNTANT, ILL_STAFF, ADMIN)
    own_partner_id(partner_id, user_id, role)
    get_partner(partner_id)
    rows = [c for c in db.lending_charges.values() if c["partner_id"] == partner_id]
    rows = filter_eq(rows, "status", q_enum("status", CHARGE_STATUSES))
    return list_response(rows)


def _borrow_lines(partner_id, start, end):
    rows = [r for r in db.requests.values()
            if r.get("committed_partner_id") == partner_id
            and r["status"] not in ("CANCELLED", "UNFILLED")
            and r.get("fulfilled_at") is not None
            and start <= r["fulfilled_at"] < end]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def _lend_lines(partner_id, start, end):
    rows = [c for c in db.lending_charges.values()
            if c["partner_id"] == partner_id and c["status"] == "OPEN"
            and start <= c["incurred_at"] < end]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return rows


@bp.route("/ill/partners/<partner_id>/invoices", methods=["POST"])
def draft_invoice(partner_id):
    auth(ACCOUNTANT)
    partner = get_partner(partner_id)
    data = body()
    # rung 35
    period_month = req_str(data, "period_month")
    if not calc.PERIOD_MONTH_RE.match(period_month):
        bad("Field 'period_month' must be a YYYY-MM settlement period.")
    expected_version = req_int(data, "expected_partner_version", 0)
    # rung 48
    if expected_version != partner["version"]:
        raise ApiError("ERR_STALE_PARTNER_VERSION")
    start, end = calc.period_bounds(period_month)
    # a fresh draft supersedes any DRAFT already covering the same period
    for existing in db.invoices.values():
        if existing["partner_id"] == partner_id \
                and existing["period_month"] == period_month \
                and existing["status"] == "DRAFT":
            existing["status"] = "SUPERSEDED"
            touch(existing)
    borrow = _borrow_lines(partner_id, start, end)
    lend = _lend_lines(partner_id, start, end)
    # PRD 3.9: round each line, then sum the rounded values
    payable_total = sum(calc.surcharged(r["committed_fee_cents"] or 0)
                        for r in borrow)
    receivable_total = sum(calc.surcharged(c["charge_cents"] or 0) for c in lend)
    agreement = calc.applicable_agreement(partner_id, now())
    variant = agreement["settlement_mode"] if agreement is not None else "GROSS"
    if variant == "NET":
        net_amount = payable_total - receivable_total
    else:
        net_amount = payable_total
    row = base_row()
    row.update({
        "partner_id": partner_id,
        "period_month": period_month,
        "settlement_variant": variant,
        "direction": "PAYABLE" if net_amount >= 0 else "RECEIVABLE",
        "borrow_line_count": len(borrow),
        "lend_line_count": len(lend),
        "payable_total_cents": payable_total,
        "receivable_total_cents": receivable_total,
        "gross_amount_cents": payable_total,
        "net_amount_cents": net_amount,
        "status": "DRAFT",
        "issued_at": None,
        "settled_at": None,
        "dispute_reason": None,
    })
    db.invoices[row["id"]] = row
    touch(partner)
    return ok_row(row, 201)


@bp.route("/ill/invoices/<invoice_id>/issue", methods=["POST"])
def issue_invoice(invoice_id):
    auth(ACCOUNTANT)
    invoice = get_invoice(invoice_id)
    # rung 46
    if invoice["status"] != "DRAFT":
        raise ApiError("ERR_INVOICE_INVALID_STATE")
    start, end = calc.period_bounds(invoice["period_month"])
    # rung 67
    if now() < end:
        raise ApiError("ERR_INVOICE_PERIOD_NOT_CLOSED")
    invoice["status"] = "ISSUED"
    invoice["issued_at"] = now()
    touch(invoice)
    for charge in _lend_lines(invoice["partner_id"], start, end):
        charge["status"] = "INVOICED"
        touch(charge)
    derive.recompute_partner_by_id(invoice["partner_id"])
    return ok_row(invoice)


@bp.route("/ill/invoices/<invoice_id>/settle", methods=["POST"])
def settle_invoice(invoice_id):
    user_id, role = auth(ACCOUNTANT, PARTNER_AGENT)
    invoice = get_invoice(invoice_id)
    own_invoice(invoice, user_id, role)
    data = body()
    action = req_enum(data, "action", SETTLE_ACTIONS)
    dispute_reason = opt_str(data, "dispute_reason")
    # paying an invoice is the accountant's alone; the partner's agent may only
    # dispute or reinstate
    if role == PARTNER_AGENT and action == "PAY":
        raise ApiError("ERR_UNAUTHORIZED")
    if action == "DISPUTE" and not dispute_reason:
        bad("Field 'dispute_reason' is required to dispute an invoice.")
    # rung 46
    required = "DISPUTED" if action == "REINSTATE" else "ISSUED"
    if invoice["status"] != required:
        raise ApiError("ERR_INVOICE_INVALID_STATE")
    if action == "PAY":
        invoice["status"] = "PAID"
        invoice["settled_at"] = now()
    elif action == "DISPUTE":
        invoice["status"] = "DISPUTED"
        invoice["dispute_reason"] = dispute_reason
    else:
        # issued_at deliberately survives the round trip
        invoice["status"] = "ISSUED"
        invoice["dispute_reason"] = None
    touch(invoice)
    return ok_row(invoice)


@bp.route("/ill/invoices/<invoice_id>", methods=["GET"])
def get_one_invoice(invoice_id):
    user_id, role = auth(PARTNER_AGENT, ACCOUNTANT, ADMIN)
    invoice = get_invoice(invoice_id)
    own_invoice(invoice, user_id, role)
    return ok_row(invoice)


@bp.route("/ill/partners/<partner_id>/invoices", methods=["GET"])
def list_partner_invoices(partner_id):
    user_id, role = auth(PARTNER_AGENT, ACCOUNTANT, ADMIN)
    own_partner_id(partner_id, user_id, role)
    get_partner(partner_id)
    rows = [i for i in db.invoices.values() if i["partner_id"] == partner_id]
    rows = filter_eq(rows, "period_month", q_str("period_month"))
    rows = filter_eq(rows, "status", q_enum("status", INVOICE_STATUSES))
    return list_response(rows)


@bp.route("/ill/copyright-usage", methods=["GET"])
def copyright_usage_report():
    auth(ILL_STAFF, ADMIN)
    issn = q_str("issn")
    if not issn:
        bad("Query parameter 'issn' is required.")
    calendar_year = q_int("calendar_year")
    if calendar_year is None:
        bad("Query parameter 'calendar_year' is required.")
    return ok(calc.copyright_usage(issn, calendar_year))


@bp.route("/ill/ops-runs", methods=["POST"])
def run_ops():
    auth(ILL_STAFF, ADMIN)
    return ok(sweep.run_sweep())


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(ADMIN, ILL_STAFF)
    data = body()
    target = req_instant(data, "to_iso8601")
    # the logical clock only ever moves forward
    if target < db.clock:
        bad("Field 'to_iso8601' must not be earlier than the current logical clock.")
    db.clock = target
    return ok({"current_utc": iso_ms(db.clock)})
