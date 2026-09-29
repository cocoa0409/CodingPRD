"""Faculty mentoring, caseload, endorsements and evaluators (PRD 3.4, 3.6)."""
from flask import Blueprint, request

import db as store
from db import db, new_row, touch
from errors import ApiError, bad_request
from middleware import (ROLE_EVALUATOR, ROLE_FACULTY_MENTOR,
                        ROLE_INTEGRITY_OFFICER, ROLE_PLATFORM_ADMIN,
                        ROLE_REGISTRAR, ROLE_STUDENT, check_mentor_ownership,
                        require)
from response import json_body, created_response, object_response, paginated
from services import calc, cascade, derive, lookup, serialize, shape

bp = Blueprint("mentoring", __name__)

MENTOR_READ_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN, ROLE_FACULTY_MENTOR,
                     ROLE_INTEGRITY_OFFICER)
ASSIGNMENT_READ_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN,
                         ROLE_FACULTY_MENTOR, ROLE_STUDENT)
ASSIGNMENT_LIST_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN,
                         ROLE_FACULTY_MENTOR)
EVALUATOR_READ_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN, ROLE_EVALUATOR,
                        ROLE_INTEGRITY_OFFICER)

MENTOR_STATUSES = ("ACTIVE", "ON_LEAVE", "INACTIVE")
CERTIFICATION_LEVELS = ("ASSOCIATE", "SENIOR")
EVALUATOR_STANDINGS = ("CERTIFIED", "PROVISIONAL", "SUSPENDED")


def _arg(name):
    raw = request.args.get(name, None)
    if raw is None:
        return None
    text = raw.strip()
    return text if text else None


# ------------------------------------------------------------------- mentors

@bp.route("/mentors", methods=["POST"])
def create_mentor():
    require(ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN)
    body = json_body()
    full_name = shape.req_str(body, "full_name")
    email = shape.req_str(body, "email")
    max_caseload = shape.req_int(body, "max_caseload", minimum=1)
    cadence_days = shape.req_int(body, "cadence_days", minimum=1)
    for existing in db.mentors.values():
        if existing["email"] == email:
            raise bad_request("A mentor with this email already exists.")
    row = new_row()
    row.update({
        "full_name": full_name,
        "email": email,
        "max_caseload": max_caseload,
        "cadence_days": cadence_days,
        "status": "ACTIVE",
    })
    db.mentors[row["id"]] = row
    return created_response(serialize.mentor(row))


@bp.route("/mentors/<mid>", methods=["GET"])
def read_mentor(mid):
    require(*MENTOR_READ_ROLES)
    return object_response(serialize.mentor(lookup.mentor(mid)))


@bp.route("/mentors", methods=["GET"])
def list_mentors():
    require(*MENTOR_READ_ROLES)
    status = _arg("status")
    rows = [m for m in db.mentors.values()
            if status is None or m["status"] == status]
    ordered = store.sort_rows(rows, [(derive.mentor_caseload, False)])
    return paginated(ordered, serialize.mentor)


@bp.route("/mentors/<mid>/status", methods=["POST"])
def set_mentor_status(mid):
    require(ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN)
    mentor = lookup.mentor(mid)
    body = json_body()
    status = shape.req_enum(body, "status", MENTOR_STATUSES)
    mentor["status"] = status
    touch(mentor)
    return object_response(serialize.mentor(mentor))


# --------------------------------------------------------- mentor assignments

