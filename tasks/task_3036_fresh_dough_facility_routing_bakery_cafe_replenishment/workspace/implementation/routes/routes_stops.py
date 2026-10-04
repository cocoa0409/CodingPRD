"""Delivery routes and route stops (PRD 3.5 / 3.6)."""

import datetime

from flask import Blueprint, request

import db
import response as resp
import services
import validators as V
from errors import ApiError
from middleware import authorize, ALL_ROLES, ROLE_ROUTE_DISPATCHER

bp = Blueprint("routes_stops", __name__)


# ---------------------------------------------------------------------------
# DeliveryRoute
# ---------------------------------------------------------------------------
@bp.route("/dough-ops/facilities/<facility_id>/routes", methods=["POST"])
def create_route(facility_id):
    authorize(ROLE_ROUTE_DISPATCHER)
    services.get_or_404(db.facilities, facility_id, "Facility")
    data = V.body_json(request)
    production_date = V.req_date(data, "production_date")
    capacity = V.req_int(data, "vehicle_capacity_units", minimum=1)
    row = db.common_fields()
    row.update({
        "facility_id": facility_id,
        "production_date": production_date,
        "status": "DRAFT",
        "vehicle_capacity_units": capacity,
    })
    db.delivery_routes[row["id"]] = row
    return resp.object_response(resp.serialize(row), 201)


