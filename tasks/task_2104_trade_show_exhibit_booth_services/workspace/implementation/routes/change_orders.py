"""On-site change orders: review under segregation of duties, then application."""
from flask import Blueprint, g

import db
import guards
import response
from errors import ApiError
from middleware import ANY_ROLE, own_exhibitor, require_roles, segregation
from routes.service_orders import lines_of_order, reprice
from services import calc, state
from validation import json_body, parse_dt, require_row

bp = Blueprint("change_orders", __name__)
store = db.store

TARGET_TYPES = ("SERVICE_ORDER", "LABOR_CALL", "EXHIBIT_DESIGN")
DELTA_KINDS = ("QTY_INCREASE", "QTY_DECREASE", "CREW_INCREASE", "SCOPE_UPGRADE")
TERMINAL = ("REJECTED", "APPLIED")


def _resolve_target(target_type, target_id):
    if target_type == "SERVICE_ORDER":
        return store.service_orders.get(target_id)
    if target_type == "LABOR_CALL":
        return store.labor_calls.get(target_id)
    if target_type == "EXHIBIT_DESIGN":
        return store.designs.get(target_id)
    return None


def _check_target(booth_id, target_type, target_id):
    target = _resolve_target(target_type, target_id)
    if target is None or target.get("booth_id") != booth_id:
        raise ApiError("ERR_CHANGE_TARGET_MISMATCH",
                       "The change target does not exist on this booth")
    return target


def _booth_exhibitor(change_order):
    if not change_order:
        return None
    booth = store.booths.get(change_order["booth_id"])
    return booth["exhibitor_id"] if booth else None


@bp.post("/change-orders")
def create_change_order():
    uid, _role = require_roles("Exhibitor", "ShowOperations")
    body = json_body()
    peeked = store.booths.get(body.peek_str("booth_id"))
    own_exhibitor(peeked["exhibitor_id"] if peeked else None)

    booth_id = body.string("booth_id")
    target_type = body.enum("target_type", TARGET_TYPES)
    target_id = body.string("target_id")
    delta_kind = body.enum("delta_kind", DELTA_KINDS)
    reason = body.string("reason")
    delta_qty = body.integer("delta_qty", required=False, default=None)

    booth = require_row(store.booths, booth_id, "ERR_BOOTH_NOT_FOUND", "Booth")
    guards.booth_not_frozen(booth)
    _check_target(booth_id, target_type, target_id)

    change_order = {
        "id": db.new_id(),
        "booth_id": booth_id,
        "target_type": target_type,
        "target_id": target_id,
        "delta_kind": delta_kind,
        "delta_qty": delta_qty,
        "reason": reason,
        "created_by_user_id": uid,
        "reviewed_by_user_id": None,
        "price_delta_cents": None,
        "status": "DRAFT",
    }
    db.stamp_common(change_order)
    store.change_orders[change_order["id"]] = change_order
    return response.created(change_order)


@bp.get("/change-orders/<change_order_id>")
def get_change_order(change_order_id):
    require_roles(ANY_ROLE)
    change_order = store.change_orders.get(change_order_id)
    own_exhibitor(_booth_exhibitor(change_order))
    change_order = require_row(store.change_orders, change_order_id,
                               "ERR_CHANGE_ORDER_NOT_FOUND", "Change order")
    return response.ok(change_order)


@bp.get("/change-orders")
def list_change_orders():
    require_roles(ANY_ROLE)
    rows = list(store.change_orders.values())
    rows = response.filter_rows(rows, "booth_id", "status", "target_type")
    return response.listing(rows)


@bp.post("/change-orders/<change_order_id>/submit")
def submit(change_order_id):
    require_roles("Exhibitor", "ShowOperations")
    json_body()
    change_order = store.change_orders.get(change_order_id)
    own_exhibitor(_booth_exhibitor(change_order))
    change_order = require_row(store.change_orders, change_order_id,
                               "ERR_CHANGE_ORDER_NOT_FOUND", "Change order")
    booth = store.booths.get(change_order["booth_id"])

    guards.transition(change_order["status"], TERMINAL, ("DRAFT", "RETURNED"))
    if booth is not None:
        guards.booth_not_frozen(booth)

    change_order["status"] = "SUBMITTED"
    db.touch(change_order)
    return response.ok(change_order)


