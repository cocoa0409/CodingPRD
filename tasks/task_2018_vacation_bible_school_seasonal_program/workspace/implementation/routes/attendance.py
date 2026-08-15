"""Attendance check-in/out, security tags, reprint (PRD §3.7)."""

from datetime import datetime, timezone

from flask import Blueprint, request

import clock
import store
from auth import authenticate, require_role
from derived import (
    attendance_view,
    security_tag_view,
    record_for,
    next_tag_code,
    child_has_approved_plan,
    tags_of_day,
)
from envelope import ok_object
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ACCOMMODATION_NOT_APPROVED,
    ERR_NOT_ENROLLED,
    ERR_TAG_MISMATCH,
    ERR_TAG_NOT_ACTIVE,
    ERR_FORBIDDEN,
)
from routes.common import paginate
from validate import Field, get_body, validate_body

bp = Blueprint("attendance", __name__)

_CHECKIN_SPEC = {
    "child_id": Field("str", required=True),
    "program_day_id": Field("str", required=True),
}

_CHECKOUT_SPEC = {
    "child_id": Field("str", required=True),
    "program_day_id": Field("str", required=True),
    "tag_code": Field("str", required=True),
    "pickup_person": Field("str", required=True),
}

_REPRINT_SPEC = {
    "child_id": Field("str", required=True),
    "program_day_id": Field("str", required=True),
}

_ATT_READ = ("ProgramDirector", "RegistrationCoordinator", "SafetyOfficer", "CheckInStaff")


def _enrolled_registration(child_id, program_id):
    classroom_ids = {
        c["id"] for c in store.all_of("classrooms") if c["program_id"] == program_id
    }
    for reg in store.all_of("registrations"):
        if (
            reg["child_id"] == child_id
            and reg["classroom_id"] in classroom_ids
            and reg["status"] == "ENROLLED"
        ):
            return reg
    return None


def _mint_tag(child_id, program_day_id):
    tag = store.new_record(
        child_id=child_id,
        program_day_id=program_day_id,
        tag_code=next_tag_code(program_day_id),
        status="ISSUED",
        void_reason=None,
        issued_at=clock.now(),
        redeemed_at=None,
    )
    store.put("security_tags", tag)
    return tag


def _resolve_child_and_day(body_spec):
    """P0 + P1 + P2 + P3 shared by the three front-desk actions.

    Existence follows the reference hierarchy: the day before the child.
    """
    body = get_body()
    data = validate_body(body, body_spec)
    ctx = authenticate()
    require_role(ctx, "CheckInStaff")
    day = store.get("program_days", data["program_day_id"])
    if day is None:
        raise_err(ERR_NOT_FOUND, "program day not found")
    child = store.get("children", data["child_id"])
    if child is None:
        raise_err(ERR_NOT_FOUND, "child not found")
    return ctx, data, day, child


