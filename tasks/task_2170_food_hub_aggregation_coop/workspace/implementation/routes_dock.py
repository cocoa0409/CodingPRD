"""Cross-dock doors, drop-off appointments, cold-chain receipt and the no-show."""

from flask import Blueprint, request

import cascade
import domain
import fetch
import serializers
from constants import (APPOINTMENT_OUTCOMES, DEFAULT_SANITATION_BUFFER_MINUTES,
                       RISK_CLASSES, ROLE_HUB_ADMIN, ROLE_PRODUCER,
                       STORAGE_CLASSES)
from envelope import list_response, ok
from errors import ApiError
from store import add_minutes, base_record, db, sorted_records, touch
from validators import (actor, body, endpoint, opt_int, opt_number, req_datetime,
                        req_enum, req_int, req_number, req_string)

bp = Blueprint("dock", __name__)


# ---------------------------------------------------------------------------
# dock slots
# ---------------------------------------------------------------------------

@bp.post("/dock-slots")
@endpoint([ROLE_HUB_ADMIN])
def create_dock_slot():
    payload = body()
    door_code = req_string(payload, "door_code", min_len=1, max_len=12)
    storage_class = req_enum(payload, "storage_class", STORAGE_CLASSES)
    window_start = req_datetime(payload, "window_start")
    window_end = req_datetime(payload, "window_end")
    pallet_capacity = req_int(payload, "pallet_capacity", minimum=1)
    temp_setpoint_c = req_number(payload, "temp_setpoint_c")
    buffer_minutes = opt_int(payload, "sanitation_buffer_minutes", minimum=0,
                             default=DEFAULT_SANITATION_BUFFER_MINUTES)

    # rung 18
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_WINDOW")

    slot = base_record({
        "door_code": door_code,
        "storage_class": storage_class,
        "window_start": window_start,
        "window_end": window_end,
        "pallet_capacity": pallet_capacity,
        "temp_setpoint_c": temp_setpoint_c,
        "sanitation_buffer_minutes": buffer_minutes,
        "pallets_booked": 0,
        "status": "OPEN",
    })
    db.dock_slots[slot["id"]] = slot
    return ok(serializers.dock_slot_out(slot), 201)


@bp.get("/dock-slots/<slot_id>")
@endpoint([ROLE_HUB_ADMIN, ROLE_PRODUCER])
def read_dock_slot(slot_id):
    slot = fetch.get("dock_slot", slot_id)
    return ok(serializers.dock_slot_out(slot))


# ---------------------------------------------------------------------------
# appointments
# ---------------------------------------------------------------------------

def _active_appointments(slot_id):
    return [a for a in sorted_records(list(db.appointments.values()))
            if a["dock_slot_id"] == slot_id and a["status"] in ("BOOKED", "RECEIVED")]


