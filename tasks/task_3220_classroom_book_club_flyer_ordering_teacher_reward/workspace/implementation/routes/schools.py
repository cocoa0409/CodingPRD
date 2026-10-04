"""School endpoints: CRUD, program enrollment, suspension cascade, reverse listings."""

from flask import Blueprint

import db
from errors import raise_err
from middleware import require_roles
from response import object_response, list_response, paginate
from services import (
    new_record, touch, serialize_school, serialize_teacher, serialize_cycle,
    serialize_fair, serialize_donation, serialize_enrollment, parse_date,
    school_posture, cascade_suspend_school,
)
from routes.common import get_body, path_get, req_field

bp = Blueprint("schools", __name__)


@bp.post("/club/schools")
@require_roles("ClubAdmin")
def create_school():
    body = get_body()
    name = req_field(body, "name")
    address = req_field(body, "address")
    low_income = body.get("low_income_program", False)
    if not isinstance(low_income, bool):
        raise_err("ERR_INVALID_REQUEST", "low_income_program must be a boolean")
    school = new_record({"name": name, "address": address, "low_income_program": low_income})
    db.schools[school["id"]] = school
    return object_response(serialize_school(school), 201)


@bp.get("/club/schools")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher", "Parent", "Donor")
def list_schools():
    items = sorted(db.schools.values(), key=lambda s: (s["created_at"], s["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_school(s) for s in page], total, limit, offset))


@bp.get("/club/schools/<sid>")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher", "Parent", "Donor")
def get_school(sid):
    return object_response(serialize_school(path_get(db.schools, sid, "School")))


@bp.get("/club/schools/<sid>/teachers")
@require_roles("ClubAdmin", "SchoolAdmin")
def school_teachers(sid):
    path_get(db.schools, sid, "School")
    items = sorted((t for t in db.teachers.values() if t["school_id"] == sid),
                   key=lambda t: (t["created_at"], t["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_teacher(t) for t in page], total, limit, offset))


@bp.get("/club/schools/<sid>/flyer-cycles")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher")
def school_cycles(sid):
    from flask import request
    path_get(db.schools, sid, "School")
    items = [c for c in db.flyer_cycles.values() if c["school_id"] == sid]
    gb = request.args.get("grade_band")
    st = request.args.get("status")
    if gb:
        items = [c for c in items if c["grade_band"] == gb]
    if st:
        items = [c for c in items if c["status"] == st]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_cycle(c) for c in page], total, limit, offset))


@bp.get("/club/schools/<sid>/book-fairs")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher")
def school_fairs(sid):
    from flask import request
    path_get(db.schools, sid, "School")
    items = [f for f in db.book_fairs.values() if f["school_id"] == sid]
    st = request.args.get("status")
    if st:
        items = [f for f in items if f["status"] == st]
    items.sort(key=lambda f: (f["created_at"], f["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_fair(f) for f in page], total, limit, offset))


@bp.get("/club/schools/<sid>/donation-requests")
@require_roles("ClubAdmin", "SchoolAdmin", "Donor")
def school_donations(sid):
    from flask import request
    path_get(db.schools, sid, "School")
    items = [d for d in db.donation_requests.values() if d["school_id"] == sid]
    st = request.args.get("status")
    if st:
        items = [d for d in items if d["status"] == st]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_donation(d) for d in page], total, limit, offset))


@bp.get("/club/schools/<sid>/enrollments")
@require_roles("ClubAdmin", "SchoolAdmin")
def school_enrollments(sid):
    path_get(db.schools, sid, "School")
    items = sorted((e for e in db.enrollments.values() if e["school_id"] == sid),
                   key=lambda e: (e["created_at"], e["id"]))
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_enrollment(e) for e in page], total, limit, offset))


@bp.post("/club/schools/<sid>/enroll-program")
@require_roles("ClubAdmin")
def enroll_program(sid):
    path_get(db.schools, sid, "School")
    body = get_body()
    enrolled_on = req_field(body, "enrolled_on")
    parse_date(enrolled_on, "enrolled_on")
    for e in db.enrollments.values():
        if e["school_id"] == sid and e["status"] == "ACTIVE":
            raise_err("ERR_ENROLLMENT_EXISTS", "School already has an ACTIVE enrollment")
    enr = new_record({"school_id": sid, "status": "ACTIVE", "enrolled_on": enrolled_on})
    db.enrollments[enr["id"]] = enr
    return object_response(serialize_enrollment(enr), 201)


@bp.post("/club/schools/<sid>/suspend-program")
@require_roles("ClubAdmin")
def suspend_program(sid):
    path_get(db.schools, sid, "School")
    if school_posture(sid) != "NORMAL":
        raise_err("ERR_INVALID_STATE", "School posture is not NORMAL")
    active = [e for e in db.enrollments.values()
              if e["school_id"] == sid and e["status"] == "ACTIVE"]
    if not active:
        raise_err("ERR_INVALID_STATE", "School has no ACTIVE enrollment")
    enr = active[0]
    enr["status"] = "SUSPENDED"
    touch(enr)
    cascade_suspend_school(sid)
    school = db.schools[sid]
    touch(school)
    return object_response(serialize_school(school))


@bp.post("/club/schools/<sid>/reinstate-program")
@require_roles("ClubAdmin")
def reinstate_program(sid):
    path_get(db.schools, sid, "School")
    if school_posture(sid) != "RESTRICTED":
        raise_err("ERR_INVALID_STATE", "School posture is not RESTRICTED")
    susp = [e for e in db.enrollments.values()
            if e["school_id"] == sid and e["status"] == "SUSPENDED"]
    if susp:
        enr = susp[0]
        enr["status"] = "ACTIVE"
        touch(enr)
    school = db.schools[sid]
    touch(school)
    return object_response(serialize_school(school))
