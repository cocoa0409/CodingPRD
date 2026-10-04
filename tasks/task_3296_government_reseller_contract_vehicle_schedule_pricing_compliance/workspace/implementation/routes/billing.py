"""Invoice + Dispute surface."""
from datetime import timedelta

from flask import request

import db
from server_core import app
from errors import err, not_found, invalid_state, fk_not_found, ERR_UNIQUENESS_VIOLATION
from util import (
    envelope, respond_list, body_arg, new_entity, bump, now_logical, fmt_iso,
    require_period_label,
)
from rules import (
    lazy_invoice_overdue, refresh_sales_reports_for_order,
    recompute_sales_report, recompute_posture,
)


def invoice_view(i):
    return {k: i[k] for k in ("id", "order_id", "period_label", "amount_cents",
                              "payment_terms_days", "issued_at", "due_at", "status",
                              "created_at", "updated_at", "version")}


def dispute_view(d):
    return {k: d[k] for k in ("id", "order_id", "kind", "amount_cents", "status",
                              "created_at", "updated_at", "version")}


def agreement_of_order(order):
    return db.agreements[db.vehicles[order["vehicle_id"]]["agreement_id"]]


@app.post("/invoices")
def invoices_create():
    order_id = body_arg("order_id")
    order = db.orders.get(order_id)
    if order is None:
        raise fk_not_found("order_id not found")
    period_label = require_period_label(body_arg("period_label"))
    if order["billing_status"] != "DELIVERED" or order["compliance_status"] != "CLEARED":
        raise invalid_state("order must be CLEARED and DELIVERED to invoice")
    for inv in db.invoices.values():
        if inv["order_id"] == order_id and inv["status"] != "VOID":
            raise err(ERR_UNIQUENESS_VIOLATION, "a non-VOID invoice already exists for this order", 409)
    terms = body_arg("payment_terms_days")
    if terms not in (15, 30, 45, 60):
        raise err("ERR_ORDER_LINE_INVALID", "payment_terms_days must be one of 15, 30, 45, 60", 422)
    issued_dt = now_logical(db)
    due_dt = issued_dt + timedelta(days=terms)
    amount = int(order["order_total_cents"]) + int(order["teaming_surcharge_cents"])
    inv = new_entity(db, db.invoices, {},
                     order_id=order_id, period_label=period_label,
                     amount_cents=amount, payment_terms_days=terms,
                     issued_at=fmt_iso(issued_dt), due_at=fmt_iso(due_dt),
                     status="ISSUED")
    inv["_due"] = due_dt
    order["billing_status"] = "INVOICED"
    bump(order)
    refresh_sales_reports_for_order(db, order, period_label)
    return envelope(invoice_view(inv), 201)


@app.get("/invoices")
def invoices_list():
    items = list(db.invoices.values())
    for inv in items:
        lazy_invoice_overdue(db, inv)
    period = request.args.get("period_label")
    if period is not None:
        items = [i for i in items if i["period_label"] == period]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return respond_list([invoice_view(i) for i in items])


@app.get("/invoices/<iid>")
def invoices_get(iid):
    inv = db.invoices.get(iid)
    if inv is None:
        raise not_found("invoice not found")
    lazy_invoice_overdue(db, inv)
    return envelope(invoice_view(inv), 200)


@app.post("/invoices/<iid>/pay")
def invoices_pay(iid):
    inv = db.invoices.get(iid)
    if inv is None:
        raise not_found("invoice not found")
    lazy_invoice_overdue(db, inv)
    if inv["status"] not in ("ISSUED", "OVERDUE"):
        raise invalid_state("invoice is not ISSUED or OVERDUE")
    inv["status"] = "PAID"
    bump(inv)
    order = db.orders[inv["order_id"]]
    order["billing_status"] = "PAID"
    bump(order)
    return envelope(invoice_view(inv), 200)


@app.post("/invoices/<iid>/void")
def invoices_void(iid):
    inv = db.invoices.get(iid)
    if inv is None:
        raise not_found("invoice not found")
    lazy_invoice_overdue(db, inv)
    if inv["status"] != "ISSUED":
        raise invalid_state("only ISSUED invoices may be voided")
    inv["status"] = "VOID"
    bump(inv)
    order = db.orders[inv["order_id"]]
    order["billing_status"] = "DELIVERED"
    bump(order)
    vehicle = db.vehicles[order["vehicle_id"]]
    report = next((r for r in db.sales_reports.values()
                   if r["agreement_id"] == vehicle["agreement_id"]
                   and r["period_label"] == inv["period_label"]), None)
    if report is not None:
        recompute_sales_report(db, report)
    return envelope(invoice_view(inv), 200)


@app.post("/disputes")
def disputes_create():
    order_id = body_arg("order_id")
    order = db.orders.get(order_id)
    if order is None:
        raise fk_not_found("order_id not found")
    amount = body_arg("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount == 0:
        raise err("ERR_ORDER_LINE_INVALID", "amount_cents must be a non-zero integer", 422)
    d = new_entity(db, db.disputes, {},
                   order_id=order_id, kind=body_arg("kind"),
                   amount_cents=amount, status="OPEN")
    agreement = agreement_of_order(order)
    agreement["dispute_credit_cents"] += amount
    recompute_posture(agreement)
    bump(agreement)
    return envelope(dispute_view(d), 201)


@app.get("/disputes")
def disputes_list():
    items = list(db.disputes.values())
    oid = request.args.get("order_id")
    if oid is not None:
        items = [d for d in items if d["order_id"] == oid]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return respond_list([dispute_view(d) for d in items])


@app.get("/disputes/<did>")
def disputes_get(did):
    d = db.disputes.get(did)
    if d is None:
        raise not_found("dispute not found")
    return envelope(dispute_view(d), 200)


@app.post("/disputes/<did>/resolve")
def disputes_resolve(did):
    d = db.disputes.get(did)
    if d is None:
        raise not_found("dispute not found")
    if d["status"] != "OPEN":
        raise invalid_state("dispute is not OPEN")
    outcome = body_arg("outcome")
    if outcome not in ("CREDIT", "DEBIT", "REJECT"):
        raise err("ERR_ORDER_LINE_INVALID", "outcome must be CREDIT, DEBIT, or REJECT", 422)
    if outcome == "CREDIT":
        d["status"] = "RESOLVED_CREDIT"
    elif outcome == "DEBIT":
        d["status"] = "RESOLVED_DEBIT"
    else:
        d["status"] = "REJECTED"
    agreement = agreement_of_order(db.orders[d["order_id"]])
    if outcome == "REJECT":
        agreement["dispute_credit_cents"] -= d["amount_cents"]
    recompute_posture(agreement)
    bump(agreement)
    bump(d)
    return envelope(dispute_view(d), 200)
