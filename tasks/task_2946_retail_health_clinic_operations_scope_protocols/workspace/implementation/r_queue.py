"""Routes: queue intake, arrival and calling the next patient."""

from datetime import timedelta

from flask import Blueprint

import calc
import engine
import serial
from auth import (
    ROLE_CLINIC_ADMIN,
    ROLE_CLINICIAN,
    ROLE_FRONT_DESK,
    authenticate,
)
from common import collection, get_clinic, get_patient, get_queue_entry
from envelope import object_response
from errors import (
    ERR_APPOINTMENT_SLOT_CONFLICT,
    ERR_APPOINTMENT_WINDOW_CLOSED,
    ERR_CLINIC_CLOSED,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_HOURLY_SLOT_CAPACITY_EXCEEDED,
    ERR_INVALID_TIME_RANGE,
    ERR_QUEUE_CAPACITY_REACHED,
    ERR_QUEUE_EMPTY,
    ERR_QUEUE_ENTRY_INVALID_STATE,
    ERR_WALK_IN_SUSPENDED,
    raise_error,
)
from shapes import (
    bad,
    json_body,
    query_enum,
    query_string,
    read_enum,
    read_instant,
    read_string,
    reject_unknown,
)
from store import db, new_row, touch

bp = Blueprint("queue", __name__)

QUEUE_KINDS = ("WALK_IN", "APPOINTMENT")
QUEUE_STATUSES = (
    "SCHEDULED",
    "WAITING",
    "CALLED",
    "SERVED",
    "ABANDONED",
    "DEFERRED_CLOSURE",
)


