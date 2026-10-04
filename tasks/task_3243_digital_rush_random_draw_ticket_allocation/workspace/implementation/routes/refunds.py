"""Refund requests: opening, approval, settlement and listing."""

from flask import Blueprint

from clock import CLOCK
from db import DB
from errors import ApiError
from response import ok, ok_list, public, public_list, sorted_by_created
from routes import actor, pagination, payload
import guards_helpers
from services import calc, engine

bp = Blueprint("refunds", __name__)

REASON_CODES = ("PATRON_REQUEST", "PERFORMANCE_CANCELLED", "PLATFORM_FAULT", "DESK_FAILURE")
REFUND_TERMINAL = ("SETTLED", "REJECTED", "COMPENSATED")


def _context(purchase):
    allocation = DB.get("allocation", purchase["allocation_id"])
    performance = DB.get("performance", purchase["performance_id"])
    production = DB.get("production", performance["production_id"]) if performance else None
    return allocation, performance, production


@bp.post("/purchases/<purchase_id>/refund-requests")
def open_refund(purchase_id):
    """Open a refund; the base amount is priced by the refund_amount rule."""
    user_id, role = actor(["Patron", "CustomerService"])
    body = payload()
    purchase = DB.get("purchase", purchase_id)
    if purchase is None:
        raise ApiError("ERR_PURCHASE_NOT_FOUND")

    guards_helpers.require_occ(body, "expected_purchase_version", purchase)

    if role == "Patron" and str(purchase["patron_id"]) != str(user_id):
        raise ApiError("ERR_FORBIDDEN")

    reason_code = body.get("reason_code")
    if reason_code not in REASON_CODES:
        raise ApiError("ERR_INVALID_STATE")

    allocation, performance, production = _context(purchase)
    if purchase["payment_status"] not in ("AUTHORIZED", "SETTLED", "PARTIALLY_REFUNDED"):
        raise ApiError("ERR_INVALID_STATE")

    patron = DB.get("patron", purchase["patron_id"])
    if patron is None:
        raise ApiError("ERR_PATRON_NOT_FOUND")
    if patron["status"] != "ACTIVE" and reason_code != "PERFORMANCE_CANCELLED":
        raise ApiError("ERR_INVALID_STATE")

    if reason_code != "PERFORMANCE_CANCELLED":
        _require_refund_window(purchase, allocation, production, performance)

    refund = {
        "purchase_id": purchase["id"],
        "patron_id": purchase["patron_id"],
        "reason_code": reason_code,
        "status": "REQUESTED",
        "approved_by": None,
        "requested_by": user_id,
        "refunded_amount_cents": 0,
        "pre_settlement_refunded_cents": int(purchase.get("refunded_cents") or 0),
    }
    purchase["_refund_status"] = "REQUESTED"
    refund["refunded_amount_cents"] = calc.refund_amount(
        purchase, allocation, production, performance
    )
    purchase.pop("_refund_status", None)
    DB.insert("refund", refund)
    DB.touch("purchase", purchase)
    return ok(public(refund), 201)


def _require_refund_window(purchase, allocation, production, performance):
    """Thirteenth rung: the production's refund window must still permit a return."""
    if allocation is None or production is None or performance is None:
        raise ApiError("ERR_REFUND_WINDOW_CLOSED")
    from clock import parse_iso

    hours_before_start = (parse_iso(performance["starts_at"]) - CLOCK.now).total_seconds() / 3600.0
    window = int(production.get("refund_window_hours") or 0)
    if hours_before_start >= window:
        return
    if bool(allocation.get("refundable")) and hours_before_start > 0:
        return
    raise ApiError("ERR_REFUND_WINDOW_CLOSED")


@bp.get("/purchases/<purchase_id>/refund-requests")
def list_refunds(purchase_id):
    actor(["CustomerService", "FinancialOps", "Patron", "PlatformAdmin"])
    purchase = DB.get("purchase", purchase_id)
    if purchase is None:
        raise ApiError("ERR_PURCHASE_NOT_FOUND")
    limit, offset = pagination()
    rows = [r for r in DB.all("refund") if r["purchase_id"] == purchase_id]
    rows = sorted_by_created(rows)
    return ok_list(public_list(rows), limit, offset)


@bp.post("/refunds/<refund_id>/approvals")
def approve_refund(refund_id):
    """Approve a requested refund, or reject it outright."""
    user_id, _role = actor(["CustomerService"])
    body = payload()
    refund = DB.get("refund", refund_id)
    if refund is None:
        raise ApiError("ERR_REFUND_NOT_FOUND")
    purchase = DB.get("purchase", refund["purchase_id"])
    if purchase is None:
        raise ApiError("ERR_PURCHASE_NOT_FOUND")

    guards_helpers.require_occ(body, "expected_purchase_version", purchase)

    if refund["status"] not in ("REQUESTED", "PROCESSING"):
        raise ApiError("ERR_INVALID_STATE")
    if refund["status"] in REFUND_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")

    from guards import require_distinct

    require_distinct(user_id, refund.get("requested_by"))

    decision = str(body.get("decision") or "").strip().upper()
    refund["approved_by"] = user_id
    if decision == "REJECT":
        refund["status"] = "REJECTED"
    else:
        if refund["status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE")
        refund["status"] = "PROCESSING"
    DB.touch("refund", refund)
    DB.touch("purchase", purchase)
    return ok(public(refund))


@bp.post("/refunds/<refund_id>/settlement")
def settle_refund(refund_id):
    """Settle a processing refund: return the money and the seats."""
    actor(["FinancialOps"])
    body = payload()
    refund = DB.get("refund", refund_id)
    if refund is None:
        raise ApiError("ERR_REFUND_NOT_FOUND")
    purchase = DB.get("purchase", refund["purchase_id"])
    if purchase is None:
        raise ApiError("ERR_PURCHASE_NOT_FOUND")

    guards_helpers.require_occ(body, "expected_purchase_version", purchase)

    if refund["status"] != "PROCESSING":
        raise ApiError("ERR_INVALID_STATE")

    allocation, performance, production = _context(purchase)
    refund["status"] = "SETTLED"
    refund["refunded_amount_cents"] = _priced_refund(purchase, allocation, production, performance)
    DB.touch("refund", refund)

    refund["pre_settlement_refunded_cents"] = int(purchase.get("refunded_cents") or 0)
    purchase["refunded_cents"] = int(purchase.get("refunded_cents") or 0) + int(
        refund["refunded_amount_cents"]
    )
    purchase["payment_status"] = "REFUNDED"
    DB.touch("purchase", purchase)

    if allocation is not None:
        allocation["quantity_sold_today"] = max(
            0, int(allocation.get("quantity_sold_today") or 0) - int(purchase["quantity"])
        )
        DB.touch("allocation", allocation)
        engine.maybe_allocation_reopened(allocation)
    return ok(public(refund))


def _priced_refund(purchase, allocation, production, performance):
    purchase["_refund_status"] = "SETTLED"
    amount = calc.refund_amount(purchase, allocation, production, performance)
    purchase.pop("_refund_status", None)
    return amount