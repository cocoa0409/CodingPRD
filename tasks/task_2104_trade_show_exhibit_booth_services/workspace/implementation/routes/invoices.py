"""Invoices: sweeping orders, issuing, payments and voiding (PRD §3.9)."""
from flask import Blueprint, g

import db
import guards
import response
from errors import ApiError
from middleware import ANY_ROLE, own_exhibitor, require_roles, segregation
from services import state
from validation import json_body, require_row

bp = Blueprint("invoices", __name__)
store = db.store

TERMINAL = ("SETTLED", "VOID")


def _orders_of(invoice):
    return [store.service_orders[oid] for oid in invoice["service_order_ids"]
            if oid in store.service_orders]


@bp.post("/invoices")
def create_invoice():
    require_roles("FinanceController")
    body = json_body()
    exhibitor_id = body.string("exhibitor_id")
    show_id = body.string("show_id")
    order_ids = body.id_array("service_order_ids")

    require_row(store.exhibitors, exhibitor_id, "ERR_EXHIBITOR_NOT_FOUND", "Exhibitor")
    require_row(store.shows, show_id, "ERR_SHOW_NOT_FOUND", "Show")
    orders = [require_row(store.service_orders, order_id, "ERR_SERVICE_ORDER_NOT_FOUND",
                          "Service order") for order_id in order_ids]

    for order in orders:
        booth = store.booths.get(order["booth_id"])
        if booth is None or booth["exhibitor_id"] != exhibitor_id or \
                booth["show_id"] != show_id:
            raise ApiError("ERR_INVOICE_SCOPE_MISMATCH",
                           "A swept order belongs to a different exhibitor or show")

    guards.not_empty(order_ids, "service_order_ids")

    subtotal = sum(int(order["total_cents"]) for order in orders)
    invoice = {
        "id": db.new_id(),
        "exhibitor_id": exhibitor_id,
        "show_id": show_id,
        "service_order_ids": list(order_ids),
        "subtotal_cents": subtotal,
        "adjustments_cents": 0,
        "total_cents": subtotal,
        "settled_cents": 0,
        "issued_by_user_id": None,
        "voided_by_user_id": None,
        "status": "DRAFT",
    }
    db.stamp_common(invoice)
    store.invoices[invoice["id"]] = invoice
    return response.created(invoice)


@bp.get("/invoices/<invoice_id>")
def get_invoice(invoice_id):
    require_roles(ANY_ROLE)
    invoice = store.invoices.get(invoice_id)
    own_exhibitor(invoice["exhibitor_id"] if invoice else None)
    invoice = require_row(store.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND", "Invoice")
    return response.ok(invoice)


@bp.get("/invoices")
def list_invoices():
    require_roles(ANY_ROLE)
    rows = list(store.invoices.values())
    rows = response.filter_rows(rows, "exhibitor_id", "show_id", "status")
    return response.listing(rows)


@bp.post("/invoices/<invoice_id>/issue")
def issue(invoice_id):
    require_roles("FinanceController")
    json_body()
    invoice = require_row(store.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND", "Invoice")
    orders = _orders_of(invoice)
    exhibitor = store.exhibitors.get(invoice["exhibitor_id"])

    rebill = [o for o in orders if o["billing_status"] == "REBILL_PENDING"]
    if invoice["status"] in ("ISSUED", "PARTIALLY_SETTLED") and rebill:
        # Re-issue after a change-order adjustment: no money moves, because
        # total_cents already reflects the adjustment.
        for order in rebill:
            order["billing_status"] = "INVOICED"
            db.touch(order)
        db.touch(invoice)
        return response.ok(invoice)

    guards.transition(invoice["status"], TERMINAL, ("DRAFT",))

    for order in orders:
        if order["billing_status"] not in ("UNBILLED", "REBILL_PENDING"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "A swept order is already billed")

    if exhibitor is not None and exhibitor["status"] == "SUSPENDED":
        raise ApiError("ERR_EXHIBITOR_SUSPENDED",
                       "An invoice may not be issued against a suspended exhibitor")

    invoice["subtotal_cents"] = sum(int(order["total_cents"]) for order in orders)
    invoice["total_cents"] = int(invoice["subtotal_cents"]) + int(invoice["adjustments_cents"])
    invoice["issued_by_user_id"] = g.user_id
    invoice["status"] = "ISSUED"
    db.touch(invoice)

    for order in orders:
        order["billing_status"] = "INVOICED"
        order["invoice_id"] = invoice["id"]
        db.touch(order)

    if exhibitor is not None:
        state.recompute_balance(exhibitor)
        state.refresh_exhibitor_booths(exhibitor["id"])
    return response.ok(invoice)


@bp.post("/invoices/<invoice_id>/payments")
def payments(invoice_id):
    require_roles("FinanceController")
    body = json_body()
    amount = body.integer("amount_cents")
    invoice = require_row(store.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND", "Invoice")

    guards.transition(invoice["status"], TERMINAL, ("ISSUED", "PARTIALLY_SETTLED"))

    if amount <= 0 or int(invoice["settled_cents"]) + amount > int(invoice["total_cents"]):
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE",
                       "The payment must be positive and may not overshoot the invoice")

    invoice["settled_cents"] = int(invoice["settled_cents"]) + amount
    fully_settled = int(invoice["settled_cents"]) == int(invoice["total_cents"])
    invoice["status"] = "SETTLED" if fully_settled else "PARTIALLY_SETTLED"
    db.touch(invoice)

    if fully_settled:
        for order in _orders_of(invoice):
            order["billing_status"] = "SETTLED"
            db.touch(order)

    exhibitor = store.exhibitors.get(invoice["exhibitor_id"])
    if exhibitor is not None:
        state.recompute_balance(exhibitor)
        state.refresh_exhibitor_booths(exhibitor["id"])
    return response.ok(invoice)


@bp.post("/invoices/<invoice_id>/void")
def void(invoice_id):
    require_roles("FinanceController")
    body = json_body()
    invoice = store.invoices.get(invoice_id)
    if invoice is not None:
        segregation(invoice.get("issued_by_user_id"))
    body.string("reason")
    invoice = require_row(store.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND", "Invoice")

    guards.transition(invoice["status"], TERMINAL, ("DRAFT", "ISSUED"))
    if int(invoice["settled_cents"]) != 0:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an unsettled invoice may be voided")

    invoice["voided_by_user_id"] = g.user_id
    invoice["status"] = "VOID"
    db.touch(invoice)

    for order in _orders_of(invoice):
        order["billing_status"] = "CREDITED"
        order["invoice_id"] = None
        db.touch(order)

    exhibitor = store.exhibitors.get(invoice["exhibitor_id"])
    if exhibitor is not None:
        state.recompute_balance(exhibitor)
        state.refresh_exhibitor_booths(exhibitor["id"])
    return response.ok(invoice)
