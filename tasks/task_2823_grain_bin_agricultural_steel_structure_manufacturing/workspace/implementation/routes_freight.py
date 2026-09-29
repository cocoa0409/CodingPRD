"""Freight loads, yard staging and the linehaul split (PRD 3.8)."""
from flask import Blueprint, request

import calc
import serializers
import services
import store
from authz import ALL_ROLES, authorize
from common import D, rhu
from envelope import created, ok, paginated
from errors import ApiError
from routes_orders import find_order
from routes_parties import find_dealer
from shape import body, req_dt, req_enum, req_int, req_str
from store import insert, touch

bp = Blueprint("freight", __name__)

TRAILER_TYPES = ("FLATBED", "HIGH_CUBE_VAN", "STEP_DECK")
ALLOCATION_BASES = ("WEIGHT", "CUBE")


def find_load(row_id):
    row = store.freight_loads.get(row_id)
    if row is None:
        raise ApiError("ERR_FREIGHT_LOAD_NOT_FOUND")
    return row


@bp.post("/freight-loads")
def plan_load():
    authorize(("LogisticsCoordinator",))
    payload = body()
    dealer_id = req_str(payload, "dealer_id")
    trailer_type = req_enum(payload, "trailer_type", TRAILER_TYPES)
    allocation_basis = req_enum(payload, "allocation_basis", ALLOCATION_BASES)
    yard_window_start = req_dt(payload, "yard_window_start")
    yard_window_end = req_dt(payload, "yard_window_end")
    expected_dealer_version = req_int(payload, "expected_dealer_version")

    dealer = find_dealer(dealer_id)

    if expected_dealer_version != dealer["version"]:
        raise ApiError("ERR_STALE_DEALER_VERSION")

    if yard_window_end < yard_window_start:
        raise ApiError("ERR_WINDOW_ORDER_INVALID")

    # Closed intervals: windows that merely touch at an instant do intersect.
    overlapping = 0
    for existing in store.loads_of_dealer(dealer_id):
        if existing["status"] != "PLANNED":
            continue
        if (
            yard_window_start <= existing["yard_window_end"]
            and existing["yard_window_start"] <= yard_window_end
        ):
            overlapping += 1
    if overlapping >= dealer["staging_slots"]:
        raise ApiError("ERR_YARD_SLOTS_EXHAUSTED")

    if trailer_type == "HIGH_CUBE_VAN" and not dealer["high_cube_access"]:
        raise ApiError("ERR_HIGH_CUBE_ACCESS_DENIED")

    load = {
        "dealer_id": dealer_id,
        "trailer_type": trailer_type,
        "allocation_basis": allocation_basis,
        "yard_window_start": yard_window_start,
        "yard_window_end": yard_window_end,
        "max_cube_m3": calc.TRAILER_CUBE_M3[trailer_type],
        "max_weight_kg": calc.TRAILER_WEIGHT_KG[trailer_type],
        "assigned_cube_m3": D("0"),
        "assigned_weight_kg": D("0"),
        "cube_utilization_pct": D("0"),
        "linehaul_cost_cents": 0,
        "order_count": 0,
        "status": "PLANNED",
    }
    insert(store.freight_loads, load)
    services.recompute_staged_kit_count(dealer)
    return created(serializers.freight_load(load))


@bp.get("/freight-loads")
def list_loads():
    authorize(ALL_ROLES)
    rows = store.ordered(store.freight_loads)
    dealer_id = request.args.get("dealer_id")
    if dealer_id:
        rows = [row for row in rows if row["dealer_id"] == dealer_id]
    return paginated(rows, serializers.freight_load)


@bp.get("/freight-loads/<row_id>")
def read_load(row_id):
    authorize(ALL_ROLES)
    return ok(serializers.freight_load(find_load(row_id)))


