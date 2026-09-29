"""Land-use applications (PRD 3.1): the draft / submit / decide loop."""

from flask import Blueprint, g

import auth
import db
import validation
from errors import fail
from routes import common
from services import cascade

bp = Blueprint("permits", __name__)

SUBMITTABLE_STATUSES = ("DRAFT", "REVISION_REQUESTED")


@bp.post("/ocr/venues/<venue_id>/permits")
def draft_permit(venue_id):
    auth.require(auth.COURSE_DESIGNER)
    venue = validation.path_venue(venue_id)
    payload = validation.body()
    permit_number = validation.field_str(payload, "permit_number", 1)
    water_use_allowed = validation.field_bool(payload, "water_use_allowed")
    max_disturbed = validation.field_int(payload, "max_disturbed_area_sqm", minimum=1)
    quiet_start = validation.field_int(
        payload, "quiet_hours_start_hour_utc", minimum=0, maximum=23
    )
    quiet_end = validation.field_int(payload, "quiet_hours_end_hour_utc", minimum=0, maximum=23)
    valid_until = validation.field_datetime(payload, "valid_until_utc")
    restoration_deadline = validation.field_datetime(payload, "restoration_deadline_utc")

    # Rung 22: permit_number is unique across every application ever filed.
    for peer in db.all_rows("permits"):
        if peer["permit_number"] == permit_number:
            fail("ERR_UNIQUENESS_CONFLICT", "permit_number %s is already filed." % permit_number)

    row = db.insert(
        "permits",
        {
            "venue_id": venue["id"],
            "permit_number": permit_number,
            "water_use_allowed": water_use_allowed,
            "max_disturbed_area_sqm": max_disturbed,
            "quiet_hours_start_hour_utc": quiet_start,
            "quiet_hours_end_hour_utc": quiet_end,
            "valid_until_utc": valid_until,
            "restoration_deadline_utc": restoration_deadline,
            "status": "DRAFT",
            "submitted_by_user_id": None,
            "decided_by_user_id": None,
            "revision_rounds": 0,
            "decision_note": None,
        },
    )
    return common.created(row)


@bp.get("/ocr/venues/<venue_id>/permits")
def list_permits(venue_id):
    auth.require(*auth.OPERATOR_READERS)
    venue = validation.path_venue(venue_id)
    status = validation.query_enum("status", validation.PERMIT_STATUSES)
    rows = db.where("permits", venue_id=venue["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.listing(rows)


@bp.get("/ocr/permits/<permit_id>")
def read_permit(permit_id):
    auth.require(*auth.OPERATOR_READERS)
    permit = validation.path_permit(permit_id)
    return common.ok(permit)


@bp.post("/ocr/permits/<permit_id>/submit")
def submit_permit(permit_id):
    auth.require(auth.COURSE_DESIGNER)
    permit = validation.path_permit(permit_id)
    venue = common.venue_of(permit)

    if permit["status"] not in SUBMITTABLE_STATUSES:
        fail("ERR_PERMIT_STATE_INVALID", "A %s application cannot be submitted." % permit["status"])
    common.require_venue_open(venue)

    with db.mutation(permit) as row:
        row["status"] = "SUBMITTED"
        row["submitted_by_user_id"] = g.user_id
    return common.ok(permit)


@bp.post("/ocr/permits/<permit_id>/decision")
def decide_permit(permit_id):
    auth.require(auth.PERMIT_OFFICER)
    permit = validation.path_permit(permit_id)
    venue = common.venue_of(permit)
    payload = validation.body()
    decision = validation.field_enum(payload, "decision", validation.PERMIT_DECISIONS)
    note = validation.field_str(payload, "decision_note", min_len=0, default=None)

    # Rung 7: the submitter may never decide its own application (PRD 2.7).
    if permit["submitted_by_user_id"] is not None and permit["submitted_by_user_id"] == g.user_id:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "Operator %s submitted this application and may not decide it." % g.user_id,
        )

    # Rung 9: only a SUBMITTED application admits a decision.
    if permit["status"] != "SUBMITTED":
        fail("ERR_PERMIT_STATE_INVALID", "A %s application cannot be decided." % permit["status"])

    if decision == "APPROVED":
        for peer in db.where("permits", venue_id=permit["venue_id"]):
            if peer["id"] != permit["id"] and peer["status"] == "APPROVED":
                fail(
                    "ERR_PERMIT_ALREADY_APPROVED",
                    "Application %s already governs this parcel." % peer["id"],
                )

    with db.mutation(permit) as row:
        row["decided_by_user_id"] = g.user_id
        if note is not None:
            row["decision_note"] = note
        if decision == "APPROVED":
            row["status"] = "APPROVED"
        elif decision == "REVISION_REQUESTED":
            row["status"] = "REVISION_REQUESTED"
            row["revision_rounds"] = int(row["revision_rounds"]) + 1
        else:
            row["status"] = "DENIED"

    if decision == "APPROVED":
        cascade.recompute_venue_courses_readiness(venue)
    elif decision == "DENIED":
        cascade.freeze_venue(venue)

    return common.ok(permit)
