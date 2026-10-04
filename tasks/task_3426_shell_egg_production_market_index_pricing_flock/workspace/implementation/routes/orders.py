"""Sales orders and settlements (PRD §3.6, §3.7): OCC-guarded booking, the
allocation selector, shipment with provisional pricing, cancellation, and the
settlement lifecycle (finalize / dispute / resolve / mark-paid)."""

from datetime import timedelta

from flask import Blueprint, request

from auth import authenticate, check_customer_ownership, require_role
from calc import (
    commitment_of_order,
    compute_final_pricing,
    customer_of_commitment,
    latest_quotation,
    select_allocation,
    week_average,
)
from db import STORE, stamp_new, touch
from errors import (
    ApiError,
    ERR_COMMITMENT_WEEKLY_VOLUME_EXCEEDED,
    ERR_CUSTOMER_SUSPENDED,
    ERR_INVALID_STATE,
    ERR_NO_QUOTATION,
    ERR_ORDER_OUTSIDE_COMMITMENT_WINDOW,
    ERR_ORDER_OUTSIDE_SHIP_WINDOW,
    ERR_SETTLEMENT_NOT_FINALIZABLE,
    ERR_SHIP_WEEK_NOT_MONDAY,
    ERR_STALE_COMMITMENT_VERSION,
)
from helpers import (
    get_commitment,
    get_complex,
    get_order,
    get_settlement,
    list_response,
)
from serialize import serialize_order, serialize_settlement
from util import SIZE_CLASSES, success_object
from validate import apply_values, get_body, validate_payload

bp = Blueprint("orders", __name__)

_SHIP_WINDOW_DAYS = 14


def _is_monday_midnight_utc(dt):
    return (
        dt.weekday() == 0
        and dt.hour == 0
        and dt.minute == 0
        and dt.second == 0
        and dt.microsecond == 0
    )


