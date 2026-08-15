"""BuyBackRequest endpoints: excess returns and shortage buy-backs."""

import math
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

import clock
import db
import errors as E
from errors import ApiError
from middleware import require_auth, require_role
from response import success
from services.helpers import (
    check_buyer_body_ownership,
    get_buyback_or_404,
    get_json_body,
    get_order_line_or_404,
    mint_id,
    paginate,
    pagination_params,
    recompute_part_availability,
    req_enum,
    req_int,
    req_str,
    serialize_buyback,
    stamp_now,
    valid_date_code,
    whole_days_between,
)

bp = Blueprint("buybacks", __name__)

_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def _fee_pct(days, kind):
    if kind == "SHORTAGE_BUYBACK":
        return 0.0
    if days <= 90:
        return 0.10
    if days <= 180:
        return 0.25
    return 0.25


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


@bp.post("/buy-backs")
def create_buyback():
    user_id, role = require_auth()
    require_role(user_id, role, {"SalesRep", "CustomerBuyer"})
    body = get_json_body()
    customer_id = req_str(body, "customer_id")
    order_line_id = req_str(body, "order_line_id")
    kind = req_enum(body, "kind", {"EXCESS_RETURN", "SHORTAGE_BUYBACK"})
    qty = req_int(body, "qty")
    if qty <= 0:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "qty must be positive.")

    # Ownership (priority 2) precedes FK existence (priority 3) for body customer_id.
    check_buyer_body_ownership(user_id, role, customer_id)

    customer = db.customers.get(customer_id)
    if customer is None:
        raise ApiError(E.ERR_CUSTOMER_NOT_FOUND, 404, "Customer not found.")
    line = db.order_lines.get(order_line_id)
    if line is None:
        raise ApiError(E.ERR_ORDER_LINE_NOT_FOUND, 404, "Order line not found.")

    now = clock.now()
    part = db.parts.get(line["part_id"])

    # constraint (priority 6): qty covered by the line
    covered = sum(
        b["qty"]
        for b in db.buy_backs.values()
        if b["order_line_id"] == order_line_id and b["status"] in ("REQUESTED", "APPROVED", "RECEIVED")
    )
    if qty > line["shipped_qty"] - covered:
        raise ApiError(
            E.ERR_BUYBACK_QTY_EXCEEDED,
            409,
            "Requested qty exceeds shipped_qty minus quantities already covered.",
        )

    # temporal (priority 7): excess returns must land within 180 days of last shipment (inclusive)
    if kind == "EXCESS_RETURN":
        last = line["_last_shipped_at"]
        if last is None or now > last + timedelta(days=180):
            raise ApiError(
                E.ERR_BUYBACK_WINDOW_CLOSED,
                409,
                "Buy-back window closed (now > last_shipped_at + 180 days).",
            )

    # referential (priority 8): shortage must actually be in effect for SHORTAGE_BUYBACK
    if kind == "SHORTAGE_BUYBACK":
        shortage = any(
            r["part_id"] == line["part_id"]
            and r["status"] == "PUBLISHED"
            and r["total_demand_qty"] > r["total_supply_qty"]
            for r in db.allocation_runs.values()
        )
        if not shortage:
            raise ApiError(
                E.ERR_SHORTAGE_NOT_IN_EFFECT,
                409,
                "No PUBLISHED shortage allocation run exists for the part.",
            )

    if kind == "EXCESS_RETURN":
        price_basis = min(line["unit_price_cents"], part["book_price_cents"] if part else 0)
    else:
        price_basis = part["book_price_cents"] if part else 0
    last = line["_last_shipped_at"]
    days = whole_days_between(last, now) if last is not None else 0
    fee = _fee_pct(days, kind)
    provisional = _round_half_up(qty * price_basis * (1.0 - fee))

    # fiscal: 15% trailing-purchases cap for excess returns (inclusive)
    if kind == "EXCESS_RETURN":
        cap = math.floor(0.15 * customer["trailing_12mo_purchases_cents"])
        window_start = now - timedelta(days=365)
        used = 0
        for b in db.buy_backs.values():
            if (
                b["customer_id"] == customer_id
                and b["kind"] == "EXCESS_RETURN"
                and b["status"] in ("REQUESTED", "APPROVED", "RECEIVED")
                and b["_created_at"] >= window_start
            ):
                used += b["final_credit_cents"] if b["status"] == "RECEIVED" else b["provisional_credit_cents"]
        if used + provisional > cap:
            raise ApiError(
                E.ERR_BUYBACK_CAP_EXCEEDED, 422, "Excess buy-back cap exceeded."
            )

    now_str = stamp_now()
    bb = {
        "id": mint_id(),
        "customer_id": customer_id,
        "order_line_id": order_line_id,
        "kind": kind,
        "qty": qty,
        "price_basis_cents": price_basis,
        "fee_pct": fee,
        "provisional_credit_cents": provisional,
        "received_qty": None,
        "final_credit_cents": None,
        "status": "REQUESTED",
        "created_at": now_str,
        "updated_at": now_str,
        "version": 1,
        "_seq": _next_seq(),
        "_created_at": now,
    }
    db.buy_backs[bb["id"]] = bb
    return success(serialize_buyback(bb), status=201)


