"""Enrollment, the two student status axes and subscription terms (PRD 3.3)."""
from flask import Blueprint, request

import db as store
from db import db, new_row, touch
from errors import ApiError, bad_request
from middleware import (ROLE_FACULTY_MENTOR, ROLE_FINANCIAL_AID_OFFICER,
                        ROLE_INTEGRITY_OFFICER, ROLE_PLATFORM_ADMIN,
                        ROLE_REGISTRAR, ROLE_STUDENT, check_student_ownership,
                        require)
from response import json_body, created_response, object_response, paginated
from services import cascade, derive, lookup, serialize, shape

bp = Blueprint("students", __name__)

READ_STUDENT_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN, ROLE_FACULTY_MENTOR,
                      ROLE_INTEGRITY_OFFICER, ROLE_FINANCIAL_AID_OFFICER,
                      ROLE_STUDENT)
LIST_STUDENT_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN, ROLE_FACULTY_MENTOR,
                      ROLE_INTEGRITY_OFFICER, ROLE_FINANCIAL_AID_OFFICER)
SUMMARY_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN, ROLE_FACULTY_MENTOR,
                 ROLE_FINANCIAL_AID_OFFICER, ROLE_STUDENT)
READ_TERM_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN,
                   ROLE_FINANCIAL_AID_OFFICER, ROLE_FACULTY_MENTOR,
                   ROLE_STUDENT)
LIST_TERM_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN,
                   ROLE_FINANCIAL_AID_OFFICER, ROLE_FACULTY_MENTOR)

ENROLLMENT_STATUSES = ("APPLICANT", "ACTIVE", "SUSPENDED", "WITHDRAWN",
                       "GRADUATED")
SAP_STATUSES = ("GOOD_STANDING", "WARNING", "PROBATION", "DISMISSED")
TERM_STATUSES = ("PENDING", "ACTIVE", "COMPLETED", "LAPSED", "CANCELLED")
CLOSED_ENROLLMENT = ("WITHDRAWN", "GRADUATED")


def _arg(name):
    raw = request.args.get(name, None)
    if raw is None:
        return None
    text = raw.strip()
    return text if text else None


# ------------------------------------------------------------------ students

@bp.route("/students", methods=["POST"])
def create_student():
    require(ROLE_REGISTRAR)
    body = json_body()
    program = lookup.program(shape.req_id(body, "program_id"))
    full_name = shape.req_str(body, "full_name")
    email = shape.req_str(body, "email")
    for existing in db.students.values():
        if existing["email"] == email:
            raise bad_request("A student with this email already exists.")
    if program["status"] != "PUBLISHED":
        raise ApiError("ERR_PROGRAM_NOT_PUBLISHED")
    row = new_row()
    row.update({
        "program_id": program["id"],
        "full_name": full_name,
        "email": email,
        "enrollment_status": "APPLICANT",
        "sap_status": "GOOD_STANDING",
        "activated_at_utc": None,
        "suspended_at_utc": None,
        "withdrawn_at_utc": None,
        "graduated_at_utc": None,
    })
    db.students[row["id"]] = row
    return created_response(serialize.student(row))


@bp.route("/students/<sid>", methods=["GET"])
def read_student(sid):
    caller = require(*READ_STUDENT_ROLES)
    check_student_ownership(caller, sid)
    return object_response(serialize.student(lookup.student(sid)))


@bp.route("/students", methods=["GET"])
def list_students():
    require(*LIST_STUDENT_ROLES)
    program_id = _arg("program_id")
    enrollment_status = _arg("enrollment_status")
    sap_status = _arg("sap_status")
    rows = []
    for row in db.students.values():
        if program_id is not None and row["program_id"] != program_id:
            continue
        if (enrollment_status is not None
                and row["enrollment_status"] != enrollment_status):
            continue
        if sap_status is not None and row["sap_status"] != sap_status:
            continue
        rows.append(row)
    return paginated(store.by_created(rows), serialize.student)


@bp.route("/students/<sid>/activate", methods=["POST"])
def activate_student(sid):
    require(ROLE_REGISTRAR)
    student = lookup.student(sid)
    if student["enrollment_status"] != "APPLICANT":
        raise ApiError("ERR_STUDENT_NOT_APPLICANT")
    program = lookup.program_of_student(student)
    if program is None or program["status"] != "PUBLISHED":
        raise ApiError("ERR_PROGRAM_NOT_PUBLISHED")
    student["enrollment_status"] = "ACTIVE"
    student["activated_at_utc"] = db.now()
    touch(student)
    return object_response(serialize.student(student))


@bp.route("/students/<sid>/reinstate", methods=["POST"])
def reinstate_student(sid):
    require(ROLE_REGISTRAR)
    student = lookup.student(sid)
    if student["enrollment_status"] != "SUSPENDED":
        raise ApiError("ERR_STUDENT_NOT_SUSPENDED")
    if derive.student_has_live_case(student["id"]):
        raise ApiError("ERR_INTEGRITY_HOLD_ACTIVE",
                       "An integrity matter for this student is unresolved.")
    student["enrollment_status"] = "ACTIVE"
    touch(student)
    return object_response(serialize.student(student))