@bp.post("/dock-appointments")
@endpoint([ROLE_PRODUCER, ROLE_HUB_ADMIN])
def book_appointment():
    payload = body()
    slot = fetch.body_fk(payload, "dock_slot_id", "dock_slot")     # rung 5
    producer = fetch.body_fk(payload, "producer_id", "producer")   # rung 5

    # rung 6
    req_string(payload, "dock_slot_id")
    req_string(payload, "producer_id")
    arrival_start = req_datetime(payload, "arrival_start")
    arrival_end = req_datetime(payload, "arrival_end")
    pallets = req_int(payload, "pallets", minimum=1)
    risk_class = req_enum(payload, "risk_class", RISK_CLASSES)
    expected_version = req_int(payload, "expected_dock_slot_version")

    user_id, role = actor()
    if role == ROLE_PRODUCER and user_id != producer["id"]:         # rung 7
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # rung 9
    if expected_version != slot["version"]:
        raise ApiError("ERR_STALE_DOCK_SLOT_VERSION")

    # rung 13
    if not domain.producer_in_good_standing(producer):
        raise ApiError("ERR_PRODUCER_NOT_COMPLIANT")

    # rung 18
    if arrival_end <= arrival_start:
        raise ApiError("ERR_INVALID_WINDOW")
    # rung 19 — containment inside the door's bookable window
    if arrival_start < slot["window_start"] or arrival_end > slot["window_end"]:
        raise ApiError("ERR_INVALID_WINDOW")

    neighbours = _active_appointments(slot["id"])

    # rung 20 — aggregate capacity over half-open overlap (checked BEFORE sanitation)
    overlapping = [a for a in neighbours
                   if a["arrival_start"] < arrival_end and arrival_start < a["arrival_end"]]
    if pallets + sum(a["pallets"] for a in overlapping) > slot["pallet_capacity"]:
        raise ApiError("ERR_DOCK_CAPACITY_EXCEEDED")

    # rung 21 — sanitation separation against every differing risk_class neighbour
    buffer_minutes = slot["sanitation_buffer_minutes"]
    for other in neighbours:
        if other["risk_class"] == risk_class:
            continue
        separated = (add_minutes(other["arrival_end"], buffer_minutes) <= arrival_start
                     or add_minutes(arrival_end, buffer_minutes) <= other["arrival_start"])
        if not separated:
            raise ApiError("ERR_SANITATION_BUFFER_VIOLATION")

    appointment = base_record({
        "dock_slot_id": slot["id"],
        "producer_id": producer["id"],
        "arrival_start": arrival_start,
        "arrival_end": arrival_end,
        "pallets": pallets,
        "risk_class": risk_class,
        "received_pallets": 0,
        "recorded_temp_c": None,
        "status": "BOOKED",
    })
    db.appointments[appointment["id"]] = appointment

    domain.refresh_slot(slot)
    touch(slot)
    return ok(serializers.appointment_out(appointment), 201)


@bp.get("/dock-appointments/<appointment_id>")
@endpoint([ROLE_HUB_ADMIN, ROLE_PRODUCER])
def read_appointment(appointment_id):
    appointment = fetch.get("appointment", appointment_id)
    return ok(serializers.appointment_out(appointment))


@bp.get("/dock-appointments")
@endpoint([ROLE_HUB_ADMIN, ROLE_PRODUCER])
def list_appointments():
    records = sorted_records(list(db.appointments.values()))
    for field in ("dock_slot_id", "producer_id", "status"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    return list_response(records, serializers.appointment_out)


# ---------------------------------------------------------------------------
# receipt / close-out
# ---------------------------------------------------------------------------

@bp.post("/dock-appointments/<appointment_id>/receipt")
@endpoint([ROLE_HUB_ADMIN])
def close_out_appointment(appointment_id):
    appointment = fetch.get("appointment", appointment_id)         # rung 4
    payload = body()
    outcome = req_enum(payload, "outcome", APPOINTMENT_OUTCOMES)   # rung 6
    received_pallets = opt_int(payload, "received_pallets", minimum=0, default=0)
    recorded_temp_c = opt_number(payload, "recorded_temp_c")

    # rung 10
    if appointment["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE")
    producer = db.producers.get(appointment["producer_id"])
    if outcome == "RECEIVED":
        if producer is None or producer["onboarding_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_PRODUCER_STATE")

    slot = db.dock_slots.get(appointment["dock_slot_id"])
    booked_before = domain.slot_pallets_booked(slot) if slot is not None else 0

    if outcome == "RECEIVED":
        appointment["status"] = "RECEIVED"
        appointment["received_pallets"] = received_pallets
        appointment["recorded_temp_c"] = recorded_temp_c
        touch(appointment)
        if slot is not None:
            cascade.stage_allocations(appointment, slot)
        cascade.advance_loaded_routes()
    elif outcome == "NO_SHOW":
        appointment["status"] = "NO_SHOW"
        touch(appointment)
        cascade.no_show_unwind(appointment)
    else:
        appointment["status"] = "CANCELLED"
        touch(appointment)

    if slot is not None:
        domain.refresh_slot(slot)
        if slot["pallets_booked"] != booked_before:
            touch(slot)

    return ok(serializers.appointment_out(appointment))
