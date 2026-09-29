"""Volunteer crew staffing (PRD 3.5)."""

from flask import Blueprint

import calc
import constants as C
import db
import middleware
import support
import validation
from errors import ApiError, invalid_transition, not_found

bp = Blueprint("crew", __name__)

READ_ROLES = (C.ROLE_CENTER_ADMIN, C.ROLE_SCHEDULING_COORDINATOR, C.ROLE_PRODUCER)


@bp.post("/crew-assignments")
def create_assignment():
    middleware.authorize(C.ROLE_SCHEDULING_COORDINATOR)
    body = validation.body()
    slot_id = validation.req_id(body, "slot_id")
    volunteer_producer_id = validation.req_id(body, "volunteer_producer_id")
    crew_role = validation.req_enum(body, "crew_role", C.CREW_ROLES)
    if db.get("playback_slots", slot_id) is None:
        raise not_found("playback_slot", slot_id)
    if db.get("producers", volunteer_producer_id) is None:
        raise not_found("producer", volunteer_producer_id)
    row = db.new_row(
        "crew_assignments",
        {
            "slot_id": slot_id,
            "volunteer_producer_id": volunteer_producer_id,
            "crew_role": crew_role,
            "status": "OFFERED",
            "credited_hours_tenths": 0,
            "release_reason": None,
        },
    )
    return support.created("crew_assignments", row)


@bp.get("/crew-assignments/<assignment_id>")
def read_assignment(assignment_id):
    middleware.authorize(*READ_ROLES)
    row = support.must_exist("crew_assignments", assignment_id)
    return support.single("crew_assignments", row)


@bp.get("/crew-assignments")
def list_assignments():
    middleware.authorize(*READ_ROLES)
    slot_id = validation.query_string("slot_id")
    volunteer_producer_id = validation.query_string("volunteer_producer_id")
    status = validation.query_enum("status", C.CREW_STATUSES)
    validation.pagination()
    rows = support.filter_rows(
        "crew_assignments",
        [
            ("slot_id", slot_id),
            ("volunteer_producer_id", volunteer_producer_id),
            ("status", status),
        ],
    )
    return support.collection_response("crew_assignments", rows)


@bp.post("/crew-assignments/<assignment_id>/confirm")
def confirm_assignment(assignment_id):
    user_id, role = middleware.authorize(C.ROLE_PRODUCER, C.ROLE_SCHEDULING_COORDINATOR)
    validation.body()
    row = support.must_exist("crew_assignments", assignment_id)
    middleware.require_owner(row["volunteer_producer_id"], user_id, role)
    slot = db.get("playback_slots", row["slot_id"])
    if row["status"] != "OFFERED" or slot is None or slot["status"] != "SCHEDULED":
        raise invalid_transition("Only an offered assignment on a scheduled slot may be confirmed")
    volunteer = db.get("producers", row["volunteer_producer_id"])
    # priority 10
    if volunteer is None or volunteer["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCER_NOT_ACTIVE", "The volunteer's membership is not active")
    program = db.get("programs", slot["program_id"])
    # priority 16
    if (
        row["crew_role"] in C.LIVE_ROLES_REQUIRING_LIVE_CERT
        and program is not None
        and program["is_live"]
        and calc.certification_level(volunteer) != "LIVE"
    ):
        raise ApiError(
            "ERR_CERTIFICATION_INSUFFICIENT",
            "A LIVE certification is required for this role on a live slot",
        )
    # priority 33
    for other in db.all_rows("crew_assignments"):
        if other["id"] == row["id"] or other["status"] != "CONFIRMED":
            continue
        if other["volunteer_producer_id"] != row["volunteer_producer_id"]:
            continue
        other_slot = db.get("playback_slots", other["slot_id"])
        if other_slot is None or other_slot["id"] == slot["id"]:
            continue
        if calc.intervals_overlap(
            slot["start_at"], slot["end_at"], other_slot["start_at"], other_slot["end_at"]
        ):
            raise ApiError("ERR_CREW_TIME_CONFLICT", "The volunteer already holds an overlapping commitment")
    row["status"] = "CONFIRMED"
    db.bump(row)
    return support.single("crew_assignments", row)


@bp.post("/crew-assignments/<assignment_id>/release")
def release_assignment(assignment_id):
    user_id, role = middleware.authorize(C.ROLE_PRODUCER, C.ROLE_SCHEDULING_COORDINATOR)
    body = validation.body()
    release_reason = validation.req_string(body, "release_reason")
    row = support.must_exist("crew_assignments", assignment_id)
    middleware.require_owner(row["volunteer_producer_id"], user_id, role)
    if row["status"] not in ("OFFERED", "CONFIRMED"):
        raise invalid_transition("Only an offered or confirmed assignment may be released")
    slot = db.get("playback_slots", row["slot_id"])
    if row["status"] == "CONFIRMED" and slot is not None and slot["status"] == "AIRED":
        raise invalid_transition("A confirmed assignment may not be released once its slot has aired")
    row["status"] = "RELEASED"
    row["release_reason"] = release_reason
    db.bump(row)
    return support.single("crew_assignments", row)
