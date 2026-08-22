"""Trip and RidershipCount endpoints (PRD 3.4, 3.6, 3.7)."""

from flask import Blueprint

import calc
import store
from envelope import created, ok, paginate, pagination
from errors import ApiError
from guards import (ALL_ROLES, authorize, body, equality_filter, id_field,
                    minute_field, must_exist, validate_body)
from store import touch

bp = Blueprint("trips", __name__)

ASSIGN_SPEC = [id_field("vehicle_id"), id_field("driver_id")]
START_SPEC = [minute_field("actual_departure_min")]
COMPLETE_SPEC = [
    minute_field("actual_completion_min"),
    {"name": "boarded", "kind": "int", "min": 0},
    {"name": "alighted", "kind": "int", "min": 0},
    {"name": "ada_boardings", "kind": "int", "min": 0},
]
MISSED_SPEC = [{"name": "reason", "kind": "enum",
                "values": ("OPERATOR_FAULT", "CLIENT_REQUEST", "WEATHER")}]
RIDERSHIP_SPEC = [
    id_field("trip_id"),
    {"name": "boarded", "kind": "int", "min": 0},
    {"name": "alighted", "kind": "int", "min": 0},
    {"name": "ada_boardings", "kind": "int", "min": 0},
    {"name": "source", "kind": "enum", "values": ("DRIVER_TALLY", "APC_SENSOR")},
]


def _driver_ownership(caller, trip):
    """Ladder rung 4 — evaluated before request shape and path existence."""
    if caller.role != "DriverUser" or trip is None:
        return
    if trip["driver_id"] != caller.user_id:
        raise ApiError("ERR_DRIVER_NOT_ASSIGNED")


