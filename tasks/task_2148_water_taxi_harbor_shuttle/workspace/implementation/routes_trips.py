"""Trips, berth reservations and the movement operations — PRD 3.3, 3.4, 3.7."""

from flask import Blueprint

import calc
import cascades
import serialize
import validation as v
from auth import require
from envelope import (created, ok, ok_list, read_pagination, paginate,
                      enum_param, str_param)
from errors import ApiError
from store import store, iso_instant, parse_date

bp = Blueprint("trips", __name__)


def resolve_body_fk(body, key, table, error_id):
    candidate = v.fk_candidate(body, key)
    if candidate is None:
        return None
    row = table.get(candidate)
    if row is None:
        raise ApiError(error_id, "No resource with id %s." % candidate)
    return row


def find_trip(trip_id):
    row = store.trips.get(trip_id)
    if row is None:
        raise ApiError("ERR_TRIP_NOT_FOUND", "No trip with id %s." % trip_id)
    return row


def find_slot(slot_id):
    row = store.dock_slots.get(slot_id)
    if row is None:
        raise ApiError("ERR_DOCK_SLOT_NOT_FOUND", "No dock slot with id %s." % slot_id)
    return row


def _require_master(actor, trip):
    if actor.user_id != trip["master_crew_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the trip's own master may perform this operation.")


def _day_of(trip):
    return store.service_days.get(trip["service_day_id"])


# ------------------------------------------------------------------ trips

@bp.post("/harbor/trips")
def create_trip():
    require("Dispatcher")
    body = v.body()

    # rung 4 — body foreign keys, in the endpoint's declared field order
    day = resolve_body_fk(body, "service_day_id", store.service_days,
                          "ERR_SERVICE_DAY_NOT_FOUND")
    vessel = resolve_body_fk(body, "vessel_id", store.vessels, "ERR_VESSEL_NOT_FOUND")
    crew = resolve_body_fk(body, "master_crew_id", store.crew, "ERR_CREW_NOT_FOUND")
    origin = resolve_body_fk(body, "origin_stop_id", store.stops, "ERR_STOP_NOT_FOUND")
    destination = resolve_body_fk(body, "destination_stop_id", store.stops,
                                  "ERR_STOP_NOT_FOUND")

    # rung 6 — payload validity
    v.get_string(body, "service_day_id", min_len=1)
    v.get_string(body, "vessel_id", min_len=1)
    v.get_string(body, "master_crew_id", min_len=1)
    v.get_string(body, "origin_stop_id", min_len=1)
    v.get_string(body, "destination_stop_id", min_len=1)
    service_mode = v.get_enum(body, "service_mode", ("SCHEDULED", "ON_DEMAND"))
    departure_raw, departure_dt = v.get_utc_instant(body, "scheduled_departure_utc")
    arrival_raw, arrival_dt = v.get_utc_instant(body, "scheduled_arrival_utc")

    # rung 7 — time windows
    if arrival_dt <= departure_dt:
        raise ApiError("ERR_INVALID_TIME_WINDOW",
                       "scheduled_arrival_utc must be strictly after scheduled_departure_utc.")

    # rung 8 — distinct endpoints
    if origin["id"] == destination["id"]:
        raise ApiError("ERR_SAME_ORIGIN_DESTINATION",
                       "origin_stop_id and destination_stop_id must differ.")

    # rung 13 — vessel availability against the closed-closed layup window
    if calc.vessel_layup_conflict(vessel, departure_dt, arrival_dt):
        raise ApiError("ERR_VESSEL_IN_LAYUP",
                       "The trip window overlaps the vessel's layup window.")

    row = store.new_row()
    row.update({
        "service_day_id": day["id"],
        "vessel_id": vessel["id"],
        "master_crew_id": crew["id"],
        "origin_stop_id": origin["id"],
        "destination_stop_id": destination["id"],
        "service_mode": service_mode,
        "scheduled_departure_utc": departure_raw,
        "scheduled_arrival_utc": arrival_raw,
        "_departure_dt": departure_dt,
        "_arrival_dt": arrival_dt,
        "actual_departure_utc": None,
        "actual_arrival_utc": None,
        "_actual_departure_dt": None,
        "seats_committed": 0,
        "booked_pax": 0,
        "boarded_pax": 0,
        "operational_status": "SCHEDULED",
        "settlement_status": "UNSETTLED",
        "provisional_fee_cents": 0,
        "final_fee_cents": 0,
        "cancellation_reason": None,
    })
    store.trips[row["id"]] = row
    return created(serialize.trip(row))


