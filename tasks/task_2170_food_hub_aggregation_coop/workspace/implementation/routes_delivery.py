"""Refrigerated delivery routes, exclusive stop windows and dispatch."""

from flask import Blueprint

import domain
import fetch
import serializers
from constants import ROLE_BUYER, ROLE_HUB_ADMIN, STORAGE_CLASSES
from envelope import ok
from errors import ApiError
from store import add_minutes, base_record, db, touch
from validators import (body, endpoint, req_datetime, req_enum, req_int,
                        req_string)

bp = Blueprint("delivery", __name__)


@bp.post("/delivery-routes")
@endpoint([ROLE_HUB_ADMIN])
def create_route():
    payload = body()
    route_date = req_datetime(payload, "route_date")
    vehicle_code = req_string(payload, "vehicle_code", min_len=1, max_len=12)
    storage_class = req_enum(payload, "storage_class", STORAGE_CLASSES)
    pallet_capacity = req_int(payload, "pallet_capacity", minimum=1)
    depot_departure_at = req_datetime(payload, "depot_departure_at")

    route = base_record({
        "route_date": route_date,
        "vehicle_code": vehicle_code,
        "storage_class": storage_class,
        "pallet_capacity": pallet_capacity,
        "depot_departure_at": depot_departure_at,
        "pallets_loaded": 0,
        "stop_count": 0,
        "status": "PLANNED",
    })
    db.routes[route["id"]] = route
    return ok(serializers.route_out(route), 201)


@bp.get("/delivery-routes/<route_id>")
@endpoint([ROLE_HUB_ADMIN, ROLE_BUYER])
def read_route(route_id):
    route = fetch.get("route", route_id)
    return ok(serializers.route_out(route))


@bp.post("/delivery-routes/<route_id>/stops")
@endpoint([ROLE_HUB_ADMIN])
def add_stop(route_id):
    route = fetch.get("route", route_id)                          # rung 4
    payload = body()
    order = fetch.body_fk(payload, "order_id", "order")           # rung 5

    # rung 6
    req_string(payload, "order_id")
    sequence_no = req_int(payload, "sequence_no")
    planned_arrival_at = req_datetime(payload, "planned_arrival_at")
    service_minutes = req_int(payload, "service_minutes")
    expected_version = req_int(payload, "expected_route_version")

    # rung 9
    if expected_version != route["version"]:
        raise ApiError("ERR_STALE_ROUTE_VERSION")

    # rung 10
    if order["fulfillment_status"] != "AGGREGATED":
        raise ApiError("ERR_INVALID_ORDER_STATE")

    # rung 15 — one vehicle runs at one temperature
    for line in domain.order_lines(order["id"]):
        if line["storage_class"] != route["storage_class"]:
            raise ApiError("ERR_STORAGE_CLASS_MISMATCH")

    # rung 18 — a zero-length stop is not a stop
    if service_minutes < 1:
        raise ApiError("ERR_INVALID_WINDOW")

    new_start = planned_arrival_at
    new_end = add_minutes(planned_arrival_at, service_minutes)

    # rung 22 — exclusive service window; back-to-back stops are legal
    for other in domain.route_orders(route["id"]):
        if other["id"] == order["id"]:
            continue
        if other["planned_arrival_at"] is None or other["service_minutes"] is None:
            continue
        other_start = other["planned_arrival_at"]
        other_end = add_minutes(other_start, other["service_minutes"])
        if other_start < new_end and new_start < other_end:
            raise ApiError("ERR_STOP_WINDOW_OVERLAP")

    # rung 23 — vehicle pallet capacity
    domain.refresh_route_counts(route)
    if route["pallets_loaded"] + order["order_pallets"] > route["pallet_capacity"]:
        raise ApiError("ERR_ROUTE_CAPACITY_EXCEEDED")

    order["route_id"] = route["id"]
    order["route_sequence_no"] = sequence_no
    order["planned_arrival_at"] = planned_arrival_at
    order["service_minutes"] = service_minutes
    order["fulfillment_status"] = "SCHEDULED"
    touch(order)

    domain.refresh_route_counts(route)
    touch(route)

    return ok(serializers.order_out(order), 201)


@bp.post("/delivery-routes/<route_id>/dispatch")
@endpoint([ROLE_HUB_ADMIN])
def dispatch_route(route_id):
    route = fetch.get("route", route_id)                          # rung 4

    # rung 10 / rung 24 — a route still PLANNED because something is unstaged
    # is reported as ERR_ALLOCATIONS_NOT_STAGED
    if route["status"] != "LOADED":
        if route["status"] == "PLANNED":
            for order in domain.route_orders(route["id"]):
                for alloc in domain.order_allocations(order["id"]):
                    if alloc["status"] == "RESERVED":
                        raise ApiError("ERR_ALLOCATIONS_NOT_STAGED")
        raise ApiError("ERR_INVALID_ROUTE_STATE")

    # rung 23 — dispatch re-checks the load
    domain.refresh_route_counts(route)
    if route["pallets_loaded"] > route["pallet_capacity"]:
        raise ApiError("ERR_ROUTE_CAPACITY_EXCEEDED")

    route["status"] = "DISPATCHED"
    touch(route)
    for order in domain.route_orders(route["id"]):
        if order["fulfillment_status"] == "SCHEDULED":
            order["fulfillment_status"] = "IN_TRANSIT"
            touch(order)

    return ok(serializers.route_out(route))