# ---------------------------------------------------------------------------
# Order booking (OCC-guarded on the commitment version)
# ---------------------------------------------------------------------------
@bp.route("/api/commitments/<cid>/orders", methods=["POST"])
def create_order(cid):
    uid, role = authenticate()
    require_role(role, {"Customer", "SalesManager"})
    commitment = get_commitment(cid)
    # Priority 3: entity-backed ownership precedes payload shape.
    check_customer_ownership(uid, role, commitment["customer_id"])
    values, raws = validate_payload(
        get_body(),
        {
            "ship_week_start": {"kind": "datetime", "required": True},
            "dozen_ordered": {"kind": "int", "required": True, "gt": 0},
            "size_class": {
                "kind": "enum", "required": True, "enum": SIZE_CLASSES,
            },
            "expected_commitment_version": {"kind": "int", "required": True},
        },
    )
    # Priority 7: cross-entity state gate.
    if commitment["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "commitment is not ACTIVE")
    # Priority 8: optimistic concurrency on the commitment version.
    if values["expected_commitment_version"] != commitment["version"]:
        raise ApiError(
            ERR_STALE_COMMITMENT_VERSION,
            412,
            "expected_commitment_version does not match the commitment version",
        )
    ship_week_start = values["ship_week_start"]
    if not _is_monday_midnight_utc(ship_week_start):
        raise ApiError(
            ERR_SHIP_WEEK_NOT_MONDAY,
            422,
            "ship_week_start must be exactly a Monday 00:00:00Z",
        )
    if not (
        commitment["_dt_effective_from"]
        <= ship_week_start
        <= commitment["_dt_effective_to"]
    ):
        raise ApiError(
            ERR_ORDER_OUTSIDE_COMMITMENT_WINDOW,
            422,
            "ship_week_start is outside the commitment window",
        )
    customer = STORE.customers.get(commitment["customer_id"])
    if customer is None or customer["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_SUSPENDED, 422, "customer is SUSPENDED")
    used = sum(
        o["dozen_ordered"]
        for o in STORE.orders.values()
        if o["commitment_id"] == commitment["id"]
        and o["status"] in ("BOOKED", "ALLOCATED", "SHIPPED")
        and o["_dt_ship_week_start"] == ship_week_start
    )
    if values["dozen_ordered"] > commitment["weekly_dozen_committed"] - used:
        raise ApiError(
            ERR_COMMITMENT_WEEKLY_VOLUME_EXCEEDED,
            422,
            "the commitment's remaining volume for that ship week is exceeded",
        )
    order = {
        "commitment_id": commitment["id"],
        "dozen_ordered": values["dozen_ordered"],
        "size_class": values["size_class"],
        "status": "BOOKED",
        "allocated_complex_id": None,
        "allocated_dozen": None,
    }
    apply_values(order, {"ship_week_start": values["ship_week_start"]},
                 {"ship_week_start": raws["ship_week_start"]})
    stamp_new(order)
    STORE.orders[order["id"]] = order
    touch(commitment)  # booking bumps the commitment version (OCC bookkeeping)
    return success_object(serialize_order(order), 201)


@bp.route("/api/commitments/<cid>/orders", methods=["GET"])
def list_commitment_orders(cid):
    authenticate()
    commitment = get_commitment(cid)
    items = [
        o for o in STORE.orders.values() if o["commitment_id"] == commitment["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_response(items, serialize_order)


@bp.route("/api/orders/<oid>", methods=["GET"])
def read_order(oid):
    uid, role = authenticate()
    order = get_order(oid)
    commitment = STORE.commitments.get(order["commitment_id"])
    check_customer_ownership(
        uid, role, commitment["customer_id"] if commitment else None
    )
    return success_object(serialize_order(order))


# ---------------------------------------------------------------------------
# Allocation (deferred matching; empty pool -> BLOCKED, still 200)
# ---------------------------------------------------------------------------
@bp.route("/api/orders/<oid>/allocate", methods=["POST"])
def allocate_order(oid):
    _uid, role = authenticate()
    require_role(role, {"ProductionPlanner"})
    order = get_order(oid)
    validate_payload(get_body(), {})
    if order["status"] not in ("BOOKED", "BLOCKED"):
        raise ApiError(
            ERR_INVALID_STATE, 409, "order is not BOOKED or BLOCKED"
        )
    commitment = commitment_of_order(order)
    if commitment is None or commitment["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "commitment is not ACTIVE")
    clock = STORE.clock
    if not clock < order["_dt_ship_week_start"] + timedelta(days=_SHIP_WINDOW_DAYS):
        raise ApiError(
            ERR_ORDER_OUTSIDE_SHIP_WINDOW,
            422,
            "the ship window for allocation has closed",
        )
    was_blocked = order["status"] == "BLOCKED"
    chosen = select_allocation(order, commitment)
    if chosen is None:
        order["status"] = "BLOCKED"
        order["allocated_complex_id"] = None
        order["allocated_dozen"] = None
        if not was_blocked:
            commitment["blocked_order_count"] += 1
            touch(commitment)
    else:
        order["status"] = "ALLOCATED"
        order["allocated_complex_id"] = chosen["id"]
        order["allocated_dozen"] = order["dozen_ordered"]
        if was_blocked:
            commitment["blocked_order_count"] -= 1
            touch(commitment)
    touch(order)
    return success_object(serialize_order(order))


# ---------------------------------------------------------------------------
# Shipment: creates the 1:1 PROVISIONAL settlement priced off the latest
# quotation at or before the ship clock.
# ---------------------------------------------------------------------------
@bp.route("/api/orders/<oid>/ship", methods=["POST"])
def ship_order(oid):
    _uid, role = authenticate()
    require_role(role, {"PlantManager"})
    order = get_order(oid)
    validate_payload(get_body(), {})
    if order["status"] != "ALLOCATED":
        raise ApiError(ERR_INVALID_STATE, 409, "order is not ALLOCATED")
    clock = STORE.clock
    week_start = order["_dt_ship_week_start"]
    if not (week_start <= clock < week_start + timedelta(days=_SHIP_WINDOW_DAYS)):
        raise ApiError(
            ERR_ORDER_OUTSIDE_SHIP_WINDOW,
            422,
            "the clock is outside the ship window",
        )
    commitment = commitment_of_order(order)
    quotation = latest_quotation(
        commitment["region_code"], order["size_class"], clock
    )
    if quotation is None:
        raise ApiError(
            ERR_NO_QUOTATION,
            422,
            "no quotation for the commitment's region and the order's size "
            "class is effective at or before the clock",
        )
    unit_price = (
        quotation["price_cents_per_dozen"]
        + commitment["price_adjustment_cents_per_dozen"]
    )
    dozen_shipped = order["allocated_dozen"]
    settlement = {
        "sales_order_id": order["id"],
        "ship_week_start": order["ship_week_start"],
        "_dt_ship_week_start": order["_dt_ship_week_start"],
        "dozen_shipped": dozen_shipped,
        "status": "PROVISIONAL",
        "provisional_index_cents": quotation["price_cents_per_dozen"],
        "provisional_unit_price_cents": unit_price,
        "provisional_total_cents": dozen_shipped * unit_price,
        "final_index_average_cents": None,
        "final_volume_discount_cents": None,
        "final_unit_price_cents": None,
        "final_total_cents": None,
        "quotation_ids_used": [],
        "disputed_reason": None,
    }
    stamp_new(settlement)
    STORE.settlements[settlement["id"]] = settlement
    order["status"] = "SHIPPED"
    touch(order)
    return success_object(serialize_order(order))


# ---------------------------------------------------------------------------
# Cancellation (owning Customer only)
# ---------------------------------------------------------------------------
@bp.route("/api/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    order = get_order(oid)
    commitment = commitment_of_order(order)
    check_customer_ownership(
        uid, role, commitment["customer_id"] if commitment else None
    )
    validate_payload(get_body(), {})
    if order["status"] not in ("BOOKED", "ALLOCATED", "BLOCKED"):
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "only BOOKED, ALLOCATED or BLOCKED orders can be cancelled",
        )
    was_blocked = order["status"] == "BLOCKED"
    order["status"] = "CANCELLED"
    touch(order)
    if was_blocked and commitment is not None:
        commitment["blocked_order_count"] -= 1
        touch(commitment)
    return success_object(serialize_order(order))


@bp.route("/api/complexes/<cid>/orders", methods=["GET"])
def list_complex_orders(cid):
    authenticate()
    cx = get_complex(cid)
    items = [
        o
        for o in STORE.orders.values()
        if o.get("allocated_complex_id") == cx["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_response(items, serialize_order)


@bp.route("/api/orders/<oid>/settlements", methods=["GET"])
def list_order_settlements(oid):
    authenticate()
    order = get_order(oid)
    items = [
        s for s in STORE.settlements.values() if s["sales_order_id"] == order["id"]
    ]
    return list_response(items, serialize_settlement)


# ---------------------------------------------------------------------------
# Settlement lifecycle
# ---------------------------------------------------------------------------
@bp.route("/api/settlements/<sid>/finalize", methods=["POST"])
def finalize_settlement(sid):
    _uid, role = authenticate()
    require_role(role, {"SalesManager"})
    settlement = get_settlement(sid)
    validate_payload(get_body(), {})
    if settlement["status"] != "PROVISIONAL":
        raise ApiError(ERR_INVALID_STATE, 409, "settlement is not PROVISIONAL")
    clock = STORE.clock
    week_start = settlement["_dt_ship_week_start"]
    if clock < week_start + timedelta(days=7):
        raise ApiError(
            ERR_SETTLEMENT_NOT_FINALIZABLE,
            409,
            "the settlement week has not closed",
        )
    order = STORE.orders.get(settlement["sales_order_id"])
    commitment = commitment_of_order(order)
    customer = customer_of_commitment(commitment)
    week_avg, _ids = week_average(
        commitment["region_code"], order["size_class"], week_start
    )
    if week_avg is None:
        raise ApiError(
            ERR_NO_QUOTATION,
            422,
            "no quotation falls inside the settlement week",
        )
    index_avg, discount, unit, total, quotation_ids = compute_final_pricing(
        settlement, order, commitment, customer
    )
    settlement["final_index_average_cents"] = index_avg
    settlement["final_volume_discount_cents"] = discount
    settlement["final_unit_price_cents"] = unit
    settlement["final_total_cents"] = total
    settlement["quotation_ids_used"] = quotation_ids
    settlement["status"] = "FINAL"
    touch(settlement)
    order["status"] = "SETTLED"
    touch(order)
    customer["outstanding_cents"] += total
    if customer["outstanding_cents"] > customer["credit_limit_cents"]:
        customer["status"] = "SUSPENDED"
    touch(customer)
    return success_object(serialize_settlement(settlement))


@bp.route("/api/settlements/<sid>/dispute", methods=["POST"])
def dispute_settlement(sid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    settlement = get_settlement(sid)
    order = STORE.orders.get(settlement["sales_order_id"])
    commitment = commitment_of_order(order) if order else None
    check_customer_ownership(
        uid, role, commitment["customer_id"] if commitment else None
    )
    values, _raws = validate_payload(
        get_body(), {"reason": {"kind": "string", "required": True}}
    )
    if settlement["status"] != "FINAL":
        raise ApiError(ERR_INVALID_STATE, 409, "settlement is not FINAL")
    settlement["status"] = "DISPUTED"
    settlement["disputed_reason"] = values["reason"]
    touch(settlement)
    return success_object(serialize_settlement(settlement))


@bp.route("/api/settlements/<sid>/resolve", methods=["POST"])
def resolve_settlement(sid):
    _uid, role = authenticate()
    require_role(role, {"SalesManager"})
    settlement = get_settlement(sid)
    validate_payload(get_body(), {})
    if settlement["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE, 409, "settlement is not DISPUTED")
    # Amounts pinned at finalize are preserved verbatim — no repricing.
    settlement["status"] = "FINAL"
    settlement["disputed_reason"] = None
    touch(settlement)
    return success_object(serialize_settlement(settlement))


@bp.route("/api/settlements/<sid>/mark-paid", methods=["POST"])
def mark_settlement_paid(sid):
    _uid, role = authenticate()
    require_role(role, {"SalesManager"})
    settlement = get_settlement(sid)
    validate_payload(get_body(), {})
    if settlement["status"] != "FINAL":
        raise ApiError(ERR_INVALID_STATE, 409, "settlement is not FINAL")
    settlement["status"] = "PAID"
    touch(settlement)
    order = STORE.orders.get(settlement["sales_order_id"])
    commitment = commitment_of_order(order) if order else None
    customer = customer_of_commitment(commitment) if commitment else None
    if customer is not None:
        customer["outstanding_cents"] -= settlement["final_total_cents"]
        if (
            customer["status"] == "SUSPENDED"
            and customer["outstanding_cents"] <= customer["credit_limit_cents"]
        ):
            customer["status"] = "ACTIVE"
        touch(customer)
    return success_object(serialize_settlement(settlement))