@bp.get("/harbor/trips/<trip_id>")
def read_trip(trip_id):
    require("HarborAdmin", "Dispatcher", "VesselMaster", "Rider", "FareAuditor")
    return ok(serialize.trip(find_trip(trip_id)))


@bp.get("/harbor/trips")
def list_trips():
    require("HarborAdmin", "Dispatcher", "VesselMaster", "Rider", "FareAuditor")
    limit, offset = read_pagination()
    filters = {
        "service_day_id": str_param("service_day_id"),
        "vessel_id": str_param("vessel_id"),
        "master_crew_id": str_param("master_crew_id"),
        "origin_stop_id": str_param("origin_stop_id"),
        "destination_stop_id": str_param("destination_stop_id"),
    }
    operational = enum_param("operational_status",
                             ("SCHEDULED", "BOARDING", "DEPARTED", "COMPLETED", "CANCELLED"))
    settlement = enum_param("settlement_status",
                            ("UNSETTLED", "PROVISIONAL", "FINAL", "VOID"))
    rows = []
    for trip in store.trips.values():
        if any(value is not None and trip[key] != value for key, value in filters.items()):
            continue
        if operational is not None and trip["operational_status"] != operational:
            continue
        if settlement is not None and trip["settlement_status"] != settlement:
            continue
        rows.append(trip)
    rows = store.ordered(rows)
    window = paginate(rows, limit, offset)
    return ok_list([serialize.trip(r) for r in window], limit, offset, len(rows))


# ------------------------------------------------------------- dock slots

@bp.post("/harbor/trips/<trip_id>/dock-slots")
def reserve_dock_slot(trip_id):
    require("Dispatcher")
    trip = find_trip(trip_id)
    body = v.body()

    # rung 4 — body foreign key
    dock = resolve_body_fk(body, "dock_id", store.docks, "ERR_DOCK_NOT_FOUND")

    # rung 6 — payload validity
    v.get_string(body, "dock_id", min_len=1)
    purpose = v.get_enum(body, "purpose", ("LANDING", "LAYOVER"))
    start_raw, start_dt = v.get_utc_instant(body, "start_utc")
    end_raw, end_dt = v.get_utc_instant(body, "end_utc")
    expected_dock_version = v.get_integer(body, "expected_dock_version")

    # rung 7 — time windows
    if end_dt <= start_dt:
        raise ApiError("ERR_INVALID_TIME_WINDOW",
                       "end_utc must be strictly after start_utc.")

    # rung 11 — optimistic concurrency on the dock
    if expected_dock_version != dock["version"]:
        raise ApiError("ERR_STALE_DOCK_VERSION",
                       "expected_dock_version does not match the dock's current version.")

    # rung 19 — berth occupancy
    if calc.dock_berth_conflict(dock, start_dt, end_dt):
        raise ApiError("ERR_DOCK_BERTH_CONFLICT",
                       "The dock has no free berth over the requested window.")

    # rung 21 — the dock must be on the trip's route
    origin = store.stops.get(trip["origin_stop_id"])
    destination = store.stops.get(trip["destination_stop_id"])
    route_docks = set()
    if origin is not None:
        route_docks.add(origin["dock_id"])
    if destination is not None:
        route_docks.add(destination["dock_id"])
    if dock["id"] not in route_docks:
        raise ApiError("ERR_SLOT_DOCK_NOT_ON_ROUTE",
                       "The dock is not on this trip's route.")

    row = store.new_row()
    row.update({
        "dock_id": dock["id"],
        "trip_id": trip["id"],
        "purpose": purpose,
        "start_utc": start_raw,
        "end_utc": end_raw,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "status": "RESERVED",
        "pax_basis": 0,
        "berth_minutes": 0,
        "rebate_bp": 0,
        "projected_fee_cents": 0,
        "landing_fee_cents": 0,
    })
    store.dock_slots[row["id"]] = row
    store.touch(dock)
    return created(serialize.dock_slot(row))


