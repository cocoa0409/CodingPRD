"""Turn work orders: windows, capacity, cost waterfall and the departure cascade."""
from __future__ import annotations

from flask import Blueprint

import repo
import serializers
from db import mark_created, new_record, set_field, set_instant, store
from errors import ApiError
from middleware import endpoint
from response import created
from services import community as community_service, turn as turn_service
from validation import MISSING, bad, body, raw_id, req_enum, req_instant, req_int

bp = Blueprint("turns", __name__)

MIN_TECH_COUNT = 1
MAX_TECH_COUNT = 3


def _apply_costs(order, homesite):
    costs = turn_service.compute_costs(
        homesite, order["scope"], order["tech_count"],
        order["window_hours"], order["material_cost_cents"])
    for field, value in costs.items():
        set_field(order, field, value)


@bp.post("/turn-work-orders")
@endpoint("PropertyManager")
def open_turn_order():
    payload = body()
    homesite_ref = raw_id(payload, "homesite_id")
    homesite = repo.get_homesite(homesite_ref) if homesite_ref is not MISSING else None
    if homesite is None:
        raise bad("homesite_id is required")

    window_start = req_instant(payload, "window_start")
    window_end = req_instant(payload, "window_end")
    scope = req_enum(payload, "scope", turn_service.TURN_SCOPES)
    tech_count = req_int(payload, "tech_count", MIN_TECH_COUNT, MAX_TECH_COUNT)
    material_cost_cents = req_int(payload, "material_cost_cents", minimum=0)

    if homesite["status"] not in ("NOTICE_GIVEN", "IN_TURN"):
        raise ApiError("ERR_HOMESITE_NOT_IN_TURN")

    community = repo.community_of_homesite(homesite)
    siblings = repo.turn_orders_of_homesite(homesite)
    # The four rules are evaluated in exactly this order (PRD section 3.10).
    for other in siblings:
        if turn_service.overlaps(window_start, window_end,
                                 other["_window_start"], other["_window_end"]):
            raise ApiError("ERR_TURN_WINDOW_OVERLAP")
    hours = turn_service.window_hours(window_start, window_end)
    if (hours is None or hours > turn_service.MAX_WINDOW_HOURS
            or window_start < store.now()):
        raise ApiError("ERR_INVALID_TURN_WINDOW")
    for other in siblings:
        if other["scope"] != scope:
            continue
        if (window_start >= other["_window_end"]
                and window_start - other["_window_end"] < turn_service.REWORK_BUFFER):
            raise ApiError("ERR_TURN_REWORK_BUFFER")
    committed = turn_service.peak_tech_demand(community, window_start, window_end)
    if committed + tech_count > community["maintenance_tech_headcount"]:
        raise ApiError("ERR_TURN_CAPACITY_EXCEEDED")

    order = new_record("TurnWorkOrder", {
        "homesite_id": homesite["id"],
        "window_start": None,
        "window_end": None,
        "scope": scope,
        "tech_count": tech_count,
        "material_cost_cents": material_cost_cents,
        "window_hours": hours,
        "labor_cost_cents": 0,
        "total_turn_cost_cents": 0,
        "tenant_recoverable_cents": 0,
        "community_opex_cents": 0,
        "capital_reserve_cents": 0,
        "status": "SCHEDULED",
        "completed_at": None,
        "_completed_at": None,
    })
    store.turn_orders[order["id"]] = order
    mark_created(order)
    set_instant(order, "window_start", window_start)
    set_instant(order, "window_end", window_end)
    _apply_costs(order, homesite)

    # The departure cascade. A second scope on a home already in turn leaves the
    # home and the outgoing lease where they are.
    if homesite["status"] == "NOTICE_GIVEN":
        set_field(homesite, "status", "IN_TURN")
        for lease in repo.leases_of_homesite(homesite):
            if lease["lease_status"] == "ENDING":
                set_field(lease, "lease_status", "ENDED")
                community_service.recompute_household_of_lease(lease)
        community_service.recompute_community(community)
        community_service.apply_stabilization_revert(community)
    else:
        community_service.recompute_community(community)
    return created(serializers.turn_order, order)


@bp.post("/turn-work-orders/<identifier>/completion")
@endpoint("PropertyManager")
def complete_turn_order(identifier):
    order = repo.get_turn_order(identifier)
    homesite = repo.get_homesite(order["homesite_id"])
    community = repo.community_of_homesite(homesite)
    if order["status"] != "SCHEDULED" or store.now() < order["_window_start"]:
        raise ApiError("ERR_INVALID_TURN_STATE")

    set_field(order, "status", "COMPLETED")
    set_instant(order, "completed_at", store.now())
    # Recomputed against the recoverable cap in force at completion.
    _apply_costs(order, homesite)

    outstanding = [o for o in repo.turn_orders_of_homesite(homesite)
                   if o["id"] != order["id"] and o["status"] == "SCHEDULED"]
    if not outstanding and homesite["status"] == "IN_TURN":
        set_field(homesite, "status", "AVAILABLE")
        set_field(homesite, "turn_cycle_count", homesite["turn_cycle_count"] + 1)
        set_instant(homesite, "last_turn_ready_at", store.now())
    community_service.recompute_community(community)
    return created(serializers.turn_order, order)
