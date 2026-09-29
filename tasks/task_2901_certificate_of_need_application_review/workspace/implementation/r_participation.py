"""Interventions and public hearings (PRD §3.6)."""

from datetime import timedelta

from flask import Blueprint

import auth
import clock
import envelope
import services
import shape
import store
from errors import ApiError

bp = Blueprint("participation", __name__)

READ_ROLES = auth.STAFF_AND_PARTIES
DECISIONS = ("GRANT", "DENY")


# --- interventions -----------------------------------------------------------

@bp.post("/interventions")
def file_intervention():
    user_id, _role = auth.identity(["Applicant"])
    body = shape.body()
    application_id = shape.string_field(body, "application_id")
    party_id = shape.string_field(body, "affected_party_applicant_id")
    grounds = shape.string_field(body, "grounds")
    requested_hearing = shape.bool_field(body, "requested_hearing", required=False, default=False)

    app = services.application(application_id)
    party = services.applicant(party_id)

    services.require_not_barred(party)

    if party_id == app["applicant_id"]:
        raise ApiError("ERR_NOT_AFFECTED_PARTY", "A provider cannot intervene against itself.")
    if user_id != party_id:
        raise ApiError("ERR_NOT_AFFECTED_PARTY",
                       "A provider cannot intervene on another party's behalf.")

    cycle_row = services.cycle_of_application(app)
    if cycle_row is not None and clock.now() > clock.parse_instant(
            cycle_row["intervention_deadline_at"]):
        raise ApiError("ERR_INTERVENTION_DEADLINE_PASSED",
                       "The intervention deadline has passed.")

    record = store.create("interventions", {
        "application_id": app["id"],
        "affected_party_applicant_id": party_id,
        "grounds": grounds,
        "requested_hearing": requested_hearing,
        "filed_at": clock.now_str(),
        "status": "REQUESTED",
        "decided_by_user_id": None,
        "denial_reason": None,
    })
    return envelope.ok(record, 201)


@bp.get("/interventions/<record_id>")
def read_intervention(record_id):
    auth.identity(READ_ROLES)
    return envelope.ok(services.intervention(record_id))


@bp.get("/interventions")
def list_interventions():
    auth.identity(READ_ROLES)
    limit, offset = shape.pagination()
    picked = shape.filters("application_id", "affected_party_applicant_id", "status")
    rows = shape.apply_filters(store.sort_created(store.rows("interventions")), picked)
    return envelope.ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.post("/interventions/<record_id>/decide")
def decide_intervention(record_id):
    user_id, _role = auth.identity(["IntakeAnalyst"])
    body = shape.body()
    decision = shape.enum_field(body, "decision", DECISIONS)
    denial_reason = shape.string_field(body, "denial_reason", required=False, default=None)
    if decision == "DENY" and denial_reason is None:
        shape.bad("Field 'denial_reason' is required when denying an intervention.")
    record = services.intervention(record_id)

    if record["status"] != "REQUESTED":
        raise ApiError("ERR_INTERVENTION_ALREADY_DECIDED",
                       "This intervention request has already been decided.")

    if decision == "GRANT":
        app = store.get("applications", record["application_id"])
        if app is None or app["status"] not in services.LIVE_INTAKE_STATES:
            raise ApiError("ERR_APPLICATION_NOT_IN_COMPLETENESS_REVIEW",
                           "The target application has moved beyond intake.")
        record["status"] = "GRANTED"
    else:
        record["status"] = "DENIED"
        record["denial_reason"] = denial_reason
    record["decided_by_user_id"] = user_id
    store.touch(record)
    return envelope.ok(record)


# --- public hearings ---------------------------------------------------------

def _occupancy_start(start_at, room):
    return start_at - timedelta(minutes=int(room["setup_buffer_minutes"]))


def _require_room_free(room_id, occupancy_start, end_at, exclude_id=None):
    for other in store.rows("public_hearings"):
        if other["hearing_room_id"] != room_id or other["status"] != "SCHEDULED":
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        other_start = clock.parse_instant(other["occupancy_start_at"])
        other_end = clock.parse_instant(other["scheduled_end_at"])
        if occupancy_start < other_end and other_start < end_at:
            raise ApiError("ERR_HEARING_ROOM_CONFLICT",
                           "The buffered occupancy interval overlaps another scheduled hearing.")