@bp.route("/mentor-assignments", methods=["POST"])
def create_assignment():
    require(ROLE_REGISTRAR)
    body = json_body()
    student = lookup.student(shape.req_id(body, "student_id"))
    named_mentor = None
    if shape.present(body, "mentor_id"):
        named_mentor = lookup.mentor(shape.req_id(body, "mentor_id"))
    expected_version = shape.req_expected_version(body,
                                                  "expected_student_version")
    cadence_days = shape.opt_int(body, "cadence_days", None, minimum=1)
    if student["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_STUDENT_NOT_ACTIVE")
    if expected_version != student["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "The supplied expected_student_version is stale.")
    if named_mentor is not None:
        if (named_mentor["status"] != "ACTIVE"
                or derive.mentor_caseload(named_mentor)
                >= named_mentor["max_caseload"]):
            raise ApiError("ERR_MENTOR_CASELOAD_FULL")
        mentor = named_mentor
        selection_mode = "EXPLICIT"
    else:
        mentor = calc.auto_select_mentor()
        if mentor is None:
            raise ApiError("ERR_NO_ELIGIBLE_MENTOR")
        selection_mode = "AUTO_SELECTED"
    prior = derive.active_assignment(student["id"])
    if prior is not None:
        cascade.end_assignment(prior)
    row = new_row()
    row.update({
        "mentor_id": mentor["id"],
        "student_id": student["id"],
        "cadence_days": (cadence_days if cadence_days is not None
                         else mentor["cadence_days"]),
        "selection_mode": selection_mode,
        "assigned_at_utc": db.now(),
        "last_contact_utc": None,
        "contact_count": 0,
        "endorsements": [],
        "status": "ACTIVE",
        "ended_at_utc": None,
    })
    db.assignments[row["id"]] = row
    touch(mentor)
    touch(student)
    return created_response(serialize.assignment(row))


@bp.route("/mentor-assignments/<aid>", methods=["GET"])
def read_assignment(aid):
    require(*ASSIGNMENT_READ_ROLES)
    return object_response(serialize.assignment(lookup.assignment(aid)))


@bp.route("/mentor-assignments", methods=["GET"])
def list_assignments():
    require(*ASSIGNMENT_LIST_ROLES)
    student_id = _arg("student_id")
    mentor_id = _arg("mentor_id")
    status = _arg("status")
    cadence_status = _arg("cadence_status")
    rows = []
    for row in db.assignments.values():
        if student_id is not None and row["student_id"] != student_id:
            continue
        if mentor_id is not None and row["mentor_id"] != mentor_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if (cadence_status is not None
                and derive.cadence_state(row)[0] != cadence_status):
            continue
        rows.append(row)
    ordered = store.sort_rows(rows, [(lambda r: r["assigned_at_utc"], True)])
    return paginated(ordered, serialize.assignment)


@bp.route("/mentor-assignments/<aid>/contacts", methods=["POST"])
def record_contact(aid):
    caller = require(ROLE_FACULTY_MENTOR, ROLE_REGISTRAR)
    assignment = lookup.assignment(aid)
    check_mentor_ownership(caller, assignment["mentor_id"])
    body = json_body()
    shape.opt_str(body, "note")
    if assignment["status"] != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE")
    student = db.students.get(assignment["student_id"])
    if student is None or student["enrollment_status"] not in ("ACTIVE",
                                                              "SUSPENDED"):
        raise ApiError("ERR_STUDENT_NOT_ACTIVE")
    assignment["last_contact_utc"] = db.now()
    assignment["contact_count"] = assignment["contact_count"] + 1
    touch(assignment)
    return object_response(serialize.assignment(assignment))


@bp.route("/mentor-assignments/<aid>/endorsements", methods=["POST"])
def record_endorsement(aid):
    caller = require(ROLE_FACULTY_MENTOR)
    assignment = lookup.assignment(aid)
    check_mentor_ownership(caller, assignment["mentor_id"])
    body = json_body()
    competency = lookup.competency(shape.req_id(body, "competency_id"))
    if assignment["status"] != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE")
    student = db.students.get(assignment["student_id"])
    if student is None or competency["program_id"] != student["program_id"]:
        raise bad_request(
            "The endorsed competency does not belong to the mentee's program.")
    if competency["status"] != "ACTIVE":
        raise ApiError("ERR_COMPETENCY_RETIRED")
    for pending in derive.unconsumed_endorsements(assignment):
        if pending["competency_id"] == competency["id"]:
            raise bad_request(
                "This competency already carries an unconsumed endorsement.")
    assignment["endorsements"].append({
        "competency_id": competency["id"],
        "consumed": False,
        "created_at": db.now(),
        "seq": db.next_seq(),
    })
    touch(assignment)
    return object_response(serialize.assignment(assignment))


@bp.route("/mentor-assignments/<aid>/end", methods=["POST"])
def end_assignment_route(aid):
    require(ROLE_REGISTRAR)
    assignment = lookup.assignment(aid)
    if assignment["status"] != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE")
    cascade.end_assignment(assignment)
    return object_response(serialize.assignment(assignment))


# ---------------------------------------------------------------- evaluators

@bp.route("/evaluators", methods=["POST"])
def create_evaluator():
    require(ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN)
    body = json_body()
    mentor_row = None
    if shape.present(body, "mentor_id"):
        mentor_row = lookup.mentor(shape.req_id(body, "mentor_id"))
    full_name = shape.req_str(body, "full_name")
    email = shape.req_str(body, "email")
    certification_level = shape.req_enum(body, "certification_level",
                                         CERTIFICATION_LEVELS)
    for existing in db.evaluators.values():
        if existing["email"] == email:
            raise bad_request("An evaluator with this email already exists.")
    row = new_row()
    row.update({
        "full_name": full_name,
        "email": email,
        "certification_level": certification_level,
        "mentor_id": mentor_row["id"] if mentor_row is not None else None,
        "status": "CERTIFIED",
        "demoted_at_utc": None,
    })
    db.evaluators[row["id"]] = row
    return created_response(serialize.evaluator(row))


@bp.route("/evaluators/<eid>", methods=["GET"])
def read_evaluator(eid):
    require(*EVALUATOR_READ_ROLES)
    return object_response(serialize.evaluator(lookup.evaluator(eid)))


@bp.route("/evaluators", methods=["GET"])
def list_evaluators():
    require(*EVALUATOR_READ_ROLES)
    mentor_id = _arg("mentor_id")
    status = _arg("status")
    certification_level = _arg("certification_level")
    rows = []
    for row in db.evaluators.values():
        if mentor_id is not None and row["mentor_id"] != mentor_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if (certification_level is not None
                and row["certification_level"] != certification_level):
            continue
        rows.append(row)
    return paginated(store.by_created(rows), serialize.evaluator)


@bp.route("/evaluators/<eid>/status", methods=["POST"])
def set_evaluator_status(eid):
    require(ROLE_PLATFORM_ADMIN)
    evaluator = lookup.evaluator(eid)
    body = json_body()
    status = shape.req_enum(body, "status", EVALUATOR_STANDINGS)
    if evaluator["status"] == "SUSPENDED":
        raise ApiError("ERR_EVALUATOR_SUSPENDED")
    evaluator["status"] = status
    touch(evaluator)
    return object_response(serialize.evaluator(evaluator))