@bp.get("/harbor/dock-slots/<slot_id>")
def read_dock_slot(slot_id):
    require("HarborAdmin", "Dispatcher", "VesselMaster", "FareAuditor")
    return ok(serialize.dock_slot(find_slot(slot_id)))


@bp.get("/harbor/dock-slots")
def list_dock_slots():
    require("HarborAdmin", "Dispatcher", "VesselMaster", "FareAuditor")
    limit, offset = read_pagination()
    dock_id = str_param("dock_id")
    trip_id = str_param("trip_id")
    status = enum_param("status", ("RESERVED", "CONSUMED", "VOIDED"))
    rows = []
    for slot in store.dock_slots.values():
        if dock_id is not None and slot["dock_id"] != dock_id:
            continue
        if trip_id is not None and slot["trip_id"] != trip_id:
            continue
        if status is not None and slot["status"] != status:
            continue
        rows.append(slot)
    rows = store.ordered(rows)
    window = paginate(rows, limit, offset)
    return ok_list([serialize.dock_slot(r) for r in window], limit, offset, len(rows))


# -------------------------------------------------------------- movement

@bp.post("/harbor/trips/<trip_id>/board")
def board_trip(trip_id):
    actor = require("VesselMaster")
    trip = find_trip(trip_id)
    _require_master(actor, trip)
    body = v.body()
    manifest = v.get_string_list(body, "boarded_booking_ids")

    # rung 10 — state precondition
    if trip["operational_status"] != "SCHEDULED":
        raise ApiError("ERR_TRIP_NOT_SCHEDULED", "The trip is not SCHEDULED.")

    # rung 12 — suspended service
    day = _day_of(trip)
    if day is not None and day["posture"] == "SUSPENDED":
        raise ApiError("ERR_SERVICE_SUSPENDED", "The operating day is SUSPENDED.")

    bookings = []
    for booking_id in manifest:
        booking = store.bookings.get(booking_id)
        if booking is None:
            raise ApiError("ERR_BOOKING_NOT_FOUND", "No booking with id %s." % booking_id)
        bookings.append(booking)
    for booking in bookings:
        if booking["trip_id"] != trip["id"] or booking["status"] != "CONFIRMED":
            raise ApiError("ERR_BOOKING_NOT_CONFIRMED",
                           "Booking %s is not CONFIRMED on this trip." % booking["id"])

    total_party = sum(b["party_size"] for b in bookings)
    if total_party > calc.trip_effective_capacity(trip):
        raise ApiError("ERR_TRIP_CAPACITY_EXCEEDED",
                       "The manifest exceeds the trip's effective capacity.")

    trip["boarded_pax"] = total_party
    for booking in bookings:
        booking["status"] = "BOARDED"
        store.touch(booking)
    calc.recompute_seats_committed(trip)
    trip["operational_status"] = "BOARDING"
    store.touch(trip)
    return ok(serialize.trip(trip))