@bp.post("/public-hearings")
def schedule_hearing():
    auth.identity(["IntakeAnalyst"])
    body = shape.body()
    cycle_id = shape.string_field(body, "batching_cycle_id")
    room_id = shape.string_field(body, "hearing_room_id")
    start_raw, start_at = shape.instant_field(body, "scheduled_start_at")
    end_raw, end_at = shape.instant_field(body, "scheduled_end_at")
    if not end_at > start_at:
        shape.bad("Field 'scheduled_end_at' must be strictly after 'scheduled_start_at'.")

    cycle_row = services.cycle(cycle_id)
    room = services.hearing_room(room_id)

    occupancy_start = _occupancy_start(start_at, room)
    _require_room_free(room_id, occupancy_start, end_at)

    record = store.create("public_hearings", {
        "batching_cycle_id": cycle_row["id"],
        "hearing_room_id": room_id,
        "scheduled_start_at": start_raw,
        "scheduled_end_at": end_raw,
        "occupancy_start_at": clock.fmt(occupancy_start),
        "status": "SCHEDULED",
        "attendee_count": None,
        "transcript_reference": None,
        "reschedule_count": 0,
    })
    return envelope.ok(record, 201)


@bp.get("/public-hearings/<record_id>")
def read_hearing(record_id):
    auth.identity(READ_ROLES)
    return envelope.ok(services.hearing(record_id))


@bp.get("/public-hearings")
def list_hearings():
    auth.identity(READ_ROLES)
    limit, offset = shape.pagination()
    picked = shape.filters("batching_cycle_id", "hearing_room_id", "status")
    rows = shape.apply_filters(store.sort_created(store.rows("public_hearings")), picked)
    return envelope.ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.post("/public-hearings/<record_id>/cancel")
def cancel_hearing(record_id):
    auth.identity(["IntakeAnalyst"])
    body = shape.body()
    shape.string_field(body, "reason", required=False, default=None)
    record = services.hearing(record_id)
    if record["status"] != "SCHEDULED":
        raise ApiError("ERR_HEARING_NOT_SCHEDULED", "Only a scheduled hearing may be cancelled.")
    record["status"] = "CANCELLED"
    store.touch(record)
    return envelope.ok(record)


@bp.post("/public-hearings/<record_id>/reschedule")
def reschedule_hearing(record_id):
    auth.identity(["IntakeAnalyst"])
    body = shape.body()
    start_raw, start_at = shape.instant_field(body, "scheduled_start_at")
    end_raw, end_at = shape.instant_field(body, "scheduled_end_at")
    room_id = shape.string_field(body, "hearing_room_id", required=False, default=None)
    if not end_at > start_at:
        shape.bad("Field 'scheduled_end_at' must be strictly after 'scheduled_start_at'.")

    record = services.hearing(record_id)
    if room_id is not None:
        room = services.hearing_room(room_id)
    else:
        room = services.hearing_room(record["hearing_room_id"])

    if record["status"] != "CANCELLED":
        raise ApiError("ERR_HEARING_NOT_RESCHEDULABLE",
                       "Only a cancelled hearing may be rescheduled.")

    occupancy_start = _occupancy_start(start_at, room)
    _require_room_free(room["id"], occupancy_start, end_at, exclude_id=record["id"])

    record["hearing_room_id"] = room["id"]
    record["scheduled_start_at"] = start_raw
    record["scheduled_end_at"] = end_raw
    record["occupancy_start_at"] = clock.fmt(occupancy_start)
    record["reschedule_count"] = record["reschedule_count"] + 1
    record["status"] = "SCHEDULED"
    store.touch(record)
    return envelope.ok(record)


@bp.post("/public-hearings/<record_id>/conclude")
def conclude_hearing(record_id):
    auth.identity(["IntakeAnalyst"])
    body = shape.body()
    attendees = shape.int_field(body, "attendee_count", minimum=0)
    transcript = shape.string_field(body, "transcript_reference")
    record = services.hearing(record_id)
    if record["status"] != "SCHEDULED":
        raise ApiError("ERR_HEARING_NOT_SCHEDULED", "Only a scheduled hearing may be concluded.")
    if clock.now() < clock.parse_instant(record["scheduled_end_at"]):
        raise ApiError("ERR_HEARING_NOT_CONCLUDABLE",
                       "The session has not finished yet.")
    record["attendee_count"] = attendees
    record["transcript_reference"] = transcript
    record["status"] = "HELD"
    store.touch(record)
    return envelope.ok(record)
