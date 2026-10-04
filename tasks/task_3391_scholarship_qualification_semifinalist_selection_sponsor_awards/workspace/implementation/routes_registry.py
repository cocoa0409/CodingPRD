"""Registry endpoints: schools, students, corporate sponsors, college
institutions."""

from flask import Blueprint, g, request

import constants as C
from errors import err
from helpers import (
    apply_filters,
    bad,
    body,
    check_enum_field,
    check_int_field,
    created_key,
    is_int,
    paginate,
    require_present,
    require_roles,
    resp_object,
)
from serializers import ser_college, ser_school, ser_sponsor, ser_student
from store import base_record, db, iso_ts, new_id, next_seq, wall_now

bp = Blueprint("registry", __name__)


# --------------------------------------------------------------------------
# Schools
# --------------------------------------------------------------------------

@bp.route("/api/schools", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def create_school():
    b = body()
    require_present(b, "name", "school_code", "state_code")
    for f in ("name", "school_code", "state_code"):
        if not isinstance(b[f], str):
            bad("%s must be a string" % f)
    for s in db["schools"].values():
        if s["school_code"] == b["school_code"]:
            bad("school_code must be unique")
    # School is the common-fields exception: id and created_at only.
    rec = {
        "id": new_id(),
        "created_at": iso_ts(wall_now()),
        "_seq": next_seq(),
        "name": b["name"],
        "school_code": b["school_code"],
        "state_code": b["state_code"],
    }
    db["schools"][rec["id"]] = rec
    return resp_object(ser_school(rec), code=201)


# --------------------------------------------------------------------------
# Students
# --------------------------------------------------------------------------

@bp.route("/api/students", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def create_student():
    b = body()
    # Body-referenced ids must exist (priority 4): school_id, parent_sponsor_id.
    if b.get("school_id") is not None and b["school_id"] not in db["schools"]:
        bad("referenced school_id does not exist")
    if b.get("parent_sponsor_id") is not None and b["parent_sponsor_id"] not in db["sponsors"]:
        bad("referenced parent_sponsor_id does not exist")
    # Field shape (priority 10).
    require_present(
        b,
        "full_name",
        "school_id",
        "state_code",
        "graduation_year",
        "citizenship_status",
        "enrollment_status",
    )
    if not isinstance(b["full_name"], str):
        bad("full_name must be a string")
    if not isinstance(b["state_code"], str):
        bad("state_code must be a string")
    check_int_field(b, "graduation_year")
    check_enum_field(b, "citizenship_status", C.CITIZENSHIP_STATUSES)
    check_enum_field(b, "enrollment_status", C.ENROLLMENT_STATUSES)
    rec = base_record()
    rec.update(
        {
            "full_name": b["full_name"],
            "school_id": b["school_id"],
            "state_code": b["state_code"],
            "graduation_year": b["graduation_year"],
            "citizenship_status": b["citizenship_status"],
            "enrollment_status": b["enrollment_status"],
            "parent_sponsor_id": b.get("parent_sponsor_id"),
        }
    )
    db["students"][rec["id"]] = rec
    return resp_object(ser_student(rec), code=201)


@bp.route("/api/students/<student_id>", methods=["GET"])
@require_roles(*C.ALL_ROLES)
def get_student(student_id):
    # Student acts only on own records (path id vs X-User-ID, priority 3).
    if g.user_role == C.ROLE_STUDENT and g.user_id != student_id:
        err("ERR_FORBIDDEN_OWNERSHIP", "students may only read their own record")
    rec = db["students"].get(student_id)
    if rec is None:
        err("ERR_NOT_FOUND", "student not found")
    return resp_object(ser_student(rec))


@bp.route("/api/students", methods=["GET"])
@require_roles(C.ROLE_PROGRAM_ADMIN, C.ROLE_SCHOOL_OFFICIAL)
def list_students():
    records = sorted(db["students"].values(), key=created_key)
    records = apply_filters(
        records,
        [
            ("school_id", request.args.get("school_id")),
            ("parent_sponsor_id", request.args.get("parent_sponsor_id")),
            ("state_code", request.args.get("state_code")),
        ],
    )
    return paginate(records, ser_student)


# --------------------------------------------------------------------------
# Corporate sponsors
# --------------------------------------------------------------------------

@bp.route("/api/corporate-sponsors", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def create_sponsor():
    b = body()
    require_present(b, "legal_name", "sponsor_code")
    if not isinstance(b["legal_name"], str):
        bad("legal_name must be a string")
    if not isinstance(b["sponsor_code"], str):
        bad("sponsor_code must be a string")
    for s in db["sponsors"].values():
        if s["sponsor_code"] == b["sponsor_code"]:
            bad("sponsor_code must be unique")
    rec = base_record()
    rec.update({"legal_name": b["legal_name"], "sponsor_code": b["sponsor_code"]})
    db["sponsors"][rec["id"]] = rec
    return resp_object(ser_sponsor(rec), code=201)


# --------------------------------------------------------------------------
# College institutions
# --------------------------------------------------------------------------

@bp.route("/api/college-institutions", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def create_college():
    b = body()
    require_present(
        b,
        "legal_name",
        "college_code",
        "award_amount_cents",
        "renewable_years_total",
        "terms_per_year",
        "pool_total_cents",
        "max_awards",
    )
    if not isinstance(b["legal_name"], str):
        bad("legal_name must be a string")
    if not isinstance(b["college_code"], str):
        bad("college_code must be a string")
    for c in db["colleges"].values():
        if c["college_code"] == b["college_code"]:
            bad("college_code must be unique")
    check_int_field(b, "award_amount_cents", minimum=1)
    check_int_field(b, "renewable_years_total", minimum=2)
    check_int_field(b, "terms_per_year", minimum=1)
    check_int_field(b, "max_awards", minimum=1)
    check_int_field(b, "pool_total_cents", minimum=0)
    if b["pool_total_cents"] < b["award_amount_cents"] * b["renewable_years_total"]:
        bad("pool_total_cents must be at least award_amount_cents * renewable_years_total")
    rec = base_record()
    rec.update(
        {
            "legal_name": b["legal_name"],
            "college_code": b["college_code"],
            "award_amount_cents": b["award_amount_cents"],
            "renewable_years_total": b["renewable_years_total"],
            "terms_per_year": b["terms_per_year"],
            "pool_total_cents": b["pool_total_cents"],
            "max_awards": b["max_awards"],
            "pool_committed_cents": 0,
            "pool_paid_cents": 0,
            "pool_available_reserved_cents": b["pool_total_cents"],
            "pool_available_cash_cents": b["pool_total_cents"],
            "status": "ACTIVE",
        }
    )
    db["colleges"][rec["id"]] = rec
    return resp_object(ser_college(rec), code=201)


@bp.route("/api/college-institutions/<college_id>", methods=["GET"])
@require_roles(C.ROLE_PROGRAM_ADMIN, C.ROLE_COLLEGE_ADMIN)
def get_college(college_id):
    rec = db["colleges"].get(college_id)
    if rec is None:
        err("ERR_NOT_FOUND", "college institution not found")
    return resp_object(ser_college(rec))
