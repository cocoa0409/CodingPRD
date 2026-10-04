"""School group reservations (PRD 3.3): synchronous CONFIRMED/WAITLISTED
resolution at creation, and cancellation with the promotion waterfall."""

from flask import Blueprint

import calc
import db
import serializers
import util
from envelope import listing, success
from errors import fail
from middleware import auth, get_or_404, require_role

bp = Blueprint("school_reservations", __name__)

RESERVATION_READ_ROLES = ["PlatformAdmin", "ProgramCoordinator", "Public"]


@bp.post("/campus/school-reservations")
def create_reservation():
    uid, role = auth()
    require_role(role, ["Public"])
    b = util.body()
    # (4) body FK existence (museum_id and program_id, when provided)
    museum_id = b.get("museum_id")
    program_id = b.get("program_id")
    museum = None
    program = None
    if museum_id is not None:
        museum = get_or_404("museums", museum_id, "Museum")
    if program_id is not None:
        program = get_or_404("education_programs", program_id, "EducationProgram")
    # State gate: a reservation against a cancelled program is rejected.
    if program is not None and program["status"] != "SCHEDULED":
        fail("ERR_PROGRAM_NOT_SCHEDULED", "The program is not SCHEDULED")
    # (9) request shape
    if museum_id is None:
        fail("ERR_INVALID_REQUEST", "Missing required field: museum_id")
    if program_id is None:
        fail("ERR_INVALID_REQUEST", "Missing required field: program_id")
    school_name = util.req_str(b, "school_name")
    headcount = util.req_int(b, "headcount", minimum=1)
    visit_date = util.req_date(b, "visit_date")
    # (13) closure dates on the reservation's museum
    if visit_date in museum["closed_dates"]:
        fail("ERR_MUSEUM_CLOSED_ON_DATE", "Museum is closed on the requested visit date")
    # (16) hard cap on a single reservation's headcount
    if headcount > program["max_group_size"]:
        fail("ERR_GROUP_TOO_LARGE", "headcount exceeds the program's max_group_size")
    # The visit date must fall on the program's weekly recurrence day.
    if util.weekday_code(util.parse_date(visit_date)) != program["day_of_week"]:
        fail(
            "ERR_PROGRAM_DAY_MISMATCH",
            "visit_date does not fall on the program's day_of_week",
        )
    r = db.new_entity(
        {
            "museum_id": museum["id"],
            "program_id": program["id"],
            "school_name": school_name,
            "headcount": headcount,
            "visit_date": visit_date,
            "status": None,  # resolved synchronously below; never stored REQUESTED
            "created_by_user_id": uid,
        }
    )
    r["status"] = calc.evaluate_reservation_status(
        program, headcount, visit_date, r["created_at"], r["_seq"]
    )
    db.STORE["school_reservations"][r["id"]] = r
    return success(serializers.school_reservation(r), 201)


@bp.get("/campus/school-reservations")
def list_reservations():
    _uid, role = auth()
    require_role(role, RESERVATION_READ_ROLES)
    limit, offset = util.pagination()
    f_museum = util.request.args.get("museum_id")
    f_program = util.request.args.get("program_id")
    rows = []
    for r in db.all_sorted("school_reservations"):
        if f_museum is not None and r["museum_id"] != f_museum:
            continue
        if f_program is not None and r["program_id"] != f_program:
            continue
        rows.append(r)
    page = rows[offset : offset + limit]
    return listing([serializers.school_reservation(r) for r in page], limit, offset, len(rows))


@bp.get("/campus/school-reservations/<rid>")
def get_reservation(rid):
    _uid, role = auth()
    require_role(role, RESERVATION_READ_ROLES)
    r = get_or_404("school_reservations", rid, "SchoolGroupReservation")
    return success(serializers.school_reservation(r))


@bp.post("/campus/school-reservations/<rid>/cancel")
def cancel_reservation(rid):
    uid, role = auth()
    require_role(role, ["Public", "ProgramCoordinator"])
    r = get_or_404("school_reservations", rid, "SchoolGroupReservation")
    # Ownership (PRD 2.1): a Public organizer cancels only their own reservation;
    # a ProgramCoordinator may cancel any.
    if role == "Public" and r["created_by_user_id"] != uid:
        fail(
            "ERR_UNAUTHORIZED_ROLE",
            "Public callers may cancel only their own reservations",
        )
    if r["status"] not in ("CONFIRMED", "WAITLISTED"):
        fail("ERR_INVALID_STATE", "Only a CONFIRMED or WAITLISTED reservation can be cancelled")
    was_confirmed = r["status"] == "CONFIRMED"
    r["status"] = "CANCELLED"
    db.touch(r)
    # Cancelling a CONFIRMED reservation releases capacity and re-runs the
    # waitlist waterfall; cancelling a WAITLISTED entry simply dequeues it.
    if was_confirmed:
        calc.promote_waitlist(r["program_id"], r["visit_date"])
    return success(serializers.school_reservation(r))
