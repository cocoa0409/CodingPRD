"""Routes: CRUD, activate/suspend/reactivate/close with full cascades."""

from flask import Blueprint, request

import db
from common import (
    new_entity,
    get_or_404,
    body,
    require_field,
    require_positive_int,
    touch,
    new_id,
    logical_clock_iso,
)
from errors import ApiError
from middleware import require_role, require_any_authenticated
from response import ok, paginate

bp = Blueprint("routes", __name__)


def _get_route_or_404(route_id):
    return get_or_404(db.routes, route_id, "ERR_ROUTE_NOT_FOUND", "Route")


@bp.route("/routes", methods=["POST"])
def create_route():
    require_role("NetworkPlanner")
    data = body()
    origin_id = require_field(data, "origin_station_id", str)
    dest_id = require_field(data, "destination_station_id", str)
    base_fare = require_positive_int(data, "base_fare_cents", minimum=0)
    freq_cap = require_positive_int(data, "weekly_frequency_cap", minimum=1)

    origin = db.stations.get(origin_id)
    if origin is None:
        raise ApiError("ERR_STATION_NOT_FOUND", "Station id does not exist", 404)
    dest = db.stations.get(dest_id)
    if dest is None:
        raise ApiError("ERR_STATION_NOT_FOUND", "Station id does not exist", 404)
    if (
        origin["station_kind"] != "ORIGIN_SMALL_CITY"
        or dest["station_kind"] != "LEISURE_DESTINATION"
    ):
        raise ApiError(
            "ERR_ROUTE_ENDPOINT_KIND_MISMATCH",
            "Origin must be ORIGIN_SMALL_CITY and destination must be LEISURE_DESTINATION",
            422,
        )

    ent = new_entity(
        {
            "origin_station_id": origin_id,
            "destination_station_id": dest_id,
            "route_posture": "PLANNING",
            "base_fare_cents": base_fare,
            "weekly_frequency_cap": freq_cap,
            "suspended_seasons_count": 0,
        }
    )
    db.routes[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/routes", methods=["GET"])
def list_routes():
    require_any_authenticated()
    items = list(db.routes.values())
    posture = request.args.get("route_posture")
    if posture:
        items = [r for r in items if r["route_posture"] == posture]
    origin = request.args.get("origin_station_id")
    if origin:
        items = [r for r in items if r["origin_station_id"] == origin]
    dest = request.args.get("destination_station_id")
    if dest:
        items = [r for r in items if r["destination_station_id"] == dest]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/routes/<route_id>", methods=["GET"])
def get_route(route_id):
    require_any_authenticated()
    ent = _get_route_or_404(route_id)
    return ok(ent)


@bp.route("/routes/<route_id>/activate", methods=["POST"])
def activate_route(route_id):
    require_role("NetworkPlanner")
    route = _get_route_or_404(route_id)
    if route["route_posture"] != "PLANNING":
        raise ApiError(
            "ERR_ROUTE_NOT_PLANNING",
            "Route activation requires PLANNING posture",
            409,
        )
    has_open = any(
        w["route_id"] == route_id and w["window_status"] == "OPEN"
        for w in db.season_windows.values()
    )
    if not has_open:
        raise ApiError(
            "ERR_NO_OPEN_SEASON",
            "Activation requires at least one OPEN SeasonWindow",
            409,
        )
    route["route_posture"] = "SEASONAL_ACTIVE"
    touch(route)
    return ok(route)


def _cancel_flight(flight, disruption):
    """Move a flight to CANCELLED; strand confirmed bookings; release crew."""
    flight["flight_status"] = "CANCELLED"
    flight["cancelled_by_disruption_id"] = disruption["id"]
    touch(flight)

    stranded_until = _compute_stranded_until(flight)

    for booking in list(db.bookings.values()):
        if (
            booking["flight_instance_id"] == flight["id"]
            and booking["booking_status"] == "CONFIRMED"
        ):
            booking["booking_status"] = "STRANDED"
            booking["stranded_until_date"] = stranded_until
            booking["_stranded_by_disruption_id"] = disruption["id"]
            touch(booking)

    for assignment in list(db.crew_assignments.values()):
        if (
            assignment["flight_instance_id"] == flight["id"]
            and assignment["assignment_status"] == "ASSIGNED"
        ):
            assignment["assignment_status"] = "RELEASED"
            touch(assignment)


def _compute_stranded_until(cancelled_flight):
    """Next SCHEDULED flight on the same route, strictly later flight_date.

    Order by flight_date ASC, tie-break created_at ASC (never id).
    Returns the flight_date string or None.
    """
    candidates = [
        f
        for f in db.flight_instances.values()
        if f["route_id"] == cancelled_flight["route_id"]
        and f["flight_status"] == "SCHEDULED"
        and f["flight_date"] > cancelled_flight["flight_date"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda f: (f["flight_date"], f["created_at"]))
    return candidates[0]["flight_date"]


def _recompute_stranded_until_for_route(route_id):
    """Post-cascade pass: recompute stranded_until_date for every STRANDED
    booking on the route so no booking points at a cancelled rescue flight
    (PRD §3.6: cancelled and operated flights never count as candidates)."""
    for booking in db.bookings.values():
        if booking["booking_status"] != "STRANDED":
            continue
        flight = db.flight_instances.get(booking["flight_instance_id"])
        if flight is None or flight["route_id"] != route_id:
            continue
        recomputed = _compute_stranded_until(flight)
        if recomputed != booking.get("stranded_until_date"):
            booking["stranded_until_date"] = recomputed
            touch(booking)


def _freeze_publication(pub, reason_code="LOW_DEMAND"):
    """PUBLISHED -> FROZEN; cancel its SCHEDULED flights via disruptions."""
    if pub["publication_status"] != "PUBLISHED":
        return
    pub["publication_status"] = "FROZEN"
    touch(pub)
    flights = [
        f
        for f in db.flight_instances.values()
        if f["publication_id"] == pub["id"] and f["flight_status"] == "SCHEDULED"
    ]
    flights.sort(key=lambda f: (f["flight_date"], f["created_at"]))
    for flight in flights:
        dis = new_entity(
            {
                "route_id": pub["route_id"],
                "flight_instance_id": flight["id"],
                "reason_code": reason_code,
                "disruption_status": "DECLARED",
            }
        )
        db.disruption_events[dis["id"]] = dis
        _cancel_flight(flight, dis)


def _suspend_window(window, reason=None):
    """OPEN -> SUSPENDED; freeze publications; maybe suspend the route."""
    if window["window_status"] != "OPEN":
        return
    window["window_status"] = "SUSPENDED"
    if reason is not None:
        window["suspension_reason"] = reason
    touch(window)
    pubs = [
        p
        for p in db.schedule_publications.values()
        if p["season_window_id"] == window["id"]
        and p["publication_status"] == "PUBLISHED"
    ]
    pubs.sort(key=lambda p: (p["created_at"], p["id"]))
    for pub in pubs:
        _freeze_publication(pub)

    # Route auto-suspension: if no OPEN window remains, the route suspends.
    route = db.routes[window["route_id"]]
    any_open = any(
        w["route_id"] == route["id"] and w["window_status"] == "OPEN"
        for w in db.season_windows.values()
    )
    if not any_open and route["route_posture"] == "SEASONAL_ACTIVE":
        route["route_posture"] = "SEASONALLY_SUSPENDED"
        route["suspended_seasons_count"] = route.get("suspended_seasons_count", 0) + 1
        touch(route)

    _recompute_stranded_until_for_route(route["id"])


@bp.route("/routes/<route_id>/suspend", methods=["POST"])
def suspend_route(route_id):
    require_role("NetworkPlanner")
    route = _get_route_or_404(route_id)
    if route["route_posture"] != "SEASONAL_ACTIVE":
        raise ApiError(
            "ERR_ROUTE_NOT_ACTIVE",
            "Operation requires SEASONAL_ACTIVE route",
            409,
        )
    open_windows = [
        w
        for w in db.season_windows.values()
        if w["route_id"] == route_id and w["window_status"] == "OPEN"
    ]
    open_windows.sort(key=lambda w: (w["created_at"], w["id"]))
    for window in open_windows:
        window["window_status"] = "SUSPENDED"
        touch(window)
        pubs = [
            p
            for p in db.schedule_publications.values()
            if p["season_window_id"] == window["id"]
            and p["publication_status"] == "PUBLISHED"
        ]
        pubs.sort(key=lambda p: (p["created_at"], p["id"]))
        for pub in pubs:
            _freeze_publication(pub)
    route["route_posture"] = "SEASONALLY_SUSPENDED"
    route["suspended_seasons_count"] = route.get("suspended_seasons_count", 0) + 1
    touch(route)
    _recompute_stranded_until_for_route(route_id)
    return ok(route)


@bp.route("/routes/<route_id>/reactivate", methods=["POST"])
def reactivate_route(route_id):
    require_role("NetworkPlanner")
    route = _get_route_or_404(route_id)
    if route["route_posture"] != "SEASONALLY_SUSPENDED":
        raise ApiError(
            "ERR_ROUTE_NOT_SUSPENDED",
            "Reactivation requires SEASONALLY_SUSPENDED route",
            409,
        )
    has_open = any(
        w["route_id"] == route_id and w["window_status"] == "OPEN"
        for w in db.season_windows.values()
    )
    if not has_open:
        raise ApiError(
            "ERR_NO_OPEN_SEASON",
            "Reactivation requires at least one OPEN SeasonWindow",
            409,
        )
    route["route_posture"] = "SEASONAL_ACTIVE"
    touch(route)
    return ok(route)


@bp.route("/routes/<route_id>/close", methods=["POST"])
def close_route(route_id):
    require_role("NetworkPlanner")
    route = _get_route_or_404(route_id)
    if route["route_posture"] not in ("SEASONAL_ACTIVE", "SEASONALLY_SUSPENDED"):
        if route["route_posture"] == "PLANNING":
            raise ApiError(
                "ERR_ROUTE_NOT_ACTIVE",
                "Operation requires SEASONAL_ACTIVE route",
                409,
            )
        raise ApiError(
            "ERR_ROUTE_NOT_ACTIVE",
            "Operation requires SEASONAL_ACTIVE route",
            409,
        )
    live_flights = [
        f
        for f in db.flight_instances.values()
        if f["route_id"] == route_id and f["flight_status"] == "SCHEDULED"
    ]
    if live_flights:
        raise ApiError(
            "ERR_ROUTE_HAS_LIVE_FLIGHTS",
            "Close blocked: SCHEDULED flights remain",
            409,
        )
    live_bookings = [
        b
        for b in db.bookings.values()
        if b["booking_status"] in ("CONFIRMED", "STRANDED", "STRANDED_REBOOKED")
        and _booking_route_id(b) == route_id
    ]
    if live_bookings:
        raise ApiError(
            "ERR_ROUTE_HAS_LIVE_BOOKINGS",
            "Close blocked: non-cancelled bookings remain",
            409,
        )
    route["route_posture"] = "PERMANENTLY_CLOSED"
    touch(route)
    return ok(route)


def _booking_route_id(booking):
    flight = db.flight_instances.get(booking["flight_instance_id"])
    if flight is None:
        return None
    return flight["route_id"]