def _hour_bucket(instant):
    return instant.replace(minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# POST /queue-entries
# ---------------------------------------------------------------------------

@bp.route("/queue-entries", methods=["POST"])
def create_queue_entry():
    authenticate([ROLE_FRONT_DESK, ROLE_CLINIC_ADMIN])
    body = json_body(required=True)
    reject_unknown(body, {
        "clinic_id",
        "patient_id",
        "kind",
        "complaint_code",
        "scheduled_at",
    })
    clinic_id = read_string(body, "clinic_id")
    patient_id = read_string(body, "patient_id")
    kind = read_enum(body, "kind", QUEUE_KINDS)
    complaint_code = read_enum(body, "complaint_code", calc.COMPLAINT_CODES)
    scheduled_at = read_instant(body, "scheduled_at", required=False)

    # rung 5 - conditional shape of scheduled_at
    if kind == "APPOINTMENT" and scheduled_at is None:
        bad("Field 'scheduled_at' is required for an APPOINTMENT entry.")
    if kind == "WALK_IN" and scheduled_at is not None:
        bad("Field 'scheduled_at' is not permitted for a WALK_IN entry.")

    # rung 7 - body references
    clinic = get_clinic(clinic_id)
    get_patient(patient_id)

    # rung 12 - clinic posture
    if clinic["open_status"] == "CLOSED":
        raise_error(ERR_CLINIC_CLOSED)
    if kind == "WALK_IN" and clinic["open_status"] == "LIMITED":
        raise_error(ERR_WALK_IN_SUSPENDED)

    if kind == "APPOINTMENT":
        # rung 27 - appointment spacing
        spacing = timedelta(minutes=calc.APPOINTMENT_SPACING_MINUTES)
        for other in db.queue_entries.values():
            if other["clinic_id"] != clinic["id"]:
                continue
            if other["kind"] != "APPOINTMENT":
                continue
            if other["status"] not in ("SCHEDULED", "WAITING"):
                continue
            if other.get("scheduled_at") is None:
                continue
            gap = other["scheduled_at"] - scheduled_at
            if gap < timedelta(0):
                gap = -gap
            if gap < spacing:
                raise_error(ERR_APPOINTMENT_SLOT_CONFLICT)

        # rung 29 - interval sanity
        if scheduled_at < db.clock:
            raise_error(
                ERR_INVALID_TIME_RANGE,
                "Field 'scheduled_at' may not be earlier than the current time.",
            )

        # rung 33 - hourly slot capacity
        bucket = _hour_bucket(scheduled_at)
        in_hour = 0
        for other in db.queue_entries.values():
            if other["clinic_id"] != clinic["id"]:
                continue
            if other["kind"] != "APPOINTMENT":
                continue
            if other.get("scheduled_at") is None:
                continue
            if _hour_bucket(other["scheduled_at"]) == bucket:
                in_hour += 1
        if in_hour >= clinic["appointment_slots_per_hour"]:
            raise_error(ERR_HOURLY_SLOT_CAPACITY_EXCEEDED)
    else:
        # rung 33 - walk-in queue capacity
        waiting_walk_ins = 0
        for other in db.queue_entries.values():
            if (
                other["clinic_id"] == clinic["id"]
                and other["kind"] == "WALK_IN"
                and other["status"] == "WAITING"
            ):
                waiting_walk_ins += 1
        if waiting_walk_ins >= clinic["walk_in_queue_capacity"]:
            raise_error(ERR_QUEUE_CAPACITY_REACHED)

    protocol = calc.protocol_for(complaint_code, clinic["state_code"])

    row = new_row()
    row.update({
        "clinic_id": clinic["id"],
        "patient_id": patient_id,
        "kind": kind,
        "complaint_code": complaint_code,
        "acuity_tier": protocol["acuity_tier"] if protocol is not None else None,
        "scheduled_at": scheduled_at,
        "arrived_at": db.clock if kind == "WALK_IN" else None,
        "called_at": None,
        "priority_score": 0,
        "realized_wait_minutes": None,
        "status": "WAITING" if kind == "WALK_IN" else "SCHEDULED",
    })
    row["priority_score"] = calc.queue_priority_score(row)
    db.queue_entries[row["id"]] = row

    engine.refresh_clinic(clinic)
    return object_response(serial.queue_entry(row), 201)


# ---------------------------------------------------------------------------
# POST /queue-entries/{queueEntryId}/arrive
# ---------------------------------------------------------------------------

@bp.route("/queue-entries/<queue_entry_id>/arrive", methods=["POST"])
def arrive_queue_entry(queue_entry_id):
    authenticate([ROLE_FRONT_DESK])
    body = json_body(required=False)
    reject_unknown(body, set())

    row = get_queue_entry(queue_entry_id)

    # rung 10 - declared transition
    if row["kind"] != "APPOINTMENT" or row["status"] != "SCHEDULED":
        raise_error(
            ERR_QUEUE_ENTRY_INVALID_STATE,
            "Queue entry %s cannot be arrived from %s."
            % (row["id"], row["status"]),
        )

    clinic = db.clinics.get(row["clinic_id"])

    # rung 12 - clinic posture (LIMITED still admits arrivals)
    if clinic is not None and clinic["open_status"] == "CLOSED":
        raise_error(ERR_CLINIC_CLOSED)

    # rung 26 - arrival window
    earliest = row["scheduled_at"] - timedelta(minutes=calc.ARRIVAL_EARLY_MINUTES)
    latest = row["scheduled_at"] + timedelta(minutes=calc.ARRIVAL_LATE_MINUTES)
    if db.clock < earliest or db.clock > latest:
        raise_error(ERR_APPOINTMENT_WINDOW_CLOSED)

    row["status"] = "WAITING"
    row["arrived_at"] = db.clock
    row["priority_score"] = calc.queue_priority_score(row)
    touch(row)

    engine.refresh_clinic(clinic)
    return object_response(serial.queue_entry(row), 200)


# ---------------------------------------------------------------------------
# POST /clinics/{clinicId}/call-next
# ---------------------------------------------------------------------------

@bp.route("/clinics/<clinic_id>/call-next", methods=["POST"])
def call_next(clinic_id):
    actor = authenticate([ROLE_CLINICIAN])
    body = json_body(required=False)
    reject_unknown(body, set())

    clinic = get_clinic(clinic_id)

    # rung 12 - clinic posture
    if clinic["open_status"] == "CLOSED":
        raise_error(ERR_CLINIC_CLOSED)

    # ownership - the caller must be on duty at this clinic
    if calc.active_assignment_at(clinic["id"], actor.user_id) is None:
        raise_error(
            ERR_FORBIDDEN_OWNERSHIP,
            "Clinician %s holds no ACTIVE assignment at clinic %s."
            % (actor.user_id, clinic["id"]),
        )

    winner = calc.call_next_selection(clinic["id"])
    if winner is None:
        raise_error(ERR_QUEUE_EMPTY)

    winner["priority_score"] = calc.queue_priority_score(winner)
    winner["status"] = "CALLED"
    winner["called_at"] = db.clock
    winner["realized_wait_minutes"] = calc.realized_wait_minutes(winner)
    touch(winner)

    previous = clinic["last_realized_wait_minutes"]
    clinic["last_realized_wait_minutes"] = winner["realized_wait_minutes"]
    engine.refresh_clinic(
        clinic, extra_changed=previous != clinic["last_realized_wait_minutes"]
    )
    return object_response(serial.queue_entry(winner), 200)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

@bp.route("/queue-entries/<queue_entry_id>", methods=["GET"])
def read_queue_entry(queue_entry_id):
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_FRONT_DESK])
    row = get_queue_entry(queue_entry_id)
    return object_response(serial.queue_entry(row), 200)


@bp.route("/queue-entries", methods=["GET"])
def list_queue_entries():
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_FRONT_DESK])
    clinic_id = query_string("clinic_id")
    patient_id = query_string("patient_id")
    kind = query_enum("kind", QUEUE_KINDS)
    status = query_enum("status", QUEUE_STATUSES)
    return collection(db.queue_entries, serial.queue_entry, [
        (clinic_id, lambda row, v: row["clinic_id"] == v),
        (patient_id, lambda row, v: row["patient_id"] == v),
        (kind, lambda row, v: row["kind"] == v),
        (status, lambda row, v: row["status"] == v),
    ])
