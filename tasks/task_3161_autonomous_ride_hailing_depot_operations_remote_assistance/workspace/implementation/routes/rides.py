"""The ride lifecycle, its safety gates and its settlement arithmetic.

Matching is the most heavily guarded transition in the interface.  Its guards
are evaluated in the fixed order of PRD 3.7: authenticity, authorization,
existence, the safety cluster (posture, curb access), then the state gate, then
the optimistic-concurrency guard, then pool exhaustion.
"""

from flask import Blueprint, request

from db import store
from errors import fail
from middleware import (
    ANY,
    FLEET_OPERATIONS,
    REMOTE_ASSISTANCE_OPERATOR,
    SAFETY_REVIEWER,
    authenticate,
    authorize,
    body_object,
    get_or_404,
    optional_enum,
    require_int,
    require_str,
)
from response import paginate, success_array, success_object
from services import calculations as calc

bp = Blueprint("rides", __name__)

SUB_SERVICE_TYPES = ("STANDARD", "ASSISTED")
MANUAL_ONLY_REASONS = ("MOBILITY_ASSIST", "CHILD_SEAT", "NONE")
ROUTE_CLASSES = ("FREEWAY", "ARTERIAL", "RESIDENTIAL", "ALLEY")

_RIDE_READERS = (FLEET_OPERATIONS, REMOTE_ASSISTANCE_OPERATOR, SAFETY_REVIEWER)


def _resolve(allowed):
    caller = authenticate(request.headers)
    authorize(caller, allowed)
    return caller


# ─── RideRequest ──────────────────────────────────────────────────────────


@bp.post("/fleet/territories/<territory_id>/ride-requests")
def create_ride(territory_id):
    _resolve((FLEET_OPERATIONS,))
    get_or_404(store.territories, territory_id)
    body = body_object(request.get_json(silent=True))
    rider_name = require_str(body, "rider_name")
    sub_service_type = require_str(body, "sub_service_type")
    if sub_service_type not in SUB_SERVICE_TYPES:
        raise fail("ERR_INVALID_REQUEST")
    manual_only_reason = optional_enum(body, "manual_only_reason", MANUAL_ONLY_REASONS, None)
    idempotency_key = require_str(body, "idempotency_key")

    # Idempotent on the (territory_id, idempotency_key) pair.
    for existing in store.rides.values():
        if existing["territory_id"] == territory_id and existing["idempotency_key"] == idempotency_key:
            return success_object(existing, 201)

    ride = {
        "id": store.new_id(),
        "territory_id": territory_id,
        "rider_name": rider_name,
        "sub_service_type": sub_service_type,
        "manual_only_reason": manual_only_reason,
        "status": "REQUESTED",
        "vehicle_id": None,
        "pickup_location_id": None,
        "dropoff_location_id": None,
        "dispatch_attempts": 0,
        "idempotency_key": idempotency_key,
        "version": 1,
    }
    store.stamp_create(ride)
    store.rides[ride["id"]] = ride
    return success_object(ride, 201)


@bp.get("/fleet/territories/<territory_id>/ride-requests")
def list_territory_rides(territory_id):
    _resolve(_RIDE_READERS)
    get_or_404(store.territories, territory_id)
    rows = [row for row in store.rides.values() if row["territory_id"] == territory_id]
    rows = _filter_rides(rows, request.args)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/ride-requests")
def list_rides():
    _resolve((ANY,))
    rows = list(store.rides.values())
    territory_id = request.args.get("territory_id")
    if territory_id:
        rows = [row for row in rows if row["territory_id"] == territory_id]
    rows = _filter_rides(rows, request.args)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


def _filter_rides(rows, params):
    for param, field in (
        ("status", "status"),
        ("vehicle_id", "vehicle_id"),
        ("pickup_location_id", "pickup_location_id"),
        ("dropoff_location_id", "dropoff_location_id"),
    ):
        raw = params.get(param)
        if raw:
            rows = [row for row in rows if row.get(field) == raw]
    return rows


