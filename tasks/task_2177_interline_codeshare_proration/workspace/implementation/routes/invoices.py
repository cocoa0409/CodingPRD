"""Clearing-house billing invoices (PRD section 3.6)."""

from flask import Blueprint

import calculations as C
from calculations import (LIVE_INVOICE_STATUSES, build_claim,
                          coupons_of_invoice, recompute_net_position,
                          round_half_up, select_rate_scaled)
from errors import ApiError
from responses import ok, ok_list
from store import db, fmt_dt, must_find, new_row, ordered, serialize, touch
import validation as V

bp = Blueprint("invoices", __name__)


@bp.route("/interline/billing-invoices", methods=["POST"])
def create_invoice():
    user_id, role = V.require([V.ROLE_ACCOUNTANT])
    data = V.body()
    period_id = V.req_str(data, "settlement_period_id")
    billing_carrier_id = V.req_str(data, "billing_carrier_id")
    billed_carrier_id = V.req_str(data, "billed_carrier_id")
    billing_currency = V.req_enum(data, "billing_currency", V.CURRENCIES)
    coupon_ids = V.req_id_list(data, "coupon_ids")

    period = must_find("period", period_id)
    billing_carrier = must_find("carrier", billing_carrier_id)
    billed_carrier = must_find("carrier", billed_carrier_id)
    coupons = [must_find("coupon", cid) for cid in coupon_ids]

    V.require_ownership(user_id, role, billing_carrier["id"])

    if period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN")

    for coupon in coupons:
        ticket = db.tickets.get(coupon["ticket_id"])
        if ticket is None or ticket["proration_status"] != "FINAL":
            raise ApiError("ERR_TICKET_NOT_FINAL_PRORATED")

    if billing_carrier["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_SUSPENDED")

    for coupon in coupons:
        ticket = db.tickets.get(coupon["ticket_id"])
        if coupon["operating_carrier_id"] != billing_carrier["id"]:
            raise ApiError("ERR_COUPON_CARRIER_MISMATCH")
        if ticket["validating_carrier_id"] != billed_carrier["id"]:
            raise ApiError("ERR_COUPON_CARRIER_MISMATCH")

    for coupon in coupons:
        ticket = db.tickets.get(coupon["ticket_id"])
        if ticket["sale_currency"] != billing_currency:
            raise ApiError("ERR_CURRENCY_MISMATCH")

    for coupon in coupons:
        if coupon.get("billing_invoice_id"):
            raise ApiError("ERR_COUPON_ALREADY_INVOICED")
        if coupon["coupon_status"] not in ("FLOWN", "ADJUSTED"):
            raise ApiError("ERR_COUPON_ALREADY_INVOICED")

    invoice = new_row({
        "settlement_period_id": period["id"],
        "billing_carrier_id": billing_carrier["id"],
        "billed_carrier_id": billed_carrier["id"],
        "billing_currency": billing_currency,
        "status": "DRAFT",
        "coupon_count": 0,
        "gross_billed_minor": 0,
        "ich_fee_bp": 0,
        "ich_handling_fee_minor": 0,
        "late_submission_penalty_minor": 0,
        "total_claim_minor": 0,
        "provisional_rate_scaled": 0,
        "provisional_settlement_minor": 0,
        "fixed_rate_scaled": 0,
        "final_settlement_minor": 0,
        "fx_variance_minor": 0,
        "disputed_amount_minor": 0,
        "rejected_amount_minor": 0,
        "net_billed_minor": 0,
        "submitted_at": None,
        "cleared_at": None,
    })
    db.invoices[invoice["id"]] = invoice

    attached = 0
    for coupon in coupons:
        if coupon.get("billing_invoice_id") == invoice["id"]:
            continue
        coupon["billing_invoice_id"] = invoice["id"]
        attached += 1
    invoice["coupon_count"] = attached
    return ok(serialize(invoice), 201)