@bp.post("/harbor/trips/<trip_id>/depart")
def depart_trip(trip_id):
    actor = require("VesselMaster")
    trip = find_trip(trip_id)
    _require_master(actor, trip)

    # rung 10 — state precondition
    if trip["operational_status"] != "BOARDING":
        raise ApiError("ERR_TRIP_NOT_BOARDING", "The trip is not BOARDING.")

    day = _day_of(trip)
    vessel = store.vessels.get(trip["vessel_id"])
    crew = store.crew.get(trip["master_crew_id"])

    # rung 12 — suspended service
    if day["posture"] == "SUSPENDED":
        raise ApiError("ERR_SERVICE_SUSPENDED", "The operating day is SUSPENDED.")

    # rung 13 — vessel availability
    service_state = calc.vessel_service_state(vessel)
    if service_state == "LAID_UP":
        raise ApiError("ERR_VESSEL_IN_LAYUP", "The vessel is laid up.")
    if service_state == "OUT_OF_SERVICE":
        raise ApiError("ERR_VESSEL_OUT_OF_SERVICE", "The vessel is out of service.")

    # rung 14 — annual inspection
    latest = calc.latest_annual_inspection(vessel["id"])
    today = store.clock_date()
    if latest is None or latest["result"] == "FAIL":
        raise ApiError("ERR_VESSEL_INSPECTION_INVALID",
                       "The vessel has no valid annual inspection.")
    expires = parse_date(latest["expires_on"])
    if expires is None or expires < today:
        raise ApiError("ERR_VESSEL_INSPECTION_INVALID",
                       "The vessel's annual inspection has expired.")
    if day["posture"] == "RESTRICTED" and latest["deficiency_count"] > calc.MAX_DEFICIENCIES_RESTRICTED:
        raise ApiError("ERR_VESSEL_INSPECTION_INVALID",
                       "Too many open deficiencies for RESTRICTED posture.")

    # rung 15 — hull class
    if day["posture"] == "RESTRICTED" and vessel["hull_class"] != "OFFSHORE":
        raise ApiError("ERR_HULL_CLASS_RESTRICTED",
                       "Only OFFSHORE hulls may sail under RESTRICTED posture.")

    # rung 16 — crew currency
    cert = parse_date(crew["cert_expires_on"])
    medical = parse_date(crew["medical_expires_on"])
    if (crew["status"] != "ACTIVE"
            or cert is None or cert < today
            or medical is None or medical < today):
        raise ApiError("ERR_CREW_CERT_EXPIRED", "The master is not current.")

    # rung 17 — endorsement rank
    if calc.ENDORSEMENT_RANK[crew["endorsement_class"]] < calc.ENDORSEMENT_RANK[vessel["required_endorsement"]]:
        raise ApiError("ERR_CREW_ENDORSEMENT_INSUFFICIENT",
                       "The master's endorsement is insufficient for this vessel.")

    # rung 18 — under-keel clearance
    if calc.under_keel_clearance(day, vessel) < calc.MIN_UNDER_KEEL_CLEARANCE_M:
        raise ApiError("ERR_UNDER_KEEL_CLEARANCE",
                       "Under-keel clearance is below the safety minimum.")

    now = store.clock_now()
    trip["actual_departure_utc"] = iso_instant(now)
    trip["_actual_departure_dt"] = now
    trip["booked_pax"] = trip["seats_committed"]
    trip["provisional_fee_cents"] = cascades.post_provisional_fees(trip)
    trip["settlement_status"] = "PROVISIONAL"
    trip["operational_status"] = "DEPARTED"
    store.touch(trip)
    return ok(serialize.trip(trip))


@bp.post("/harbor/trips/<trip_id>/complete")
def complete_trip(trip_id):
    actor = require("VesselMaster")
    trip = find_trip(trip_id)
    _require_master(actor, trip)

    now = store.clock_now()

    # rung 7 — time windows
    if trip["_actual_departure_dt"] is not None and now <= trip["_actual_departure_dt"]:
        raise ApiError("ERR_INVALID_TIME_WINDOW",
                       "The clock must read strictly later than actual_departure_utc.")

    # rung 10 — state precondition
    if trip["operational_status"] != "DEPARTED":
        raise ApiError("ERR_TRIP_NOT_DEPARTED", "The trip is not DEPARTED.")

    trip["actual_arrival_utc"] = iso_instant(now)
    trip["final_fee_cents"] = cascades.post_final_fees(trip)
    trip["settlement_status"] = "FINAL"
    trip["operational_status"] = "COMPLETED"

    bookings = [b for b in store.bookings.values()
                if b["trip_id"] == trip["id"] and b["status"] == "BOARDED"]
    for booking in store.ordered(bookings):
        booking["status"] = "COMPLETED"
        store.touch(booking)

    crew = store.crew.get(trip["master_crew_id"])
    if crew is not None:
        crew["trips_mastered_count"] = crew["trips_mastered_count"] + 1
        store.touch(crew)

    calc.recompute_seats_committed(trip)
    store.touch(trip)
    return ok(serialize.trip(trip))