@bp.get("/fleet/ride-requests/<ride_id>")
def get_ride(ride_id):
    _resolve(_RIDE_READERS)
    return success_object(get_or_404(store.rides, ride_id))


@bp.get("/fleet/territories/<territory_id>/ride-requests/<ride_id>")
def get_territory_ride(territory_id, ride_id):
    _resolve(_RIDE_READERS)
    get_or_404(store.territories, territory_id)
    ride = get_or_404(store.rides, ride_id)
    if ride["territory_id"] != territory_id:
        raise fail("ERR_NOT_FOUND")
    return success_object(ride)


# ─── match ────────────────────────────────────────────────────────────────


@bp.post("/fleet/territories/<territory_id>/ride-requests/<ride_id>/match")
def match_ride(territory_id, ride_id):
    _resolve((FLEET_OPERATIONS,))
    territory = get_or_404(store.territories, territory_id)
    ride = get_or_404(store.rides, ride_id)
    if ride["territory_id"] != territory_id:
        raise fail("ERR_NOT_FOUND")
    body = body_object(request.get_json(silent=True))
    pickup_location_id = require_str(body, "pickup_location_id")
    expected_vehicle_version = require_int(body, "expected_vehicle_version")
    route_class = optional_enum(body, "route_class", ROUTE_CLASSES, None)

    # Precedence (PRD 3.7): territory posture first, then the safety cluster.
    if territory["posture"] != "ACTIVE":
        raise fail("ERR_TERRITORY_NOT_ACTIVE")

    location = store.pickup_locations.get(pickup_location_id)
    if location is None:
        raise fail("ERR_NOT_FOUND")
    if location["is_valid"] is not True:
        raise fail("ERR_LOCATION_INVALID")
    if not calc.curb_permitted(territory_id, location["curb_access"], ride["sub_service_type"]):
        raise fail("ERR_CURB_ACCESS_DENIED")

    if route_class is not None:
        if not calc.route_class_allowed(territory_id, route_class):
            raise fail("ERR_ROUTE_NOT_ALLOWED")
        if calc.exclusion_zone_covers(territory_id, route_class):
            raise fail("ERR_EXCLUSION_ZONE_ACTIVE")

    # The state gate masks the OCC guard and pool exhaustion.
    if ride["status"] != "REQUESTED":
        raise fail("ERR_INVALID_STATE")

    candidates = calc.vehicle_candidates(territory_id)
    if not candidates:
        raise fail("ERR_NO_VEHICLE_AVAILABLE")
    selected = candidates[0]

    if expected_vehicle_version != selected["version"]:
        raise fail("ERR_STALE_VERSION")

    ride["status"] = "MATCHED"
    ride["vehicle_id"] = selected["id"]
    ride["pickup_location_id"] = pickup_location_id
    store.touch(ride)

    # The territory pool is re-provisioned from the ride's window curve and the
    # matched vehicle is credited the per-ride amount (PRD 2.10 / 3.4).
    per_ride = calc.recompute_territory_credit(territory, _window_code(ride))
    selected["service_status"] = "DISPATCHED"
    selected["credit_cents"] = selected["credit_cents"] + per_ride
    store.touch(selected)
    return success_object(ride)


def _window_code(ride):
    """The demand window the ride is settled against."""
    signal = calc.demand_signal_for(ride["territory_id"], "MIDDAY")
    if signal is not None:
        return "MIDDAY"
    for window in calc.WINDOW_CODES:
        if calc.demand_signal_for(ride["territory_id"], window) is not None:
            return window
    return "MIDDAY"


# ─── pickup / complete ────────────────────────────────────────────────────