@bp.route("/interline/billing-invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    V.require(V.ALL_ROLES)
    invoice = must_find("invoice", invoice_id)
    return ok(serialize(invoice))


@bp.route("/interline/billing-invoices", methods=["GET"])
def list_invoices():
    V.require(V.ALL_ROLES)
    limit, offset = V.pagination()
    period_id = V.filter_str("settlement_period_id")
    billing_carrier_id = V.filter_str("billing_carrier_id")
    billed_carrier_id = V.filter_str("billed_carrier_id")
    status = V.filter_enum("status", V.INVOICE_STATUSES)
    rows = list(db.invoices.values())
    if period_id is not None:
        rows = [r for r in rows if r["settlement_period_id"] == period_id]
    if billing_carrier_id is not None:
        rows = [r for r in rows if r["billing_carrier_id"] == billing_carrier_id]
    if billed_carrier_id is not None:
        rows = [r for r in rows if r["billed_carrier_id"] == billed_carrier_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, total = V.listing(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/interline/billing-invoices/<invoice_id>/submit", methods=["POST"])
def submit_invoice(invoice_id):
    user_id, role = V.require([V.ROLE_BILLING])
    V.body()
    invoice = must_find("invoice", invoice_id)

    V.require_ownership(user_id, role, invoice["billing_carrier_id"])

    period = db.periods.get(invoice["settlement_period_id"])
    if period is None or period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN")

    if invoice["status"] != "DRAFT":
        raise ApiError("ERR_INVOICE_STATE_INVALID")

    billing_carrier = db.carriers.get(invoice["billing_carrier_id"])
    billed_carrier = db.carriers.get(invoice["billed_carrier_id"])
    if billing_carrier is None or billing_carrier["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_SUSPENDED")

    late = db.clock > period["_submission_deadline"]
    claim = build_claim(invoice, late)

    rate = select_rate_scaled(invoice["billing_currency"],
                              period["settlement_currency"], db.clock)
    if rate is None:
        raise ApiError("ERR_NO_EXCHANGE_RATE")
    provisional = round_half_up(claim["total_claim_minor"] * rate, C.RATE_SCALE)

    exposure = (billed_carrier["pending_payable_minor"]
                + billed_carrier["settled_payable_minor"]
                + provisional
                - billed_carrier["pending_receivable_minor"]
                - billed_carrier["settled_receivable_minor"])
    if exposure > billed_carrier["credit_limit_minor"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED")

    invoice.update(claim)
    invoice["provisional_rate_scaled"] = rate
    invoice["provisional_settlement_minor"] = provisional
    invoice["status"] = "SUBMITTED"
    invoice["submitted_at"] = fmt_dt(db.clock)
    invoice["_submitted_at"] = db.clock

    billing_carrier["pending_receivable_minor"] += provisional
    recompute_net_position(billing_carrier)
    touch(billing_carrier)
    billed_carrier["pending_payable_minor"] += provisional
    recompute_net_position(billed_carrier)
    touch(billed_carrier)

    ticket_ids = []
    for coupon in coupons_of_invoice(invoice["id"]):
        if coupon["ticket_id"] not in ticket_ids:
            ticket_ids.append(coupon["ticket_id"])
    for ticket in ordered([db.tickets[t] for t in ticket_ids
                           if t in db.tickets]):
        if ticket["billing_status"] == "UNBILLED":
            ticket["billing_status"] = "BILLED"
            touch(ticket)

    touch(invoice)
    return ok(serialize(invoice))


@bp.route("/interline/billing-invoices/<invoice_id>/recall", methods=["POST"])
def recall_invoice(invoice_id):
    user_id, role = V.require([V.ROLE_BILLING])
    V.body()
    invoice = must_find("invoice", invoice_id)

    V.require_ownership(user_id, role, invoice["billing_carrier_id"])

    period = db.periods.get(invoice["settlement_period_id"])
    if period is None or period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN")

    if invoice["status"] != "SUBMITTED":
        raise ApiError("ERR_INVOICE_STATE_INVALID")

    provisional = invoice["provisional_settlement_minor"]
    billing_carrier = db.carriers.get(invoice["billing_carrier_id"])
    billed_carrier = db.carriers.get(invoice["billed_carrier_id"])
    if billing_carrier is not None:
        billing_carrier["pending_receivable_minor"] -= provisional
        recompute_net_position(billing_carrier)
        touch(billing_carrier)
    if billed_carrier is not None:
        billed_carrier["pending_payable_minor"] -= provisional
        recompute_net_position(billed_carrier)
        touch(billed_carrier)

    attached = coupons_of_invoice(invoice["id"])
    ticket_ids = []
    for coupon in attached:
        if coupon["ticket_id"] not in ticket_ids:
            ticket_ids.append(coupon["ticket_id"])
        coupon["billing_invoice_id"] = None

    invoice["gross_billed_minor"] = 0
    invoice["ich_fee_bp"] = 0
    invoice["ich_handling_fee_minor"] = 0
    invoice["late_submission_penalty_minor"] = 0
    invoice["total_claim_minor"] = 0
    invoice["net_billed_minor"] = 0
    invoice["provisional_rate_scaled"] = 0
    invoice["provisional_settlement_minor"] = 0
    invoice["submitted_at"] = None
    invoice["_submitted_at"] = None
    invoice["coupon_count"] = 0
    invoice["status"] = "DRAFT"

    for ticket in ordered([db.tickets[t] for t in ticket_ids
                           if t in db.tickets]):
        if ticket["billing_status"] != "BILLED":
            continue
        still_billed = False
        for coupon in db.coupons.values():
            if coupon["ticket_id"] != ticket["id"]:
                continue
            other_id = coupon.get("billing_invoice_id")
            if not other_id:
                continue
            other = db.invoices.get(other_id)
            if other is not None and other["status"] in LIVE_INVOICE_STATUSES:
                still_billed = True
                break
        if not still_billed:
            ticket["billing_status"] = "UNBILLED"
            touch(ticket)

    touch(invoice)
    return ok(serialize(invoice))
