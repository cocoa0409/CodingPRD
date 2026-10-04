"""Fuel invoice and line item endpoints (PRD section 3.6)."""

from datetime import time, timezone, datetime

from flask import Blueprint, request

import calc
import db
import envelope
import helpers
import validators as v
from authz import require_roles
from errors import (
    ApiError, ERR_CONTRACT_NOT_ACTIVE, ERR_EVENT_NOT_BILLABLE,
    ERR_INVALID_DATE_RANGE, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_STALE_VERSION,
)

bp = Blueprint("invoices", __name__)

READ_ROLES = ("BillingOperator", "SiteManager")
INVOICE_STATUSES = ("DRAFT", "ISSUED", "PAID", "DISPUTED", "VOID")


def _invoice(iid):
    return helpers.get_or_404(db.invoices, iid, "invoice")


def _site_open_for(inv):
    site = helpers.get_site(inv["site_id"])
    helpers.ensure_site_open(site)


@bp.post("/api/invoices")
@require_roles("BillingOperator")
def create_invoice():
    data = v.body()
    site_id = v.str_value(v.req(data, "site_id"), "site_id")
    contract_id = v.str_value(v.req(data, "supply_contract_id"),
                              "supply_contract_id")
    ps = v.date_value(v.req(data, "period_start"), "period_start")
    pe = v.date_value(v.req(data, "period_end"), "period_end")
    site = helpers.get_site(site_id)
    helpers.get_or_404(db.contracts, contract_id, "supply contract")
    helpers.ensure_site_open(site)
    if v.parse_date(pe) <= v.parse_date(ps):
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "period_end must be after period_start")
    inv = helpers.create_rec(db.invoices, {
        "site_id": site_id,
        "supply_contract_id": contract_id,
        "period_start": ps,
        "period_end": pe,
        "total_kg": 0,
        "subtotal_cents": 0,
        "credit_cents": 0,
        "total_cents": 0,
        "status": "DRAFT",
    })
    return envelope.ok(inv, 201)


@bp.get("/api/invoices")
@require_roles(*READ_ROLES)
def list_invoices():
    items = list(db.invoices.values())
    site_id = request.args.get("site_id")
    if site_id is not None:
        items = [i for i in items if i["site_id"] == site_id]
    status = request.args.get("status")
    if status is not None:
        if status not in INVOICE_STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid status filter")
        items = [i for i in items if i["status"] == status]
    for inv in items:
        if inv["status"] == "DRAFT":
            calc.recompute_draft_totals(inv)
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.get("/api/invoices/<iid>")
@require_roles(*READ_ROLES)
def get_invoice(iid):
    inv = _invoice(iid)
    if inv["status"] == "DRAFT":
        calc.recompute_draft_totals(inv)
    return envelope.ok(inv, 200)


