"""Exchange requests: opening, quotation, approval and application."""

from flask import Blueprint

from db import DB
from errors import ApiError
from response import ok, ok_list, public, public_list, sorted_by_created
from routes import actor, pagination, payload
import guards_helpers
from services import calc, engine, holds

bp = Blueprint("exchanges", __name__)

EXCHANGE_TERMINAL = ("APPLIED", "REJECTED", "COMPENSATED")


def _context(purchase):
    allocation = DB.get("allocation", purchase["allocation_id"])
    performance = DB.get("performance", purchase["performance_id"])
    production = DB.get("production", performance["production_id"]) if performance else None
    return allocation, performance, production


@bp.post("/purchases/<purchase_id>/exchange-requests")
def open_exchange(purchase_id):
    """Open an exchange onto another allocation of the same performance."""
    user_id, role = actor(["Patron", "CustomerService"])
    body = payload()
    purchase = DB.get("purchase", purchase_id)
    if purchase is None:
        raise ApiError("ERR_PURCHASE_NOT_FOUND")

    guards_helpers.require_occ(body, "expected_purchase_version", purchase)

    if role == "Patron" and str(purchase["patron_id"]) != str(user_id):
        raise ApiError("ERR_FORBIDDEN")

    target = DB.get("allocation", body.get("target_allocation_id"))
    if target is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    allocation, performance, production = _context(purchase)
    if production is None or not bool(production.get("exchange_allowed")):
        raise ApiError("ERR_INVALID_STATE")
    if purchase["payment_status"] not in ("SETTLED", "PARTIALLY_REFUNDED"):
        raise ApiError("ERR_INVALID_STATE")
    if target["performance_id"] != purchase["performance_id"]:
        raise ApiError("ERR_INVALID_STATE")
    if target["id"] == purchase["allocation_id"]:
        raise ApiError("ERR_INVALID_STATE")

    exchange = {
        "purchase_id": purchase["id"],
        "patron_id": purchase["patron_id"],
        "original_amount_cents": body.get("original_amount_cents"),
        "target_allocation_id": target["id"],
        "source_allocation_id": purchase["allocation_id"],
        "status": "REQUESTED",
        "fee_cents": 0,
        "value_returned_cents": 0,
        "approved_by": None,
        "requested_by": user_id,
        "pre_application_refunded_cents": int(purchase.get("refunded_cents") or 0),
    }
    DB.insert("exchange", exchange)
    DB.touch("purchase", purchase)
    return ok(public(exchange), 201)


@bp.get("/purchases/<purchase_id>/exchange-requests")
def list_exchanges(purchase_id):
    actor(["CustomerService", "FinancialOps", "PlatformAdmin", "Patron"])
    purchase = DB.get("purchase", purchase_id)
    if purchase is None:
        raise ApiError("ERR_PURCHASE_NOT_FOUND")
    limit, offset = pagination()
    rows = [e for e in DB.all("exchange") if e["purchase_id"] == purchase_id]
    rows = sorted_by_created(rows)
    return ok_list(public_list(rows), limit, offset)