@bp.get("/buy-backs")
def list_buybacks():
    require_auth()
    limit, offset = pagination_params()
    customer_id = request.args.get("customer_id")
    order_line_id = request.args.get("order_line_id")
    status = request.args.get("status")
    items = list(db.buy_backs.values())
    if customer_id is not None:
        items = [b for b in items if b["customer_id"] == customer_id]
    if order_line_id is not None:
        items = [b for b in items if b["order_line_id"] == order_line_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    page, pag = paginate(items, limit, offset)
    return success(
        [serialize_buyback(b) for b in page],
        status=200,
        response_type="array",
        pagination=pag,
    )


@bp.get("/buy-backs/<buyBackId>")
def get_buyback(buyBackId):
    require_auth()
    bb = get_buyback_or_404(buyBackId)
    return success(serialize_buyback(bb), status=200)


@bp.post("/buy-backs/<buyBackId>/decision")
def decide_buyback(buyBackId):
    user_id, role = require_auth()
    require_role(user_id, role, {"DistributorAdmin"})
    body = get_json_body()
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "decision must be APPROVE or REJECT.")
    bb = get_buyback_or_404(buyBackId)
    if bb["status"] != "REQUESTED":
        raise ApiError(E.ERR_BUYBACK_INVALID_STATE, 409, "Buy-back is not REQUESTED.")
    bb["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    bb["updated_at"] = stamp_now()
    bb["version"] += 1
    return success(serialize_buyback(bb), status=200)


@bp.post("/buy-backs/<buyBackId>/receive")
def receive_buyback(buyBackId):
    user_id, role = require_auth()
    require_role(user_id, role, {"WarehouseOps"})
    body = get_json_body()
    received_qty = req_int(body, "received_qty")
    lot_date_code = req_str(body, "lot_date_code")
    if received_qty <= 0:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "received_qty must be positive.")
    if not valid_date_code(lot_date_code):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "lot_date_code must be YYYYMM.")

    bb = get_buyback_or_404(buyBackId)
    if bb["status"] != "APPROVED":
        raise ApiError(E.ERR_BUYBACK_INVALID_STATE, 409, "Buy-back is not APPROVED.")
    if received_qty > bb["qty"]:
        raise ApiError(
            E.ERR_BUYBACK_QTY_EXCEEDED, 409, "received_qty exceeds the requested qty."
        )

    now = clock.now()
    line = db.order_lines.get(bb["order_line_id"])
    last = line["_last_shipped_at"] if line else None
    days = whole_days_between(last, now) if last is not None else 0
    fee = _fee_pct(days, bb["kind"])
    final_credit = _round_half_up(received_qty * bb["price_basis_cents"] * (1.0 - fee))

    bb["received_qty"] = received_qty
    bb["final_credit_cents"] = final_credit
    bb["status"] = "RECEIVED"
    bb["updated_at"] = stamp_now()
    bb["version"] += 1

    if line is not None:
        line["returned_qty"] += received_qty
        line["updated_at"] = stamp_now()
        line["version"] += 1

    # Returned units re-enter as an open-market inspection lot.
    now_str = stamp_now()
    lot = {
        "id": mint_id(),
        "part_id": line["part_id"] if line else None,
        "date_code": lot_date_code,
        "qty_received": received_qty,
        "qty_on_hand": received_qty,
        "qty_reserved": 0,
        "qty_shipped": 0,
        "source_type": "OPEN_MARKET",
        "authenticity": "PENDING_INSPECTION",
        "last_baked_at": None,
        "_last_baked_at": None,
        "received_by_user_id": user_id,
        "status": "IN_INSPECTION",
        "created_at": now_str,
        "updated_at": now_str,
        "version": 1,
        "_seq": _next_seq(),
    }
    db.inventory_lots[lot["id"]] = lot
    if line is not None:
        recompute_part_availability(line["part_id"])

    return success(serialize_buyback(bb), status=200)