@bp.get("/api/sites/<site_id>/invoices")
@require_roles(*READ_ROLES)
def list_site_invoices(site_id):
    helpers.get_site(site_id)
    items = [i for i in db.invoices.values() if i["site_id"] == site_id]
    status = request.args.get("status")
    if status is not None:
        if status not in INVOICE_STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid status filter")
        items = [i for i in items if i["status"] == status]
    for inv in items:
        if inv["status"] == "DRAFT":
            calc.recompute_draft_totals(inv)
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.post("/api/invoices/<iid>/line-items")
@require_roles("BillingOperator")
def add_line_item(iid):
    inv = _invoice(iid)
    if inv["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "line items can only be added to a DRAFT invoice")
    _site_open_for(inv)
    data = v.body()
    fid = v.str_value(v.req(data, "fueling_event_id"), "fueling_event_id")
    expected = v.int_value(v.req(data, "expected_invoice_version"),
                           "expected_invoice_version")
    ev = db.fueling_events.get(fid)
    if ev is None:
        raise ApiError(ERR_EVENT_NOT_BILLABLE, 422,
                       "fueling event does not exist")
    ps_dt = datetime.combine(v.parse_date(inv["period_start"]), time.min,
                             tzinfo=timezone.utc)
    pe_dt = datetime.combine(v.parse_date(inv["period_end"]), time.min,
                             tzinfo=timezone.utc)
    odt = v.parse_datetime(ev["occurred_at"])
    if not (ps_dt <= odt < pe_dt):
        raise ApiError(ERR_EVENT_NOT_BILLABLE, 422,
                       "fueling event falls outside the invoice period")
    if ev["supply_contract_id"] != inv["supply_contract_id"]:
        raise ApiError(ERR_EVENT_NOT_BILLABLE, 422,
                       "fueling event is billed under a different contract")
    for li in db.line_items.values():
        if li["fueling_event_id"] == fid:
            other = db.invoices.get(li["invoice_id"])
            if other is not None and other["status"] != "VOID":
                raise ApiError(ERR_EVENT_NOT_BILLABLE, 422,
                               "fueling event is already billed on a "
                               "non-VOID invoice")
    if expected != inv["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_invoice_version does not match the "
                       "invoice version")
    contract = db.contracts[inv["supply_contract_id"]]
    unit_price, amount = calc.price_line(inv, contract, ev["kg_dispensed"])
    line = helpers.create_rec(db.line_items, {
        "invoice_id": iid,
        "fueling_event_id": fid,
        "kg": ev["kg_dispensed"],
        "unit_price_per_kg": unit_price,
        "line_amount_cents": amount,
    })
    calc.recompute_draft_totals(inv)
    helpers.touch(inv)
    return envelope.ok(line, 201)


@bp.get("/api/invoices/<iid>/line-items")
@require_roles(*READ_ROLES)
def list_line_items(iid):
    _invoice(iid)
    items = [li for li in db.line_items.values() if li["invoice_id"] == iid]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.post("/api/invoices/<iid>/issue")
@require_roles("BillingOperator")
def issue_invoice(iid):
    inv = _invoice(iid)
    if inv["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "invoice must be DRAFT to issue")
    _site_open_for(inv)
    if not calc.invoice_lines(iid):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "invoice must carry at least one line item to issue")
    contract = db.contracts.get(inv["supply_contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, 422,
                       "invoice supply contract is not ACTIVE")
    calc.finalize_invoice_totals(inv)
    inv["status"] = "ISSUED"
    helpers.touch(inv)
    return envelope.ok(inv, 200)


@bp.post("/api/invoices/<iid>/void")
@require_roles("BillingOperator")
def void_invoice(iid):
    inv = _invoice(iid)
    if inv["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "invoice must be DRAFT to void")
    _site_open_for(inv)
    inv["status"] = "VOID"
    helpers.touch(inv)
    return envelope.ok(inv, 200)


@bp.post("/api/invoices/<iid>/pay")
@require_roles("BillingOperator")
def pay_invoice(iid):
    inv = _invoice(iid)
    if inv["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "invoice must be ISSUED to pay")
    _site_open_for(inv)
    inv["status"] = "PAID"
    helpers.touch(inv)
    return envelope.ok(inv, 200)


@bp.post("/api/invoices/<iid>/dispute")
@require_roles("SiteManager")
def dispute_invoice(iid):
    inv = _invoice(iid)
    if inv["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "invoice must be ISSUED to dispute")
    _site_open_for(inv)
    inv["status"] = "DISPUTED"
    helpers.touch(inv)
    return envelope.ok(inv, 200)


@bp.post("/api/invoices/<iid>/resolve")
@require_roles("BillingOperator")
def resolve_invoice(iid):
    inv = _invoice(iid)
    if inv["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "invoice must be DISPUTED to resolve")
    _site_open_for(inv)
    inv["status"] = "ISSUED"
    helpers.touch(inv)
    return envelope.ok(inv, 200)