def _check_ada_subset(data):
    if data["ada_boardings"] > data["boarded"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'ada_boardings' may not exceed 'boarded'.")


# ------------------------------------------------------------------- reads
@bp.get("/trips/<tid>")
def get_trip(tid):
    authorize(ALL_ROLES)
    return ok(store.public(must_exist(store.trips, tid, "ERR_TRIP_NOT_FOUND")))


@bp.get("/trips")
def list_trips():
    authorize(ALL_ROLES)
    limit, offset = pagination()
    rows = list(store.trips.values())
    for param in ("route_id", "contract_id", "vehicle_id", "driver_id",
                  "service_date", "dispatch_status", "settlement_status"):
        rows = equality_filter(rows, param, param)
    rows.sort(key=lambda t: (t["service_date"], t["scheduled_departure_min"],
                             t["created_at"], t["_seq"]))
    return paginate(rows, limit, offset, store.public)


@bp.get("/trips/<tid>/ridership-counts")
def list_trip_ridership(tid):
    authorize(ALL_ROLES)
    limit, offset = pagination()
    trip = must_exist(store.trips, tid, "ERR_TRIP_NOT_FOUND")
    rows = [r for r in store.ridership_counts.values() if r["trip_id"] == trip["id"]]
    rows = equality_filter(rows, "source", "source")
    rows.sort(key=lambda r: r["sequence_no"])
    return paginate(rows, limit, offset, store.public)


# ------------------------------------------------------------------- dispatch
@bp.post("/trips/<tid>/assign")
def assign_trip(tid):
    authorize(["OpsPlanner"])
    data = validate_body(body(), ASSIGN_SPEC)
    trip = must_exist(store.trips, tid, "ERR_TRIP_NOT_FOUND")
    vehicle = must_exist(store.vehicles, data["vehicle_id"], "ERR_VEHICLE_NOT_FOUND")
    driver = must_exist(store.drivers, data["driver_id"], "ERR_DRIVER_NOT_FOUND")

    if trip["dispatch_status"] != "SCHEDULED":
        raise ApiError("ERR_TRIP_NOT_SCHEDULABLE")
    route = store.routes.get(trip["route_id"])
    if route is None or route["status"] not in ("PUBLISHED", "DEGRADED"):
        raise ApiError("ERR_ROUTE_NOT_PUBLISHED")
    if vehicle["status"] != "AVAILABLE":
        raise ApiError("ERR_VEHICLE_UNAVAILABLE")

    # rung 13 — an OPEN shop order overlapping the trip's closed interval
    for order in store.maintenance_orders.values():
        if order["vehicle_id"] != vehicle["id"] or order["status"] != "OPEN":
            continue
        if order["service_date"] != trip["service_date"]:
            continue
        if trip["scheduled_departure_min"] <= order["window_end_min"] and \
                order["window_start_min"] <= trip["scheduled_arrival_min"]:
            raise ApiError("ERR_VEHICLE_IN_MAINTENANCE_WINDOW")

    # rung 14 — ADA certification
    if vehicle["is_ada_accessible"] and not driver["ada_certified"]:
        raise ApiError("ERR_DRIVER_NOT_ADA_CERTIFIED")

    candidate_start = trip["scheduled_departure_min"]
    candidate_end = trip["scheduled_arrival_min"]

    # rung 18 — the vehicle's buffered block, half open at the far end
    for other in store.trips.values():
        if other["id"] == trip["id"] or other["vehicle_id"] != vehicle["id"]:
            continue
        if other["service_date"] != trip["service_date"]:
            continue
        if candidate_start < other["scheduled_arrival_min"] + calc.LAYOVER_BUFFER_MIN and \
                other["scheduled_departure_min"] < candidate_end + calc.LAYOVER_BUFFER_MIN:
            raise ApiError("ERR_VEHICLE_BLOCK_CONFLICT")

    # rung 19 — the driver's unbuffered interval
    for other in store.trips.values():
        if other["id"] == trip["id"] or other["driver_id"] != driver["id"]:
            continue
        if other["service_date"] != trip["service_date"]:
            continue
        if candidate_start < other["scheduled_arrival_min"] and \
                other["scheduled_departure_min"] < candidate_end:
            raise ApiError("ERR_DRIVER_BLOCK_CONFLICT")

    # rung 20 — the daily duty cap on the candidate trip's own service date
    committed = calc.driver_duty_minutes_on(driver["id"], trip["service_date"])
    if committed + (candidate_end - candidate_start) > driver["max_duty_minutes_per_day"]:
        raise ApiError("ERR_DRIVER_DUTY_EXCEEDED")

    # rung 28 — livery discipline
    if vehicle["branding_contract_id"] is not None and \
            vehicle["branding_contract_id"] != trip["contract_id"]:
        raise ApiError("ERR_VEHICLE_BRANDING_MISMATCH")

    trip["vehicle_id"] = vehicle["id"]
    trip["driver_id"] = driver["id"]
    trip["dispatch_status"] = "ASSIGNED"
    calc.recompute_vehicle_committed_block_minutes(vehicle)
    calc.recompute_driver_duty(driver)
    touch(trip)
    return ok(store.public(trip))


@bp.post("/trips/<tid>/unassign")
def unassign_trip(tid):
    authorize(["OpsPlanner"])
    trip = must_exist(store.trips, tid, "ERR_TRIP_NOT_FOUND")
    if trip["dispatch_status"] != "ASSIGNED":
        raise ApiError("ERR_TRIP_NOT_ASSIGNED")
    trip["dispatch_status"] = "SCHEDULED"
    calc.release_trip_bindings(trip)
    calc.revert_matched_requests_to_pending(trip)
    touch(trip)
    return ok(store.public(trip))


@bp.post("/trips/<tid>/start")
def start_trip(tid):
    caller = authorize(["DriverUser"])
    _driver_ownership(caller, store.trips.get(tid))
    data = validate_body(body(), START_SPEC)
    trip = must_exist(store.trips, tid, "ERR_TRIP_NOT_FOUND")
    if trip["dispatch_status"] != "ASSIGNED":
        raise ApiError("ERR_TRIP_NOT_ASSIGNED")
    trip["dispatch_status"] = "IN_SERVICE"
    trip["actual_departure_min"] = data["actual_departure_min"]
    touch(trip)
    return ok(store.public(trip))


@bp.post("/trips/<tid>/complete")
def complete_trip(tid):
    caller = authorize(["DriverUser"])
    _driver_ownership(caller, store.trips.get(tid))
    data = validate_body(body(), COMPLETE_SPEC)
    _check_ada_subset(data)
    trip = must_exist(store.trips, tid, "ERR_TRIP_NOT_FOUND")
    if trip["dispatch_status"] != "IN_SERVICE":
        raise ApiError("ERR_TRIP_NOT_IN_SERVICE")
    if trip["actual_departure_min"] is not None and \
            data["actual_completion_min"] < trip["actual_departure_min"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'actual_completion_min' may not precede "
                       "'actual_departure_min'.")
    trip["dispatch_status"] = "COMPLETED"
    trip["actual_completion_min"] = data["actual_completion_min"]
    calc.append_ridership_row(trip, data["boarded"], data["alighted"],
                              data["ada_boardings"], "DRIVER_TALLY", caller.user_id)
    calc.recompute_trip_counted_boardings(trip)
    touch(trip)
    return ok(store.public(trip))


@bp.post("/trips/<tid>/mark-missed")
def mark_trip_missed(tid):
    authorize(["OpsPlanner"])
    data = validate_body(body(), MISSED_SPEC)
    trip = must_exist(store.trips, tid, "ERR_TRIP_NOT_FOUND")
    if trip["dispatch_status"] not in ("SCHEDULED", "ASSIGNED"):
        raise ApiError("ERR_TRIP_NOT_SCHEDULABLE")

    was_assigned = trip["dispatch_status"] == "ASSIGNED"
    trip["dispatch_status"] = "MISSED"
    trip["missed_reason"] = data["reason"]
    if was_assigned:
        calc.release_trip_bindings(trip)
    touch(trip)

    contract = store.contracts.get(trip["contract_id"])
    if data["reason"] == "OPERATOR_FAULT":
        if trip["settlement_status"] == "UNBILLED":
            trip["settlement_status"] = "CREDITED"
            if contract is not None:
                calc.mint_credit_memo(contract, trip["id"], "MISSED_TRIP",
                                      contract["penalty_rate_cents_per_missed_trip"])
    elif data["reason"] == "CLIENT_REQUEST":
        if trip["settlement_status"] == "UNBILLED":
            trip["settlement_status"] = "WAIVED"

    calc.deny_matched_requests(trip)
    return ok(store.public(trip))


# ----------------------------------------------------------------- ridership
@bp.post("/ridership-counts")
def append_ridership():
    caller = authorize(["OpsPlanner", "DriverUser"])
    raw = body()
    if caller.role == "DriverUser":
        candidate = raw.get("trip_id")
        _driver_ownership(caller, store.trips.get(candidate)
                          if isinstance(candidate, str) else None)
    data = validate_body(raw, RIDERSHIP_SPEC)
    _check_ada_subset(data)
    trip = must_exist(store.trips, data["trip_id"], "ERR_TRIP_NOT_FOUND")
    row = calc.append_ridership_row(trip, data["boarded"], data["alighted"],
                                    data["ada_boardings"], data["source"],
                                    caller.user_id)
    calc.recompute_trip_counted_boardings(trip)
    return created(store.public(row))
