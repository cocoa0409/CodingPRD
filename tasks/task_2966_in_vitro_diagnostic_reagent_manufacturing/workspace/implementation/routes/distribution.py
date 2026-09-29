"""Customer orders and the four-phase expiry-ordered allocation waterfall
(PRD 3.9)."""

from flask import Blueprint

import calc
import lookup
import recompute
import serialize
from errors import ApiError
from response import created_response, list_response, object_response
from store import create_row, db, now_clock, rows, touch
from validation import (ALL_ROLES, ALLOCATION_POLICIES, ALLOCATION_STATUSES,
                        Body, ORDER_STATUSES, authenticate_and_authorize,
                        enum_filter, json_body, pagination, paginate,
                        str_filter)

bp = Blueprint("distribution_orders", __name__)


@bp.post("/distribution-orders")
def create_distribution_order():
    user_id, _role = authenticate_and_authorize(("DistributionPlanner",))
    body = Body(json_body())
    spec_id = body.req_str("product_specification_id")
    customer_code = body.req_str("customer_code")
    requested_units = body.req_int("requested_units", gt=0)
    required_min_shelf_life_days = body.req_int("required_min_shelf_life_days", ge=0)
    ship_by = body.req_ts("ship_by")
    policy = body.opt_enum("allocation_policy", ALLOCATION_POLICIES, "FEFO_STRICT")

    # Rung 45 - body foreign keys.
    lookup.product_specification(spec_id)

    row = create_row(db.distribution_orders, {
        "product_specification_id": spec_id,
        "customer_code": customer_code,
        "requested_units": requested_units,
        "required_min_shelf_life_days": required_min_shelf_life_days,
        "ship_by": ship_by,
        "allocation_policy": policy,
        "allocated_units": 0,
        "shortfall_units": 0,
        "status": "DRAFT",
        "planner_user_id": user_id,
    })
    return created_response(serialize.distribution_order(row))


@bp.get("/distribution-orders/<order_id>")
def read_distribution_order(order_id):
    authenticate_and_authorize(ALL_ROLES)
    row = lookup.distribution_order(order_id)
    return object_response(serialize.distribution_order(row))


@bp.get("/distribution-orders")
def list_distribution_orders():
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    spec_id = str_filter("product_specification_id")
    status = enum_filter("status", ORDER_STATUSES)
    customer_code = str_filter("customer_code")
    items = rows(db.distribution_orders)
    if spec_id is not None:
        items = [r for r in items if r["product_specification_id"] == spec_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if customer_code is not None:
        items = [r for r in items if r["customer_code"] == customer_code]
    page = paginate(items, limit, offset)
    return list_response([serialize.distribution_order(r) for r in page],
                         limit, offset, len(items))


@bp.post("/distribution-orders/<order_id>/allocate")
def allocate_order(order_id):
    authenticate_and_authorize(("DistributionPlanner",))
    json_body()
    order = lookup.distribution_order(order_id)
    product = db.product_specifications[order["product_specification_id"]]

    # Rung 60 - state precondition.
    if order["status"] != "DRAFT":
        raise ApiError("ERR_ORDER_STATE_INVALID",
                       "An order in %s has already been allocated."
                       % order["status"])

    clock = now_clock()
    # Rung 108 - the ship-by deadline; the boundary instant still ships.
    if order["ship_by"] < clock:
        raise ApiError("ERR_SHIP_BY_PASSED")

    # Rung 130 - product clearance.
    if product["clearance_status"] != "CLEARED":
        raise ApiError("ERR_PRODUCT_NOT_CLEARED")

    floor_days = max(order["required_min_shelf_life_days"],
                     product["min_shelf_life_days_at_ship"])

    # Phase 1 - the candidate set.
    pool = []
    for lot in rows(db.reagent_lots):
        if lot["product_specification_id"] != order["product_specification_id"]:
            continue
        if lot["disposition_status"] != "RELEASED":
            continue
        if lot["distribution_status"] != "AVAILABLE":
            continue
        if lot["available_units"] <= 0:
            continue
        remaining = calc.remaining_shelf_life_days(lot, clock)
        if remaining is None or remaining < floor_days:
            continue
        pool.append(lot)

    # Phase 2 - first-expiry-first-out, created_at ascending as the tie-break.
    pool.sort(key=lambda row: (row["expiry_date"], row["created_at"], row["_seq"]))

    # Phase 3 - the dry-run draw against an in-memory copy of the counters.
    need = order["requested_units"]
    draws = []
    for lot in pool:
        if need <= 0:
            break
        take = min(need, lot["available_units"])
        if take <= 0:
            continue
        draws.append((lot, take, len(draws) + 1))
        need -= take

    # Phase 4 - the policy gate, then persistence.
    if need > 0 and order["allocation_policy"] == "FEFO_STRICT":
        raise ApiError("ERR_ALLOCATION_SHORTFALL")

    touched_lots = []
    for lot, take, sequence_index in draws:
        create_row(db.allocations, {
            "distribution_order_id": order["id"],
            "reagent_lot_id": lot["id"],
            "allocated_units": take,
            "sequence_index": sequence_index,
            "status": "RESERVED",
            "shipped_at": None,
            "cumulative_excursion_minutes": calc.rhu(0, 2),
            "max_excursion_temp_c": None,
            "cold_chain_status": "INTACT",
            "quarantine_reason": None,
        })
        if lot not in touched_lots:
            touched_lots.append(lot)
    for lot in touched_lots:
        recompute.reagent_lot_units(lot)
        touch(lot)

    recompute.order_rollup(order)
    order["status"] = "ALLOCATED" if need <= 0 else "PARTIALLY_ALLOCATED"
    touch(order)
    return object_response(serialize.distribution_order(order))


@bp.get("/distribution-orders/<order_id>/allocations")
def list_order_allocations(order_id):
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", ALLOCATION_STATUSES)
    order = lookup.distribution_order(order_id)
    items = calc.allocation_rows(distribution_order_id=order["id"])
    if status is not None:
        items = [r for r in items if r["status"] == status]
    # The reservations are listed in their draw sequence.
    items = sorted(items, key=lambda row: (row["sequence_index"], row["_seq"]))
    page = paginate(items, limit, offset)
    return list_response([serialize.allocation(r) for r in page],
                         limit, offset, len(items))
