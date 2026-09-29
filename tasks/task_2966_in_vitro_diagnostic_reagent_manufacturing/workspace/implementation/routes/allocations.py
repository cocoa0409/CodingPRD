"""Reservations: shipping, cancellation and the cold chain (PRD 3.9)."""

from flask import Blueprint

import calc
import lookup
import recompute
import serialize
from errors import ApiError
from response import object_response
from store import create_row, db, now_clock, touch
from validation import (ALL_ROLES, Body, authenticate_and_authorize, json_body)

bp = Blueprint("allocations", __name__)

COLD_CHAIN_QUARANTINE_REASON = "Cold-chain excursion rejected the shipment."


def _order_of(allocation):
    return db.distribution_orders.get(allocation["distribution_order_id"])


@bp.get("/allocations/<allocation_id>")
def read_allocation(allocation_id):
    authenticate_and_authorize(ALL_ROLES)
    row = lookup.allocation(allocation_id)
    return object_response(serialize.allocation(row))


@bp.post("/allocations/<allocation_id>/ship")
def ship_allocation(allocation_id):
    authenticate_and_authorize(("DistributionPlanner",))
    json_body()
    allocation = lookup.allocation(allocation_id)
    lot = db.reagent_lots[allocation["reagent_lot_id"]]
    product = db.product_specifications[lot["product_specification_id"]]

    # Rung 60 - state preconditions on the reservation and on the drawn lot.
    if allocation["status"] != "RESERVED":
        raise ApiError("ERR_ALLOCATION_STATE_INVALID",
                       "A reservation in %s cannot be shipped."
                       % allocation["status"])
    if lot["distribution_status"] != "AVAILABLE":
        raise ApiError("ERR_REAGENT_LOT_STATE_INVALID",
                       "The drawn lot is %s." % lot["distribution_status"])

    # Rung 110 - remaining shelf life re-checked at the moment of shipment;
    # the boundary is inclusive.
    clock = now_clock()
    remaining = calc.remaining_shelf_life_days(lot, clock)
    if remaining is None or remaining < product["min_shelf_life_days_at_ship"]:
        raise ApiError("ERR_SHELF_LIFE_TOO_SHORT")

    allocation["status"] = "SHIPPED"
    allocation["shipped_at"] = clock
    touch(allocation)

    # The finished-goods ledger moves the units from allocated to shipped.
    recompute.reagent_lot_units(lot)
    touch(lot)

    # The parent order advances once no reservation of it is left RESERVED.
    order = _order_of(allocation)
    if order is not None:
        outstanding = [a for a in calc.allocation_rows(
            distribution_order_id=order["id"]) if a["status"] == "RESERVED"]
        if not outstanding and order["status"] in ("ALLOCATED",
                                                   "PARTIALLY_ALLOCATED"):
            order["status"] = "SHIPPED"
            touch(order)
    return object_response(serialize.allocation(allocation))


@bp.post("/allocations/<allocation_id>/cancel")
def cancel_allocation(allocation_id):
    authenticate_and_authorize(("DistributionPlanner",))
    body = Body(json_body())
    body.opt_str("reason")
    allocation = lookup.allocation(allocation_id)
    lot = db.reagent_lots[allocation["reagent_lot_id"]]

    # Rung 60 - state precondition.
    if allocation["status"] != "RESERVED":
        raise ApiError("ERR_ALLOCATION_STATE_INVALID",
                       "A reservation in %s cannot be cancelled."
                       % allocation["status"])

    allocation["status"] = "CANCELLED"
    touch(allocation)

    # A cancelled reservation counts towards none of the four ledger buckets,
    # so the lot's counters are restored exactly.
    recompute.reagent_lot_units(lot)
    touch(lot)

    order = _order_of(allocation)
    if order is not None:
        was_allocated = order["status"] == "ALLOCATED"
        recompute.order_rollup(order)
        if was_allocated and order["allocated_units"] < order["requested_units"]:
            order["status"] = "PARTIALLY_ALLOCATED"
        touch(order)
    return object_response(serialize.allocation(allocation))


@bp.post("/allocations/<allocation_id>/cold-chain-event")
def record_cold_chain_event(allocation_id):
    authenticate_and_authorize(("DistributionPlanner",))
    body = Body(json_body())
    excursion_minutes = body.req_number("excursion_minutes")
    max_temp_c = body.req_number("max_temp_c")
    delivery_confirmed = body.opt_bool("delivery_confirmed", False)
    allocation = lookup.allocation(allocation_id)
    lot = db.reagent_lots[allocation["reagent_lot_id"]]

    # Rung 60 - state precondition.
    if allocation["status"] != "SHIPPED":
        raise ApiError("ERR_ALLOCATION_STATE_INVALID",
                       "A reservation in %s cannot take a cold-chain event."
                       % allocation["status"])

    # The event itself is not an exposed aggregate; it only feeds the roll-up.
    create_row(db.cold_chain_events, {
        "allocation_id": allocation["id"],
        "excursion_minutes": excursion_minutes,
        "max_temp_c": max_temp_c,
        "delivery_confirmed": delivery_confirmed,
        "recorded_at": now_clock(),
    }, common=False)
    recompute.allocation_cold_chain(allocation)
    verdict = allocation["cold_chain_status"]

    ledger_moved = False
    if verdict == "EXCURSION_REJECTED":
        allocation["status"] = "QUARANTINED"
        allocation["quarantine_reason"] = COLD_CHAIN_QUARANTINE_REASON
        ledger_moved = True
    elif delivery_confirmed and verdict in ("INTACT", "EXCURSION_ACCEPTABLE"):
        allocation["status"] = "DELIVERED"
    touch(allocation)

    if ledger_moved:
        # The lot's shipped_units falls and its quarantined_units rises.
        recompute.reagent_lot_units(lot)
        touch(lot)

    order = _order_of(allocation)
    if order is not None:
        if ledger_moved:
            recompute.order_rollup(order)
            touch(order)
        elif allocation["status"] == "DELIVERED" and order["status"] == "SHIPPED":
            siblings = calc.allocation_rows(distribution_order_id=order["id"])
            if siblings and all(a["status"] == "DELIVERED" for a in siblings):
                order["status"] = "CLOSED"
                touch(order)
    return object_response(serialize.allocation(allocation))