@bp.post("/vbs/attendance/check-in")
def check_in():
    ctx, data, day, child = _resolve_child_and_day(_CHECKIN_SPEC)
    # P5 safety gate first: special-needs children need an APPROVED plan.
    if child["has_special_needs"] and not child_has_approved_plan(child["id"]):
        raise_err(ERR_ACCOMMODATION_NOT_APPROVED, "no APPROVED accommodation plan on file")
    # P6 state: the day must be OPEN; an existing record must be NOT_ARRIVED.
    if day["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "the program day is not OPEN")
    record = record_for(child["id"], day["id"])
    if record is not None and record["status"] != "NOT_ARRIVED":
        raise_err(ERR_INVALID_STATE, "the attendance record is not NOT_ARRIVED")
    # P8: enrollment. When no record exists on an OPEN day, this check decides.
    reg = _enrolled_registration(child["id"], day["program_id"])
    if reg is None:
        raise_err(ERR_NOT_ENROLLED, "child holds no ENROLLED registration for this program")
    if record is None:
        record = store.new_record(
            child_id=child["id"],
            program_day_id=day["id"],
            registration_id=reg["id"],
            status="NOT_ARRIVED",
            tag_code=None,
            checked_in_at=None,
            checked_out_at=None,
            checked_in_by=None,
            checked_out_by=None,
            pickup_person=None,
            late_pickup=False,
        )
        store.put("attendance_records", record)
    record["status"] = "CHECKED_IN"
    record["checked_in_at"] = clock.now()
    record["checked_in_by"] = ctx.user_id
    tag = _mint_tag(child["id"], day["id"])
    record["tag_code"] = tag["tag_code"]
    store.touch(record)
    return ok_object(attendance_view(record), status=201)


@bp.post("/vbs/attendance/check-out")
def check_out():
    ctx, data, day, child = _resolve_child_and_day(_CHECKOUT_SPEC)
    record = record_for(child["id"], day["id"])
    if record is None or record["status"] != "CHECKED_IN":
        raise_err(ERR_INVALID_STATE, "the attendance record is not CHECKED_IN")
    # P8: match the presented code against the day's tags for this child.
    matched = None
    for tag in tags_of_day(day["id"]):
        if tag["child_id"] == child["id"] and tag["tag_code"] == data["tag_code"]:
            matched = tag
            break
    if matched is None:
        raise_err(ERR_TAG_MISMATCH, "tag code matches no security tag for this child and day")
    if matched["status"] != "ISSUED":
        raise_err(ERR_TAG_NOT_ACTIVE, "tag code belongs to a VOIDED or REDEEMED tag")
    now = clock.now()
    record["status"] = "CHECKED_OUT"
    record["checked_out_at"] = now
    record["checked_out_by"] = ctx.user_id
    record["pickup_person"] = data["pickup_person"]
    program = store.get("programs", day["program_id"])
    cutoff_time = program["pickup_cutoff_time"] if program else None
    if cutoff_time is not None:
        cutoff = datetime.combine(day["date"], cutoff_time, tzinfo=timezone.utc)
        record["late_pickup"] = now > cutoff
    else:
        record["late_pickup"] = False
    store.touch(record)
    matched["status"] = "REDEEMED"
    matched["redeemed_at"] = now
    store.touch(matched)
    return ok_object(attendance_view(record))


@bp.post("/vbs/attendance/reprint-tag")
def reprint_tag():
    ctx, data, day, child = _resolve_child_and_day(_REPRINT_SPEC)
    record = record_for(child["id"], day["id"])
    if record is None or record["status"] != "CHECKED_IN":
        raise_err(ERR_INVALID_STATE, "reprint requires a CHECKED_IN child")
    for tag in tags_of_day(day["id"]):
        if tag["child_id"] == child["id"] and tag["status"] == "ISSUED":
            tag["status"] = "VOIDED"
            tag["void_reason"] = "REPRINT"
            store.touch(tag)
    replacement = _mint_tag(child["id"], day["id"])
    record["tag_code"] = replacement["tag_code"]
    store.touch(record)
    return ok_object(attendance_view(record))


@bp.get("/vbs/attendance/<record_id>")
def get_attendance(record_id):
    ctx = authenticate()
    require_role(ctx, *_ATT_READ, "Parent")
    record = store.get("attendance_records", record_id)
    if record is not None and ctx.role == "Parent":
        child = store.get("children", record["child_id"])
        if child is None or child["family_id"] != ctx.user_id:
            raise_err(ERR_FORBIDDEN, "parents may only read their own children's attendance")
    if record is None:
        raise_err(ERR_NOT_FOUND, "attendance record not found")
    return ok_object(attendance_view(record))


@bp.get("/vbs/attendance")
def list_attendance():
    ctx = authenticate()
    require_role(ctx, *_ATT_READ)
    items = list(store.all_of("attendance_records"))
    child_id = request.args.get("child_id")
    program_day_id = request.args.get("program_day_id")
    registration_id = request.args.get("registration_id")
    status = request.args.get("status")
    if child_id is not None:
        items = [r for r in items if r["child_id"] == child_id]
    if program_day_id is not None:
        items = [r for r in items if r["program_day_id"] == program_day_id]
    if registration_id is not None:
        items = [r for r in items if r["registration_id"] == registration_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate(items, attendance_view)


@bp.get("/vbs/security-tags/<tag_id>")
def get_tag(tag_id):
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "SafetyOfficer", "CheckInStaff")
    tag = store.get("security_tags", tag_id)
    if tag is None:
        raise_err(ERR_NOT_FOUND, "security tag not found")
    return ok_object(security_tag_view(tag))


@bp.get("/vbs/security-tags")
def list_tags():
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "SafetyOfficer", "CheckInStaff")
    items = list(store.all_of("security_tags"))
    child_id = request.args.get("child_id")
    program_day_id = request.args.get("program_day_id")
    status = request.args.get("status")
    if child_id is not None:
        items = [t for t in items if t["child_id"] == child_id]
    if program_day_id is not None:
        items = [t for t in items if t["program_day_id"] == program_day_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return paginate(items, security_tag_view)
