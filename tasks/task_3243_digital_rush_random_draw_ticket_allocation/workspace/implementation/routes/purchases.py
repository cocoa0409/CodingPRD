"""Orders: creation, listing, reads, settlement and push delivery."""

from flask import Blueprint, request

from db import DB
from errors import ApiError
from response import apply_filters, ok, ok_list, public, public_list, sorted_by_created
from routes import actor, pagination, payload
import guards_helpers
from services import calc, engine, holds, purchases as purchase_service

bp = Blueprint("purchases", __name__)

PURCHASE_TERMINAL = ("REFUNDED", "VOIDED")
READ_ROLES = [
    "OpsManager",
    "CustomerService",
    "FinancialOps",
    "ConciergeDeskStaff",
    "Patron",
    "ProducerAnalyst",
    "DemandAnalyst",
]


def _replay(purchase, body):
    """A repeat of the same key and payload replays the original response."""
    return (
        purchase["performance_id"] == body.get("performance_id")
        and purchase["allocation_id"] == body.get("allocation_id")
        and int(purchase["quantity"]) == int(body.get("quantity") or 0)
    )


@bp.post("/purchases")
def create_purchase():
    """Buy rush seats. The patron must hold an admission or be buying a claimed win."""
    user_id, _role = actor(["Patron"])
    body = payload()

    idempotency_key = body.get("idempotency_key")
    if idempotency_key is not None:
        for existing in DB.all("purchase"):
            if existing.get("idempotency_key") != idempotency_key:
                continue
            if existing["patron_id"] != user_id:
                continue
            if _replay(existing, body):
                return ok(public(existing), 201)

    performance = DB.get("performance", body.get("performance_id"))
    if performance is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    allocation = DB.get("allocation", body.get("allocation_id"))
    if allocation is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    if allocation["performance_id"] != performance["id"]:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    quantity = int(body.get("quantity") or 0)
    if quantity < 1:
        raise ApiError("ERR_INVALID_STATE")

    guards_helpers.require_released_allocation(allocation, performance)
    purchase_service.resolve_admission(performance["id"], user_id, allocation)

    run = holds.next_run(performance["id"], quantity)
    guards_helpers.require_run_free(performance, run)
    guards_helpers.require_daily_capacity(allocation, quantity)
    guards_helpers.require_per_order_limit(allocation, quantity)
    guards_helpers.require_production_active(performance)

    purchase = purchase_service.open_order(
        performance, allocation, user_id, quantity, idempotency_key=idempotency_key
    )
    return ok(public(purchase), 201)


@bp.get("/purchases")
def list_purchases():
    actor(READ_ROLES)
    limit, offset = pagination()
    rows = list(DB.all("purchase"))
    rows = apply_filters(
        rows,
        request.args,
        (
            "patron_id",
            "performance_id",
            "allocation_id",
            "payment_status",
            "logistics_status",
            "handoff_status",
        ),
    )
    rows = sorted_by_created(rows)
    return ok_list(public_list(rows), limit, offset)


@bp.get("/purchases/<purchase_id>")
def read_purchase(purchase_id):
    actor(READ_ROLES)
    purchase = DB.get("purchase", purchase_id)
    if purchase is None:
        raise ApiError("ERR_PURCHASE_NOT_FOUND")
    return ok(public(purchase))


@bp.post("/purchases/<purchase_id>/settlements")
def settle_purchase(purchase_id):
    """Authorize and settle a pending purchase, consuming its seat holds."""
    actor(["FinancialOps"])
    body = payload()
    purchase = DB.get("purchase", purchase_id)
    if purchase is None:
        raise ApiError("ERR_PURCHASE_NOT_FOUND")

    guards_helpers.require_occ(body, "expected_purchase_version", purchase)

    if purchase["payment_status"] == "PENDING":
        if purchase["logistics_status"] not in ("AWAITING_HANDOFF", "REVOKED"):
            raise ApiError("ERR_INVALID_STATE")
        for label in purchase.get("seat_labels") or []:
            hold = holds.non_terminal_hold_on_label(purchase["performance_id"], label)
            if hold is not None and hold["hold_kind"] == "ALLOCATION" and hold["status"] != "HELD":
                raise ApiError("ERR_INVALID_STATE")
        purchase["payment_status"] = "AUTHORIZED"
        DB.touch("purchase", purchase)
    elif purchase["payment_status"] == "AUTHORIZED":
        purchase["payment_status"] = "SETTLED"
        purchase["settlement_epoch"] = _epoch()
        DB.touch("purchase", purchase)
        holds.consume_allocation_holds_for_labels(
            purchase["performance_id"], purchase.get("seat_labels") or []
        )
        for refund in DB.all("refund"):
            if refund["purchase_id"] != purchase["id"]:
                continue
            if refund["status"] == "PROCESSING":
                refund["status"] = "SETTLED"
                DB.touch("refund", refund)
    else:
        raise ApiError("ERR_INVALID_STATE")

    return ok(public(purchase))


def _epoch():
    from state import epoch_index

    return epoch_index.get()


@bp.post("/purchases/<purchase_id>/deliveries")
def deliver_purchase(purchase_id):
    """Push the ticket to the patron's phone; push markets only."""
    actor(["DemandAnalyst", "CustomerService"])
    body = payload()
    purchase = DB.get("purchase", purchase_id)
    if purchase is None:
        raise ApiError("ERR_PURCHASE_NOT_FOUND")
    guards_helpers.require_occ(body, "expected_purchase_version", purchase)

    performance = DB.get("performance", purchase["performance_id"])
    market = None
    if performance is not None:
        for candidate in DB.all("market"):
            if candidate["market_code"] == performance["market_code"]:
                market = candidate
                break
    if market is None or market["handoff_model"] != "MOBILE_PUSH":
        raise ApiError("ERR_INVALID_STATE")
    if purchase["logistics_status"] != "AWAITING_HANDOFF":
        raise ApiError("ERR_INVALID_STATE")
    if purchase["payment_status"] not in ("AUTHORIZED", "SETTLED"):
        raise ApiError("ERR_INVALID_STATE")

    purchase["logistics_status"] = "DELIVERED"
    return ok(public(DB.touch("purchase", purchase)))