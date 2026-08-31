"""Appointment booking and lifecycle (PRD §3.5, §3.7)."""

from flask import Blueprint, request

import calc
import serializers
from calc import ZERO, dec
from cascades import (
    cancel_appointment,
    maybe_suspend_resident,
    rewrite_lines_as_referred,
)
from common import gate_frozen, gate_restricted, list_response
from envelope import ok
from errors import ApiError
from rollups import (
    appointments_of_event,
    lines_of_appointment,
    live_open_lane_count,
    live_reserved_slot_count,
    live_slot_capacity,
    refresh_world,
)
from store import clock_raw, new_row, ordered, set_and_touch, store, touch
from validation import (
    ALL_READ_ROLES,
    authorize,
    authorize_action,
    body,
    context,
    lookup,
    opt_enum,
    opt_int,
    opt_str,
    req_dt,
    req_enum,
    req_int,
    req_num,
    req_str,
    req_str_array,
)

bp = Blueprint("appointments", __name__)

CANCEL_REASONS = ["RESIDENT_REQUEST", "SUPERSEDED", "RESIDENT_SUSPENDED",
                  "EVENT_CANCELLED"]

APPOINTMENT_ACTION_ROLES = {
    "CONFIRM": ["EligibilityClerk", "Resident"],
    "WAITLIST": ["EligibilityClerk"],
    "PROMOTE": ["EligibilityClerk"],
    "CANCEL": ["EligibilityClerk", "Resident"],
    "CHECK_IN": ["UnloadTech"],
    "START_UNLOAD": ["UnloadTech"],
    "COMPLETE_UNLOAD": ["UnloadTech"],
    "REFER_BUSINESS": ["UnloadTech"],
    "NO_SHOW": ["UnloadTech"],
}

APPOINTMENT_TRANSITIONS = {
    "CONFIRM": {"REQUESTED": "CONFIRMED"},
    "WAITLIST": {"REQUESTED": "WAITLISTED"},
    "PROMOTE": {"WAITLISTED": "CONFIRMED"},
    "CANCEL": {"REQUESTED": "CANCELLED", "CONFIRMED": "CANCELLED",
               "WAITLISTED": "CANCELLED"},
    "CHECK_IN": {"CONFIRMED": "CHECKED_IN"},
    "START_UNLOAD": {"CHECKED_IN": "UNLOADING"},
    "COMPLETE_UNLOAD": {"UNLOADING": "COMPLETED"},
    "REFER_BUSINESS": {"UNLOADING": "REFERRED_OUT", "CHECKED_IN": "REFERRED_OUT"},
    "NO_SHOW": {"CONFIRMED": "NO_SHOW"},
}