@bp.post("/exchanges/<exchange_id>/quotations")
def quote_exchange(exchange_id):
    """Quote the fee and the value returned under the base exchange variant."""
    actor(["CustomerService"])
    body = payload()
    exchange = DB.get("exchange", exchange_id)
    if exchange is None:
        raise ApiError("ERR_EXCHANGE_NOT_FOUND")
    purchase = DB.get("purchase", exchange["purchase_id"])
    if purchase is None:
        raise ApiError("ERR_PURCHASE_NOT_FOUND")

    guards_helpers.require_occ(body, "expected_purchase_version", purchase)

    if exchange["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    if str(exchange.get("original_amount_cents")) != str(_recalled_amount(purchase)):
        raise ApiError("ERR_INVALID_STATE")

    target = DB.get("allocation", exchange["target_allocation_id"])
    _allocation, performance, production = _context(purchase)
    exchange["status"] = "QUOTED"
    fee, value_returned = calc.exchange_cost(
        purchase, target, production, performance, "QUOTED"
    )
    exchange["fee_cents"] = fee
    exchange["value_returned_cents"] = value_returned
    DB.touch("exchange", exchange)
    DB.touch("purchase", purchase)
    return ok(public(exchange))


def _recalled_amount(purchase):
    """The amount the patron recalls paying; the purchase reports its own figure."""
    return purchase.get("amount_paid_cents", purchase.get("subtotal_cents"))


@bp.post("/exchanges/<exchange_id>/approvals")
def approve_exchange(exchange_id):
    """Approve or reject a quoted exchange; the approver must differ from the opener."""
    user_id, _role = actor(["CustomerService"])
    body = payload()
    exchange = DB.get("exchange", exchange_id)
    if exchange is None:
        raise ApiError("ERR_EXCHANGE_NOT_FOUND")
    purchase = DB.get("purchase", exchange["purchase_id"])
    if purchase is None:
        raise ApiError("ERR_PURCHASE_NOT_FOUND")

    guards_helpers.require_occ(body, "expected_purchase_version", purchase)

    if exchange["status"] not in ("REQUESTED", "QUOTED"):
        raise ApiError("ERR_INVALID_STATE")
    if exchange["status"] in EXCHANGE_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")

    from guards import require_distinct

    require_distinct(user_id, exchange.get("requested_by"))

    decision = str(body.get("decision") or "").strip().upper()
    exchange["approved_by"] = user_id
    if decision == "REJECT":
        exchange["status"] = "REJECTED"
    else:
        if exchange["status"] != "QUOTED":
            raise ApiError("ERR_INVALID_STATE")
        exchange["status"] = "APPROVED"
    DB.touch("exchange", exchange)
    DB.touch("purchase", purchase)
    return ok(public(exchange))


@bp.post("/exchanges/<exchange_id>/application")
def apply_exchange(exchange_id):
    """Apply an approved exchange: move the seats and conserve the remainder."""
    actor(["CustomerService"])
    body = payload()
    exchange = DB.get("exchange", exchange_id)
    if exchange is None:
        raise ApiError("ERR_EXCHANGE_NOT_FOUND")
    purchase = DB.get("purchase", exchange["purchase_id"])
    if purchase is None:
        raise ApiError("ERR_PURCHASE_NOT_FOUND")
    performance = DB.get("performance", purchase["performance_id"])
    target = DB.get("allocation", exchange["target_allocation_id"])

    guards_helpers.require_occ(body, "expected_purchase_version", purchase)
    guards_helpers.require_occ(body, "expected_performance_version", performance)

    if exchange["status"] == "APPROVED":
        if target is None or target["status"] != "RELEASED":
            raise ApiError("ERR_INVALID_STATE")
        remaining = int(target.get("daily_release_cap") or 0) - int(
            target.get("quantity_sold_today") or 0
        )
        if remaining < int(purchase["quantity"]):
            raise ApiError("ERR_ALLOCATION_EXHAUSTED")
        _apply(exchange, purchase, performance, target)
    elif exchange["status"] in ("REQUESTED", "QUOTED"):
        exchange["status"] = "REJECTED"
        DB.touch("exchange", exchange)
        DB.touch("purchase", purchase)
    else:
        raise ApiError("ERR_INVALID_STATE")
    return ok(public(exchange))


def _apply(exchange, purchase, performance, target):
    exchange["status"] = "APPLIED"
    exchange["exchange_epoch"] = _epoch()
    DB.touch("exchange", exchange)

    purchase["refunded_cents"] = int(exchange.get("fee_cents") or 0) + (
        int(exchange.get("original_amount_cents") or 0)
        - int(exchange.get("value_returned_cents") or 0)
    )
    purchase["allocation_id"] = target["id"]
    DB.touch("purchase", purchase)

    holds.release_allocation_holds_for_labels(
        performance["id"], purchase.get("seat_labels") or []
    )
    purchase["seat_labels"] = holds.next_run(performance["id"], purchase["quantity"])
    holds.create_allocation_hold(performance["id"], target["id"], purchase["seat_labels"])

    source = DB.get("allocation", exchange.get("source_allocation_id"))
    if source is not None:
        source["quantity_sold_today"] = max(
            0, int(source.get("quantity_sold_today") or 0) - int(purchase["quantity"])
        )
        DB.touch("allocation", source)
    target["quantity_sold_today"] = int(target.get("quantity_sold_today") or 0) + int(
        purchase["quantity"]
    )
    DB.touch("allocation", target)

    engine.dispatch_handoff(purchase, performance)
    DB.touch("performance", performance)


def _epoch():
    from state import epoch_index

    return epoch_index.get()