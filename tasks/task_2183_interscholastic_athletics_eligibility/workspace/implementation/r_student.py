"""Students: enrolment, academic records, reads."""
from flask import Blueprint, request

from core import (
    DB, ALL_ROLES, auth, own, body, ok, ok_list, fail, req_str, req_num, req_int,
    opt_str, opt_bool, req_date, opt_date, new_record, touch, now, pagination,
    paginate, by_created, get_school, get_student, ser_student,
)

bp = Blueprint("students", __name__)


@bp.post("/athletics/students")
def create_student():
    p = auth(["SchoolAthleticDirector"])
    b = body()
    # tier 3 - ownership against the body's school_id
    raw_school = b.get("school_id")
    if isinstance(raw_school, str):
        own(p, raw_school)
    # tier 5 - body reference existence
    if isinstance(raw_school, str):
        get_school(raw_school)
    raw_prev = b.get("previous_school_id")
    if isinstance(raw_prev, str):
        get_school(raw_prev)
    # tier 6 - body shape
    school_id = req_str(b, "school_id")
    full_name = req_str(b, "full_name")
    birth_date = req_date(b, "birth_date")
    grade_level = req_int(b, "grade_level", minimum=9, maximum=12)
    previous_school_id = opt_str(b, "previous_school_id", None)
    residency_verified = opt_bool(b, "residency_verified", False)
    residency_verified_on = opt_date(b, "residency_verified_on", None)
    transfer_date = opt_date(b, "transfer_date", None)
    hardship = opt_bool(b, "hardship_waiver_granted", False)
    frl = opt_bool(b, "free_reduced_lunch", False)
    if not residency_verified:
        residency_verified_on = None

    rec = new_record({
        "school_id": school_id,
        "previous_school_id": previous_school_id,
        "full_name": full_name,
        "birth_date": birth_date,
        "grade_level": grade_level,
        "residency_verified": residency_verified,
        "residency_verified_on": residency_verified_on,
        "transfer_date": transfer_date,
        "hardship_waiver_granted": hardship,
        "free_reduced_lunch": frl,
        "gpa_prior_period": None,
        "gpa_current_period": None,
        "credits_prior_period": 0,
        "credits_current_period": 0,
        "academic_record_submitted_by": None,
        "academic_record_submitted_at": None,
    })
    DB.students[rec["id"]] = rec
    return ok(ser_student(rec), 201)


@bp.post("/athletics/students/<sid>/academic-record")
def post_academic_record(sid):
    p = auth(["Registrar"])
    student = get_student(sid)
    own(p, student["school_id"])
    b = body()
    gpa_prior = req_num(b, "gpa_prior_period", minimum="0.000", maximum="4.000")
    gpa_current = req_num(b, "gpa_current_period", minimum="0.000", maximum="4.000")
    credits_prior = req_int(b, "credits_prior_period", minimum=0)
    credits_current = req_int(b, "credits_current_period", minimum=0)

    student["gpa_prior_period"] = gpa_prior
    student["gpa_current_period"] = gpa_current
    student["credits_prior_period"] = credits_prior
    student["credits_current_period"] = credits_current
    student["academic_record_submitted_by"] = p.user_id
    student["academic_record_submitted_at"] = now()
    touch(student)
    return ok(ser_student(student))


@bp.get("/athletics/students/<sid>")
def read_student(sid):
    auth(ALL_ROLES)
    return ok(ser_student(get_student(sid)))


@bp.get("/athletics/students")
def list_students():
    auth(ALL_ROLES)
    limit, offset = pagination()
    rows = list(DB.students.values())
    school_id = request.args.get("school_id")
    if school_id is not None:
        rows = [s for s in rows if s["school_id"] == school_id]
    prev = request.args.get("previous_school_id")
    if prev is not None:
        rows = [s for s in rows if s["previous_school_id"] == prev]
    rows = by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_student(s) for s in page], limit, offset, total)