@bp.post("/fleet/territories/<territory_id>/ride-requests/<ride_id>/pickup")
def pickup_ride(territory_id, ride_id):
    _resolve((FLEET_OPERATIONS,))
    get_or_404(store.territories, territory_id)
    ride = get_or_404(store.rides, ride_id)
    if ride["territory_id"] != territory_id:
        raise fail("ERR_NOT_FOUND")
    body = body_object(request.get_json(silent=True))
    dropoff_location_id = require_str(body, "dropoff_location_id")
    expected_vehicle_version = require_int(body, "expected_vehicle_version")

    if ride["status"] != "MATCHED":
        raise fail("ERR_INVALID_STATE")

    location = store.pickup_locations.get(dropoff_location_id)
    if location is None:
        raise fail("ERR_NOT_FOUND")
    if location["is_valid"] is not True:
        raise fail("ERR_LOCATION_INVALID")
    if not calc.curb_permitted(territory_id, location["curb_access"], ride["sub_service_type"]):
        raise fail("ERR_CURB_ACCESS_DENIED")

    vehicle = store.vehicles[ride["vehicle_id"]]
    if expected_vehicle_version != vehicle["version"]:
        raise fail("ERR_STALE_VERSION")

    ride["status"] = "PICKED_UP"
    ride["dropoff_location_id"] = dropoff_location_id
    store.touch(ride)
    vehicle["service_status"] = "ON_TRIP"
    store.touch(vehicle)
    return success_object(ride)


@bp.post("/fleet/territories/<territory_id>/ride-requests/<ride_id>/complete")
def complete_ride(territory_id, ride_id):
    _resolve((FLEET_OPERATIONS,))
    get_or_404(store.territories, territory_id)
    ride = get_or_404(store.rides, ride_id)
    if ride["territory_id"] != territory_id:
        raise fail("ERR_NOT_FOUND")
    if ride["status"] != "PICKED_UP":
        raise fail("ERR_INVALID_STATE")

    vehicle = store.vehicles.get(ride["vehicle_id"])
    if vehicle is not None and vehicle["is_roadside_blocked"] is True:
        raise fail("ERR_VEHICLE_ROADSIDE_BLOCKED")

    ride["status"] = "COMPLETED"
    store.touch(ride)
    if vehicle is not None:
        calc.recompute_service_status(vehicle)
    return success_object(ride)


# ─── cancel / no-show ─────────────────────────────────────────────────────


@bp.post("/fleet/territories/<territory_id>/ride-requests/<ride_id>/cancel")
def cancel_ride(territory_id, ride_id):
    _resolve((FLEET_OPERATIONS,))
    get_or_404(store.territories, territory_id)
    ride = get_or_404(store.rides, ride_id)
    if ride["territory_id"] != territory_id:
        raise fail("ERR_NOT_FOUND")
    body = body_object(request.get_json(silent=True))
    credit_cents = require_int(body, "credit_cents", minimum=0)

    if ride["status"] not in ("REQUESTED", "MATCHED"):
        raise fail("ERR_INVALID_STATE")

    was_matched = ride["status"] == "MATCHED"
    vehicle = store.vehicles.get(ride["vehicle_id"]) if was_matched else None
    ride["status"] = "CANCELLED"
    store.touch(ride)
    if vehicle is not None:
        vehicle["credit_cents"] = max(0, vehicle["credit_cents"] - credit_cents)
        store.touch(vehicle)
        calc.recompute_service_status(vehicle, bump=False)
    return success_object(ride)


@bp.post("/fleet/territories/<territory_id>/ride-requests/<ride_id>/cancel-no-show")
def cancel_ride_no_show(territory_id, ride_id):
    _resolve((FLEET_OPERATIONS,))
    get_or_404(store.territories, territory_id)
    ride = get_or_404(store.rides, ride_id)
    if ride["territory_id"] != territory_id:
        raise fail("ERR_NOT_FOUND")
    if ride["status"] != "REQUESTED":
        raise fail("ERR_INVALID_STATE")
    ride["status"] = "CANCELLED_NO_SHOW"
    store.touch(ride)
    vehicle = store.vehicles.get(ride["vehicle_id"])
    if vehicle is not None:
        calc.recompute_service_status(vehicle)
    return success_object(ride)