@bp.route("/dough-ops/facilities/<facility_id>/routes", methods=["GET"])
def list_routes(facility_id):
    authorize(*ALL_ROLES)
    services.get_or_404(db.facilities, facility_id, "Facility")
    production_date = request.args.get("production_date")
    status = request.args.get("status")
    rows = [r for r in db.delivery_routes.values()
            if r["facility_id"] == facility_id
            and (production_date is None or r["production_date"] == production_date)
            and (status is None or r["status"] == status)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/routes", methods=["GET"])
def list_routes_flat():
    authorize(*ALL_ROLES)
    facility_id = request.args.get("facility_id")
    production_date = request.args.get("production_date")
    status = request.args.get("status")
    rows = [r for r in db.delivery_routes.values()
            if (facility_id is None or r["facility_id"] == facility_id)
            and (production_date is None or r["production_date"] == production_date)
            and (status is None or r["status"] == status)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/routes/<route_id>", methods=["GET"])
def get_route(route_id):
    authorize(*ALL_ROLES)
    row = services.get_or_404(db.delivery_routes, route_id, "Route")
    return resp.object_response(resp.serialize(row), 200)


def _get_route_under_facility(facility_id, route_id):
    services.get_or_404(db.facilities, facility_id, "Facility")
    route = services.get_or_404(db.delivery_routes, route_id, "Route")
    if route["facility_id"] != facility_id:
        raise ApiError("ERR_NOT_FOUND", "Route not found under this facility.")
    return route


@bp.route("/dough-ops/facilities/<facility_id>/routes/<route_id>/publish", methods=["POST"])
def publish_route(facility_id, route_id):
    authorize(ROLE_ROUTE_DISPATCHER)
    route = _get_route_under_facility(facility_id, route_id)
    if route["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT route may be published.")
    stops = services.route_stops(route)
    if not stops:
        raise ApiError("ERR_INVALID_STATE", "A route needs at least one stop to publish.")
    load = sum(s["planned_units"] for s in stops)
    if load > route["vehicle_capacity_units"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", "The stop load exceeds the vehicle capacity.")
    route["status"] = "PUBLISHED"
    db.touch(route)
    return resp.object_response(resp.serialize(route), 200)


@bp.route("/dough-ops/facilities/<facility_id>/routes/<route_id>/depart", methods=["POST"])
def depart_route(facility_id, route_id):
    authorize(ROLE_ROUTE_DISPATCHER)
    route = _get_route_under_facility(facility_id, route_id)
    if route["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", "Only a PUBLISHED route may depart.")
    route["status"] = "IN_TRANSIT"
    db.touch(route)
    return resp.object_response(resp.serialize(route), 200)


@bp.route("/dough-ops/facilities/<facility_id>/routes/<route_id>/cancel", methods=["POST"])
def cancel_route(facility_id, route_id):
    authorize(ROLE_ROUTE_DISPATCHER)
    route = _get_route_under_facility(facility_id, route_id)
    if route["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT or PUBLISHED route may be cancelled.")
    route["status"] = "CANCELLED"
    db.touch(route)

    # Cascade: every stop -> CANCELLED; every order on those stops -> CANCELLED
    # with billing forced to CREDITED (zero invoice, balance unchanged).
    for stop in services.route_stops(route):
        if stop["status"] != "CANCELLED":
            stop["status"] = "CANCELLED"
            db.touch(stop)
        for order in db.cafe_orders.values():
            if (order["cafe_id"] == stop["cafe_id"]
                    and order["production_date"] == route["production_date"]
                    and order["status"] in ("DRAFT", "SUBMITTED", "LOCKED", "PLANNED", "ROUTED")):
                order["status"] = "CANCELLED"
                order["billing_status"] = "CREDITED"
                db.touch(order)
                plan_id = order.get("_plan_id")
                if plan_id and plan_id in db.production_plans:
                    services.recompute_plan_totals(db.production_plans[plan_id])
                    db.touch(db.production_plans[plan_id])
    return resp.object_response(resp.serialize(route), 200)


# ---------------------------------------------------------------------------
# RouteStop
# ---------------------------------------------------------------------------
def _window_minutes(window_start_local, window_end_local):
    return services.hhmm_minutes(window_start_local), services.hhmm_minutes(window_end_local)


def _check_window_membership(planned_arrival, window_start_local, window_end_local):
    """The planned arrival must fall inside the half-open window (start, end]."""
    start_min, end_min = _window_minutes(window_start_local, window_end_local)
    minute = planned_arrival.hour * 60 + planned_arrival.minute
    if end_min <= start_min:
        # Window wraps midnight: (start, 24:00] or [00:00, end]
        in_window = minute > start_min or minute <= end_min
    else:
        in_window = start_min < minute <= end_min
    if not in_window:
        raise ApiError("ERR_STOP_WINDOW_VIOLATION",
                       "The planned arrival falls outside the cafe's receiving window.")


def _check_same_cafe_window_gap(route, cafe_id, window_start_local, window_end_local):
    """Two stops on one cafe must not have overlapping windows with zero gap."""
    start_min, end_min = _window_minutes(window_start_local, window_end_local)
    for other in services.route_stops(route):
        if other["cafe_id"] != cafe_id or other["status"] == "CANCELLED":
            continue
        o_start, o_end = _window_minutes(other["window_start_local"], other["window_end_local"])
        # Required: the new window opens strictly after the other's close, or
        # closes strictly before the other's open. Equality (zero gap) rejects.
        if start_min > o_end or end_min < o_start:
            continue
        raise ApiError("ERR_STOP_WINDOW_VIOLATION",
                       "Two stops on the same cafe may not have touching or overlapping windows.")


@bp.route("/dough-ops/facilities/<facility_id>/routes/<route_id>/stops", methods=["POST"])
def create_route_stop(facility_id, route_id):
    authorize(ROLE_ROUTE_DISPATCHER)
    route = _get_route_under_facility(facility_id, route_id)
    data = V.body_json(request)
    seq = V.req_int(data, "seq", minimum=1)
    cafe_id = data.get("cafe_id")
    planned_arrival = V.req_instant(data, "planned_arrival")
    window_start = V.req_hhmm(data, "window_start_local")
    window_end = V.req_hhmm(data, "window_end_local")
    planned_units = V.req_int(data, "planned_units", minimum=1)
    if not isinstance(cafe_id, str) or cafe_id not in db.cafes:
        raise ApiError("ERR_NOT_FOUND", "Cafe not found.")
    if route["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Stops may only be added to a DRAFT route.")
    for other in services.route_stops(route):
        if other["seq"] == seq:
            raise ApiError("ERR_DUPLICATE", "A stop with this seq already exists on the route.")
    _check_window_membership(planned_arrival, window_start, window_end)
    _check_same_cafe_window_gap(route, cafe_id, window_start, window_end)

    row = db.common_fields()
    row.update({
        "route_id": route_id,
        "seq": seq,
        "cafe_id": cafe_id,
        "planned_arrival": data.get("planned_arrival"),
        "window_start_local": window_start,
        "window_end_local": window_end,
        "status": "SCHEDULED",
        "actual_arrival": None,
        "planned_units": planned_units,
        "loaded_units": None,
    })
    db.route_stops[row["id"]] = row
    return resp.object_response(resp.serialize(row), 201)


@bp.route("/dough-ops/facilities/<facility_id>/routes/<route_id>/stops", methods=["GET"])
def list_route_stops(facility_id, route_id):
    authorize(*ALL_ROLES)
    _get_route_under_facility(facility_id, route_id)
    cafe_id = request.args.get("cafe_id")
    status = request.args.get("status")
    rows = [r for r in db.route_stops.values()
            if r["route_id"] == route_id
            and (cafe_id is None or r["cafe_id"] == cafe_id)
            and (status is None or r["status"] == status)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/route-stops", methods=["GET"])
def list_route_stops_flat():
    authorize(*ALL_ROLES)
    route_id = request.args.get("route_id")
    cafe_id = request.args.get("cafe_id")
    status = request.args.get("status")
    rows = [r for r in db.route_stops.values()
            if (route_id is None or r["route_id"] == route_id)
            and (cafe_id is None or r["cafe_id"] == cafe_id)
            and (status is None or r["status"] == status)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/route-stops/<stop_id>", methods=["GET"])
def get_route_stop(stop_id):
    authorize(*ALL_ROLES)
    row = services.get_or_404(db.route_stops, stop_id, "Route stop")
    return resp.object_response(resp.serialize(row), 200)


@bp.route("/dough-ops/facilities/<facility_id>/routes/<route_id>/stops/<stop_id>/arrive",
          methods=["POST"])
def arrive_route_stop(facility_id, route_id, stop_id):
    authorize(ROLE_ROUTE_DISPATCHER)
    route = _get_route_under_facility(facility_id, route_id)
    stop = services.get_or_404(db.route_stops, stop_id, "Route stop")
    if stop["route_id"] != route_id:
        raise ApiError("ERR_NOT_FOUND", "Route stop not found under this route.")
    # Priority 5: state gates.
    if route["status"] != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_STATE", "Arrivals require an IN_TRANSIT route.")
    if stop["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED stop may record an arrival.")
    # In-order arrival: every earlier-seq stop must be terminal.
    for other in services.route_stops(route):
        if other["seq"] < stop["seq"] and other["status"] not in services.TERMINAL_STOP_STATES:
            raise ApiError("ERR_INVALID_STATE",
                           "Earlier stops on the route have not reached a terminal state.")

    data = V.body_json(request)
    loaded = data.get("loaded_units")
    if loaded is not None:
        if isinstance(loaded, bool) or not isinstance(loaded, int) or loaded < 0:
            raise ApiError("ERR_VALIDATION", "Field 'loaded_units' must be a non-negative integer.")

    now = db.now_dt()
    planned = V.parse_instant(stop["planned_arrival"], "planned_arrival")
    start_min, end_min = _window_minutes(stop["window_start_local"], stop["window_end_local"])

    # Window auto-resolution (PRD 3.6).
    if now.date() > planned.date():
        outcome = "MISSED"
    elif now.date() < planned.date():
        raise ApiError("ERR_STOP_WINDOW_VIOLATION",
                       "The arrival precedes the planned delivery day.")
    else:
        minute = now.hour * 60 + now.minute
        if end_min > start_min:
            if minute <= start_min:
                raise ApiError("ERR_STOP_WINDOW_VIOLATION",
                               "The arrival is at or before the window's open bound.")
            outcome = "ON_TIME" if minute <= end_min else "LATE"
        else:
            # Window wraps midnight.
            if minute > start_min:
                outcome = "ON_TIME"
            elif minute <= end_min:
                outcome = "ON_TIME"
            else:
                outcome = "LATE"

    stop["actual_arrival"] = db.fmt_instant(now)
    stop["loaded_units"] = loaded if loaded is not None else stop["planned_units"]
    stop["status"] = outcome
    db.touch(stop)

    # Deliver the stop's orders; shortage on a no-substitution dough ships short.
    orders = services.stop_orders(stop)
    total_planned = sum(o["adjusted_quantity"] for o in orders)
    remaining = stop["loaded_units"]
    shortage = remaining < total_planned
    for order in orders:
        planned_qty = order["adjusted_quantity"]
        allocated = min(remaining, planned_qty)
        remaining -= allocated
        dough_type = db.dough_types[order["dough_type_id"]]
        if not shortage or allocated >= planned_qty:
            order["status"] = "DELIVERED"
            order["actual_quantity"] = planned_qty
        elif dough_type["substitution_allowed"]:
            # Substitution fills the gap; the line ships whole.
            order["status"] = "DELIVERED"
            order["actual_quantity"] = planned_qty
        else:
            order["status"] = "SHIPPED_SHORT"
            order["actual_quantity"] = allocated
        db.touch(order)
        plan_id = order.get("_plan_id")
        if plan_id and plan_id in db.production_plans:
            services.recompute_plan_totals(db.production_plans[plan_id])
            db.touch(db.production_plans[plan_id])

    services.maybe_complete_route(route)
    return resp.object_response(resp.serialize(stop), 200)