@bp.post("/freight-loads/<row_id>/assign-order")
def assign_order(row_id):
    authorize(("LogisticsCoordinator",))
    payload = body()
    order_id = req_str(payload, "dealer_order_id")

    load = find_load(row_id)
    order = find_order(order_id)

    if load["status"] != "PLANNED":
        raise ApiError("ERR_LOAD_STATE_INVALID")
    if order["dealer_id"] != load["dealer_id"]:
        raise ApiError("ERR_LOAD_DEALER_MISMATCH")

    attached = store.orders_on_load(load["id"])
    prospective = [row for row in attached if row["id"] != order["id"]] + [order]
    prospective_cube = rhu(sum((D(row["kit_cube_m3"]) for row in prospective), D(0)), 3)
    prospective_weight = rhu(sum((D(row["kit_weight_kg"]) for row in prospective), D(0)), 2)
    if prospective_cube > D(load["max_cube_m3"]) or prospective_weight > D(load["max_weight_kg"]):
        raise ApiError("ERR_LOAD_CAPACITY_EXCEEDED")

    if order["freight_load_id"] is not None:
        raise ApiError("ERR_ORDER_ALREADY_ON_LOAD")

    order["freight_load_id"] = load["id"]
    touch(order)
    services.recompute_load(load)
    touch(load)
    return ok(serializers.freight_load(load))


@bp.post("/freight-loads/<row_id>/dispatch")
def dispatch_load(row_id):
    authorize(("LogisticsCoordinator",))
    load = find_load(row_id)
    if load["status"] != "PLANNED":
        raise ApiError("ERR_LOAD_STATE_INVALID")

    attached = store.orders_on_load(load["id"])
    for order in attached:
        if order["production_status"] not in ("QUEUED", "KITTED"):
            raise ApiError("ERR_ORDER_STATE_INVALID")
    if not attached:
        raise ApiError("ERR_LOAD_HAS_NO_ORDERS")
    if load["trailer_type"] == "HIGH_CUBE_VAN":
        if D(load["cube_utilization_pct"]) < calc.MIN_CUBE_UTILIZATION_PCT:
            raise ApiError("ERR_LOAD_BELOW_MIN_CUBE_UTILIZATION")
    for order in attached:
        if order["financial_status"] != "DEPOSIT_PAID":
            raise ApiError("ERR_DEPOSIT_REQUIRED")

    load["status"] = "DISPATCHED"
    touch(load)
    for order in attached:
        order["production_status"] = "SHIPPED"
        touch(order)
    dealer = store.dealers.get(load["dealer_id"])
    if dealer is not None:
        services.recompute_staged_kit_count(dealer)
    return ok(serializers.freight_load(load))


@bp.post("/freight-loads/<row_id>/deliver")
def deliver_load(row_id):
    authorize(("LogisticsCoordinator",))
    load = find_load(row_id)
    if load["status"] != "DISPATCHED":
        raise ApiError("ERR_LOAD_STATE_INVALID")

    load["status"] = "DELIVERED"
    touch(load)
    for order in store.orders_on_load(load["id"]):
        if order["financial_status"] == "DEPOSIT_PAID":
            order["financial_status"] = "RELEASED"
        order["credit_hold_cents"] = 0
        touch(order)
    dealer = store.dealers.get(load["dealer_id"])
    if dealer is not None:
        services.recompute_dealer_ledger(dealer)
    return ok(serializers.freight_load(load))


@bp.post("/freight-loads/<row_id>/cancel")
def cancel_load(row_id):
    authorize(("LogisticsCoordinator",))
    load = find_load(row_id)
    if load["status"] != "PLANNED":
        raise ApiError("ERR_LOAD_STATE_INVALID")

    for order in store.orders_on_load(load["id"]):
        order["freight_load_id"] = None
        order["allocated_freight_cents"] = 0
        order["freight_sequence"] = None
        touch(order)
    load["status"] = "CANCELLED"
    services.recompute_load(load)
    touch(load)
    dealer = store.dealers.get(load["dealer_id"])
    if dealer is not None:
        services.recompute_staged_kit_count(dealer)
    return ok(serializers.freight_load(load))