@bp.post("/change-orders/<change_order_id>/review")
def review(change_order_id):
    require_roles("ShowOperations")
    body = json_body()
    change_order = store.change_orders.get(change_order_id)
    raw_decision = body.peek_str("decision")
    if change_order is not None and raw_decision in ("APPROVE", "REJECT"):
        segregation(change_order["created_by_user_id"])

    decision = body.enum("decision", ("START_REVIEW", "APPROVE", "RETURN", "REJECT"))
    body.string("note", required=False, default=None)
    change_order = require_row(store.change_orders, change_order_id,
                               "ERR_CHANGE_ORDER_NOT_FOUND", "Change order")
    booth = store.booths.get(change_order["booth_id"])

    if decision == "START_REVIEW":
        guards.transition(change_order["status"], TERMINAL, ("SUBMITTED",))
        change_order["status"] = "UNDER_REVIEW"
    elif decision == "APPROVE":
        guards.transition(change_order["status"], TERMINAL, ("UNDER_REVIEW",))
        change_order["reviewed_by_user_id"] = g.user_id
        change_order["status"] = "APPROVED"
    elif decision == "RETURN":
        guards.transition(change_order["status"], TERMINAL, ("UNDER_REVIEW",))
        change_order["status"] = "RETURNED"
    else:  # REJECT
        guards.transition(change_order["status"], TERMINAL, ("UNDER_REVIEW",))
        change_order["reviewed_by_user_id"] = g.user_id
        change_order["status"] = "REJECTED"

    db.touch(change_order)
    if decision in ("APPROVE", "REJECT") and booth is not None:
        state.refresh_booth(booth)
    return response.ok(change_order)


@bp.post("/change-orders/<change_order_id>/apply")
def apply(change_order_id):
    require_roles("ShowOperations")
    body = json_body()
    expected_version = body.integer("expected_service_order_version")
    change_order = require_row(store.change_orders, change_order_id,
                               "ERR_CHANGE_ORDER_NOT_FOUND", "Change order")
    booth = store.booths.get(change_order["booth_id"])

    guards.transition(change_order["status"], TERMINAL, ("APPROVED",))

    target = _resolve_target(change_order["target_type"], change_order["target_id"])
    if change_order["target_type"] == "SERVICE_ORDER" and target is not None:
        if target["fulfillment_status"] in ("DELIVERED", "CANCELLED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The target order is no longer eligible for a change")
        guards.occ(expected_version, target["version"],
                   "ERR_STALE_SERVICE_ORDER_VERSION")

    if booth is not None:
        guards.booth_not_frozen(booth)

    target = _check_target(change_order["booth_id"], change_order["target_type"],
                           change_order["target_id"])

    delta_qty = change_order.get("delta_qty") or 0
    price_delta = 0

    if change_order["target_type"] == "SERVICE_ORDER":
        before_total = int(target["total_cents"])
        lines = lines_of_order(target["id"])
        if lines and change_order["delta_kind"] in ("QTY_INCREASE", "QTY_DECREASE"):
            first = lines[0]
            if change_order["delta_kind"] == "QTY_INCREASE":
                first["unit_qty"] = int(first["unit_qty"]) + int(delta_qty)
            else:
                first["unit_qty"] = max(0, int(first["unit_qty"]) - int(delta_qty))
        show = store.shows.get(booth["show_id"]) if booth else None
        tier, multiplier = calc.deadline_tier(
            db.now_dt(),
            (parse_dt(show["discount_deadline"]), parse_dt(show["move_in_start"])))
        reprice(target, tier, multiplier)
        price_delta = int(target["total_cents"]) - before_total
        db.touch(target)
    elif change_order["target_type"] == "LABOR_CALL":
        if change_order["delta_kind"] == "CREW_INCREASE" and delta_qty:
            target["crew_size"] = int(target["crew_size"]) + int(delta_qty)
            db.touch(target)
            show = store.shows.get(booth["show_id"]) if booth else None
            if show is not None:
                state.recompute_show_aggregates(show)

    change_order["price_delta_cents"] = price_delta
    change_order["status"] = "APPLIED"
    db.touch(change_order)

    if change_order["target_type"] == "SERVICE_ORDER":
        _billing_cascade(target, price_delta)

    if booth is not None:
        state.refresh_booth(booth)
    return response.ok(change_order)


def _billing_cascade(order, price_delta):
    """An already invoiced order re-bills: invoice total, balance, then postures."""
    if order["billing_status"] != "INVOICED":
        return
    order["billing_status"] = "REBILL_PENDING"
    db.touch(order)
    invoice = store.invoices.get(order.get("invoice_id"))
    if invoice is None:
        return
    invoice["adjustments_cents"] = int(invoice["adjustments_cents"]) + int(price_delta)
    invoice["total_cents"] = int(invoice["subtotal_cents"]) + int(invoice["adjustments_cents"])
    db.touch(invoice)
    exhibitor = store.exhibitors.get(invoice["exhibitor_id"])
    if exhibitor is not None:
        state.recompute_balance(exhibitor)
        state.refresh_exhibitor_booths(exhibitor["id"])