@bp.post("/hhw/appointments")
def create_appointment():
    user_id, role = context()
    authorize(role, ["Resident", "EligibilityClerk"])
    payload = body()
    event_id = req_str(payload, "event_id")
    resident_id = req_str(payload, "resident_id")
    slot_start = req_dt(payload, "slot_start_utc")
    waste_origin = req_enum(payload, "waste_origin", ["HOUSEHOLD", "BUSINESS"])
    declared_total_kg = req_num(payload, "declared_total_kg", gt=0)
    declared_category_ids = req_str_array(payload, "declared_category_ids")
    expected_version = req_int(payload, "expected_resident_version")
    vehicle_count = opt_int(payload, "vehicle_count", default=1, minimum=1, maximum=2)

    # Rung 5 — foreign keys in the declared order.
    event = lookup("event", event_id)
    resident = lookup("resident", resident_id)
    categories = [lookup("material_category", cid) for cid in declared_category_ids]

    # Rung 6 — resident ownership.
    if role == "Resident" and user_id != resident["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # Rung 8 — stale-version guard on the resident.
    if expected_version != resident["version"]:
        raise ApiError("ERR_STALE_VERSION")

    # Rung 10 — the event must be accepting registrations.
    if event["lifecycle_status"] != "OPEN_FOR_REGISTRATION":
        raise ApiError("ERR_EVENT_NOT_ACCEPTING_REGISTRATIONS")

    # Rung 18 — no prohibited material declared at booking.
    for category in categories:
        if category["acceptance_policy"] == "REJECTED_ALWAYS":
            raise ApiError("ERR_PROHIBITED_MATERIAL_DECLARED")

    # Rung 26 — the slot lies inside the half-open event window.
    if slot_start < event["_window_start_dt"] or slot_start >= event["_window_end_dt"]:
        raise ApiError("ERR_SLOT_OUTSIDE_EVENT_WINDOW")

    # Rung 27 — quarter-hour alignment measured from window_start_utc.
    offset = (slot_start - event["_window_start_dt"]).total_seconds()
    if offset % calc.SLOT_ALIGNMENT_SECONDS != 0:
        raise ApiError("ERR_SLOT_NOT_ALIGNED")

    event["_queue_seq"] = event.get("_queue_seq", 0) + 1
    row = new_row({
        "event_id": event["id"],
        "resident_id": resident["id"],
        "slot_start_utc": payload["slot_start_utc"],
        "_slot_start_dt": slot_start,
        "waste_origin": waste_origin,
        "declared_total_kg": declared_total_kg,
        "declared_category_ids": list(declared_category_ids),
        "vehicle_count": vehicle_count,
        "status": "REQUESTED",
        "waitlist_reason": None,
        "cancel_reason": None,
        "referral_program_code": None,
        "referral_packet_code": None,
        "queue_seq": event["_queue_seq"],
        "reserved_kg": ZERO,
        "settled_kg": ZERO,
        "check_in_utc": None,
        "unload_complete_utc": None,
    })
    store.appointments[row["id"]] = row

    # The booking supersedes the resident's other non-terminal appointment at
    # this same event, releasing its reservation.
    for other in ordered(appointments_of_event(event["id"])):
        if other["id"] == row["id"]:
            continue
        if other["resident_id"] != resident["id"]:
            continue
        if other["status"] in ("REQUESTED", "CONFIRMED", "WAITLISTED"):
            cancel_appointment(other, "SUPERSEDED")

    touch(resident)
    refresh_world()
    return ok(serializers.appointment(row), 201)


@bp.get("/hhw/appointments")
def list_appointments():
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    filters = {
        "event_id": request.args.get("event_id"),
        "resident_id": request.args.get("resident_id"),
        "status": request.args.get("status"),
        "waitlist_reason": request.args.get("waitlist_reason"),
    }
    return list_response(request.args, list(store.appointments.values()),
                         serializers.appointment, filters)


@bp.get("/hhw/appointments/<appointment_id>")
def read_appointment(appointment_id):
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    return ok(serializers.appointment(lookup("appointment", appointment_id)))


@bp.post("/hhw/appointments/<appointment_id>/transitions")
def appointment_transition(appointment_id):
    user_id, role = context()
    authorize(role, ["Resident", "EligibilityClerk", "UnloadTech"])
    payload = body()
    action = payload.get("action")
    authorize_action(role, action, APPOINTMENT_ACTION_ROLES)
    action = req_enum(payload, "action", list(APPOINTMENT_TRANSITIONS.keys()))
    cancel_reason = opt_enum(payload, "cancel_reason", CANCEL_REASONS)
    opt_str(payload, "no_show_note")
    referral_program_code = None
    if action == "REFER_BUSINESS":
        referral_program_code = req_str(payload, "referral_program_code")

    appointment = lookup("appointment", appointment_id)
    event = store.events.get(appointment["event_id"])
    resident = store.residents.get(appointment["resident_id"])
    program = store.programs.get(event["program_id"]) if event else None

    # Rung 6 — resident ownership.
    if role == "Resident" and user_id != appointment["resident_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # Rung 9 — declared transition out of the current state.
    target = APPOINTMENT_TRANSITIONS[action].get(appointment["status"])
    if target is None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if action in ("CONFIRM", "PROMOTE"):
        if event["lifecycle_status"] != "OPEN_FOR_REGISTRATION":          # rung 10
            raise ApiError("ERR_EVENT_NOT_ACCEPTING_REGISTRATIONS")
        if event["containment_status"] not in ("COMPLIANT", "REMEDIATED"):
            raise ApiError("ERR_CONTAINMENT_DEFICIENT")                   # rung 12
        gate_frozen(program)                                              # rung 14
        gate_restricted(program)                                          # rung 15
        if appointment["waste_origin"] != "HOUSEHOLD":                    # rung 19
            raise ApiError("ERR_BUSINESS_WASTE_EXCLUDED")
        if resident is None or resident["eligibility_status"] != "ELIGIBLE":
            raise ApiError("ERR_RESIDENT_NOT_ELIGIBLE")                   # rung 28
        if live_reserved_slot_count(event) + 1 > live_slot_capacity(event):
            raise ApiError("ERR_EVENT_SLOT_CAPACITY_EXCEEDED")            # rung 30
        set_and_touch(appointment, status="CONFIRMED", waitlist_reason=None,
                      reserved_kg=dec(appointment["declared_total_kg"]))

    elif action == "WAITLIST":
        if event["lifecycle_status"] != "OPEN_FOR_REGISTRATION":          # rung 10
            raise ApiError("ERR_EVENT_NOT_ACCEPTING_REGISTRATIONS")
        if appointment["waste_origin"] != "HOUSEHOLD":                    # rung 19
            raise ApiError("ERR_BUSINESS_WASTE_EXCLUDED")
        if resident is None or resident["eligibility_status"] != "ELIGIBLE":
            raise ApiError("ERR_RESIDENT_NOT_ELIGIBLE")                   # rung 28
        set_and_touch(appointment, status="WAITLISTED",
                      waitlist_reason="CAPACITY", reserved_kg=ZERO)

    elif action == "CANCEL":
        cancel_appointment(appointment, cancel_reason or "RESIDENT_REQUEST")

    elif action == "CHECK_IN":
        require_in_progress(event)                                        # rung 9
        if event["containment_status"] not in ("COMPLIANT", "REMEDIATED"):
            raise ApiError("ERR_CONTAINMENT_DEFICIENT")                   # rung 12
        set_and_touch(appointment, status="CHECKED_IN", check_in_utc=clock_raw())

    elif action == "START_UNLOAD":
        require_in_progress(event)                                        # rung 9
        if live_open_lane_count(event) < 1:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "No lane is staffed.")
        set_and_touch(appointment, status="UNLOADING")

    elif action == "COMPLETE_UNLOAD":
        require_in_progress(event)                                        # rung 9
        if len(lines_of_appointment(appointment["id"])) < 1:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The appointment carries no dropoff line.")
        set_and_touch(appointment, status="COMPLETED",
                      unload_complete_utc=clock_raw(), reserved_kg=ZERO)

    elif action == "REFER_BUSINESS":
        require_in_progress(event)                                        # rung 9
        packet = "%s-%s-%s" % (referral_program_code, event["event_date"],
                               appointment["queue_seq"])
        set_and_touch(appointment, status="REFERRED_OUT",
                      referral_program_code=referral_program_code,
                      referral_packet_code=packet, reserved_kg=ZERO)
        rewrite_lines_as_referred(appointment)

    else:  # NO_SHOW
        require_in_progress(event)                                        # rung 9
        set_and_touch(appointment, status="NO_SHOW", reserved_kg=ZERO,
                      waitlist_reason=None)
        maybe_suspend_resident(resident)

    refresh_world()
    return ok(serializers.appointment(appointment))


def require_in_progress(event):
    if event is None or event["lifecycle_status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The collection event is not in progress.")