@bp.route("/students/<sid>/suspend", methods=["POST"])
def suspend_student_route(sid):
    require(ROLE_REGISTRAR, ROLE_INTEGRITY_OFFICER)
    student = lookup.student(sid)
    body = json_body()
    shape.req_str(body, "reason")
    if student["enrollment_status"] in CLOSED_ENROLLMENT:
        raise ApiError("ERR_STUDENT_ALREADY_CLOSED")
    if student["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_STUDENT_NOT_ACTIVE")
    cascade.suspend_student(student)
    return object_response(serialize.student(student))


@bp.route("/students/<sid>/withdraw", methods=["POST"])
def withdraw_student_route(sid):
    require(ROLE_REGISTRAR)
    student = lookup.student(sid)
    body = json_body()
    effective_utc = shape.req_instant(body, "effective_utc")
    shape.req_str(body, "reason")
    if student["enrollment_status"] in CLOSED_ENROLLMENT:
        raise ApiError("ERR_STUDENT_ALREADY_CLOSED")
    if student["enrollment_status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_STUDENT_NOT_ACTIVE")
    activated = student["activated_at_utc"]
    if activated is not None and effective_utc < activated:
        raise bad_request(
            "Field 'effective_utc' may not precede activated_at_utc.")
    if effective_utc > db.now():
        raise bad_request("Field 'effective_utc' may not be in the future.")
    cascade.withdraw_student(student, effective_utc)
    return object_response(serialize.student(student))


@bp.route("/students/<sid>/progress-summary", methods=["GET"])
def student_progress_summary(sid):
    caller = require(*SUMMARY_ROLES)
    check_student_ownership(caller, sid)
    return object_response(serialize.progress_summary(lookup.student(sid)))


# --------------------------------------------------------- subscription terms

@bp.route("/subscription-terms", methods=["POST"])
def create_term():
    require(ROLE_REGISTRAR)
    body = json_body()
    student = lookup.student(shape.req_id(body, "student_id"))
    start = shape.req_instant(body, "term_start_utc")
    end = shape.req_instant(body, "term_end_utc")
    tuition_cents = shape.req_int(body, "tuition_cents", minimum=0)
    if end <= start:
        raise bad_request(
            "Field 'term_end_utc' must be strictly after 'term_start_utc'.")
    if student["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_STUDENT_NOT_ACTIVE")
    for other in lookup.terms_of(student["id"]):
        if other["status"] == "CANCELLED":
            continue
        if start < other["term_end_utc"] and other["term_start_utc"] < end:
            raise ApiError("ERR_TERM_WINDOW_OVERLAP")
    row = new_row()
    row.update({
        "student_id": student["id"],
        "term_start_utc": start,
        "term_end_utc": end,
        "tuition_cents": tuition_cents,
        "status": "PENDING",
        "activated_at_utc": None,
        "closed_effective_utc": None,
        "attended_days": None,
        "earned_pct": None,
        "institutional_refund_cents": None,
        "net_institutional_charge_cents": None,
    })
    db.terms[row["id"]] = row
    return created_response(serialize.term(row))


@bp.route("/subscription-terms/<tid>", methods=["GET"])
def read_term(tid):
    require(*READ_TERM_ROLES)
    return object_response(serialize.term(lookup.term(tid)))


@bp.route("/subscription-terms", methods=["GET"])
def list_terms():
    require(*LIST_TERM_ROLES)
    student_id = _arg("student_id")
    status = _arg("status")
    rows = []
    for row in db.terms.values():
        if student_id is not None and row["student_id"] != student_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    ordered = store.sort_rows(rows, [(lambda r: r["term_start_utc"], False)])
    return paginated(ordered, serialize.term)


@bp.route("/subscription-terms/<tid>/activate", methods=["POST"])
def activate_term(tid):
    require(ROLE_REGISTRAR)
    term = lookup.term(tid)
    if term["status"] != "PENDING":
        raise ApiError("ERR_TERM_NOT_PENDING")
    student = db.students.get(term["student_id"])
    if student is None or student["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_STUDENT_NOT_ACTIVE")
    for other in lookup.terms_of(term["student_id"]):
        if other["id"] != term["id"] and other["status"] == "ACTIVE":
            raise ApiError(
                "ERR_TERM_WINDOW_OVERLAP",
                "This student already has an active subscription term.")
    term["status"] = "ACTIVE"
    term["activated_at_utc"] = db.now()
    touch(term)
    return object_response(serialize.term(term))


@bp.route("/subscription-terms/<tid>/close", methods=["POST"])
def close_term_route(tid):
    require(ROLE_REGISTRAR, ROLE_FINANCIAL_AID_OFFICER)
    term = lookup.term(tid)
    body = json_body()
    outcome = shape.req_enum(body, "outcome",
                            ("COMPLETED", "LAPSED", "CANCELLED"))
    effective_utc = shape.req_instant(body, "effective_utc")
    if term["status"] == "PENDING":
        if outcome != "CANCELLED":
            raise ApiError(
                "ERR_TERM_NOT_ACTIVE",
                "A pending term may only be closed as CANCELLED.")
        cascade.cancel_pending_term(term, effective_utc)
        return object_response(serialize.term(term))
    if term["status"] != "ACTIVE":
        raise ApiError("ERR_TERM_NOT_ACTIVE")
    if effective_utc < term["term_start_utc"]:
        raise bad_request(
            "Field 'effective_utc' may not precede term_start_utc.")
    if effective_utc > db.now():
        raise bad_request("Field 'effective_utc' may not be in the future.")
    cascade.close_term(term, outcome, effective_utc)
    return object_response(serialize.term(term))
