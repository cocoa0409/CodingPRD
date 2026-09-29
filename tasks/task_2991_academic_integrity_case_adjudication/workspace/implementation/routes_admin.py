"""Clock, departments, faculty, training, students and course offerings
(PRD 3.1 and 3.2).
"""

from flask import Blueprint, request

import calc
import cascades
from db import S, new_immutable_row, new_row, touch
from errors import ApiError, fail
from lookup import department_or_404, faculty_or_404, filter_rows, offering_or_404, student_or_404
from middleware import (ROLE_APPEALS_DEAN, ROLE_FACULTY_REPORTER, ROLE_INTEGRITY_OFFICER,
                        ROLE_PANEL_CHAIR, ROLE_REGISTRAR_OFFICER, ROLE_STUDENT, ALL_ROLES, auth)
from response import ok, created, ok_list, pagination
from serializers import department_json, faculty_json, offering_json, student_json
from shapes import Field, query_dt, query_enum, validate
from util import D0, fmt_dt, num, r2

bp = Blueprint("admin", __name__)

MONITORING_FLAGS = ("NORMAL", "TRAINING_DEFICIT", "UNDER_REPORTING", "ELEVATED")

CLOCK_FIELDS = [Field("current_utc", "datetime")]

DEPARTMENT_FIELDS = [
    Field("code", "string", pattern=r"^[A-Z0-9]{2,8}$"),
    Field("name", "string", min_len=1, max_len=120),
    Field("enrolled_student_count", "integer", minimum=1),
    Field("faculty_headcount", "integer", minimum=1),
]

FACULTY_FIELDS = [
    Field("department_id", "string"),
    Field("full_name", "string", min_len=1, max_len=120),
    Field("email", "string", min_len=1),
]

TRAINING_FIELDS = [
    Field("module_code", "string"),
    Field("completed_at", "datetime"),
]

STUDENT_FIELDS = [
    Field("full_name", "string", min_len=1, max_len=120),
    Field("email", "string", min_len=1),
    Field("program_code", "string", min_len=2, max_len=16),
    Field("class_year", "integer", minimum=1, maximum=8),
]

GRADE_COMPONENT_FIELDS = [
    Field("code", "string", pattern=r"^[A-Z0-9_]{2,16}$"),
    Field("max_points", "integer", minimum=1),
    Field("weight_pct", "integer", minimum=1, maximum=100),
]

OFFERING_FIELDS = [
    Field("department_id", "string"),
    Field("instructor_id", "string"),
    Field("course_code", "string", pattern=r"^[A-Z]{2,6}-[0-9]{3}$"),
    Field("term_code", "string", pattern=r"^[0-9]{4}(SP|SU|FA)$"),
    Field("grade_components", "object_array", items=GRADE_COMPONENT_FIELDS,
          min_items=1, max_items=8),
]


def one_at_sign(value, label):
    if value.count("@") != 1:
        fail("ERR_INVALID_REQUEST", "Field %s must contain exactly one @ character." % label)


def fk_filter(param, resolver):
    raw = request.args.get(param)
    if raw is not None and raw != "":
        resolver(raw)


# ---------------------------------------------------------------- the clock

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(ALL_ROLES)
    body = validate(CLOCK_FIELDS)
    S.clock = body["current_utc"]
    return ok({"current_utc": fmt_dt(S.clock)})


# ---------------------------------------------------------------- departments

@bp.route("/integrity/departments", methods=["POST"])
def create_department():
    auth([ROLE_INTEGRITY_OFFICER])
    body = validate(DEPARTMENT_FIELDS)
    for existing in S.departments.values():
        if existing["code"] == body["code"]:
            fail("ERR_DUPLICATE_RESOURCE", "A department with this code already exists.")
    row = new_row(
        code=body["code"],
        name=body["name"],
        enrolled_student_count=body["enrolled_student_count"],
        faculty_headcount=body["faculty_headcount"],
        reporting_rate_per_1k_submitted=D0,
        monitoring_flag="NORMAL",
    )
    S.departments[row["id"]] = row
    # A brand-new department reports exactly 0.00, so branch one of the pinned
    # order makes it UNDER_REPORTING the moment it is created.
    row["monitoring_flag"] = calc.monitoring_flag_for(row)
    return created(department_json(row))


@bp.route("/integrity/departments", methods=["GET"])
def list_departments():
    auth([ROLE_INTEGRITY_OFFICER, ROLE_REGISTRAR_OFFICER])
    limit, offset = pagination()
    rows = filter_rows(S.departments, {"code": "code", "monitoring_flag": "monitoring_flag"})
    return ok_list(rows, department_json, limit, offset)


@bp.route("/integrity/departments/<row_id>", methods=["GET"])
def read_department(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_REGISTRAR_OFFICER, ROLE_FACULTY_REPORTER,
          ROLE_APPEALS_DEAN])
    return ok(department_json(department_or_404(row_id)))


@bp.route("/integrity/departments/<row_id>/reporting-metrics", methods=["GET"])
def reporting_metrics(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_REGISTRAR_OFFICER])
    # PRD 2.6: the parent identifier is resolved before anything nested.
    department = department_or_404(row_id)
    basis = query_enum("basis", ("SUBMITTED", "ADJUDICATED"), "SUBMITTED")
    as_of = query_dt("as_of", S.clock)
    numerator, rate = calc.department_reporting_rate(department, basis, as_of)
    training_pct = calc.department_training_completion_pct(department)
    if basis == "SUBMITTED":
        changed = department["reporting_rate_per_1k_submitted"] != rate
        department["reporting_rate_per_1k_submitted"] = rate
        flag = calc.monitoring_flag_for(department, training_pct)
        if department["monitoring_flag"] != flag:
            changed = True
        department["monitoring_flag"] = flag
        if changed:
            touch(department)
    else:
        # An ADJUDICATED-basis read persists nothing at all.
        flag = calc.monitoring_flag_for(department, training_pct)
    peer_median = calc.peer_median_rate()
    return ok({
        "department_id": department["id"],
        "basis": basis,
        "as_of": fmt_dt(as_of),
        "window_days": calc.REPORTING_WINDOW_DAYS,
        "numerator": numerator,
        "enrolled_student_count": department["enrolled_student_count"],
        "reporting_rate_per_1k": num(rate),
        "peer_median_rate": num(peer_median),
        "elevated_threshold_rate": num(calc.elevated_threshold(peer_median)),
        "training_completion_pct": num(training_pct),
        "faculty_current_count": calc.department_faculty_current_count(department),
        "faculty_headcount": department["faculty_headcount"],
        "monitoring_flag": flag,
    })


# ---------------------------------------------------------------- faculty

@bp.route("/integrity/faculty-members", methods=["POST"])
def create_faculty():
    auth([ROLE_INTEGRITY_OFFICER])
    body = validate(FACULTY_FIELDS)
    one_at_sign(body["email"], "email")
    department = department_or_404(body["department_id"])
    for existing in S.faculty_members.values():
        if existing["email"] == body["email"]:
            fail("ERR_DUPLICATE_RESOURCE", "A faculty member with this email already exists.")
    row = new_row(
        department_id=body["department_id"],
        full_name=body["full_name"],
        email=body["email"],
    )
    S.faculty_members[row["id"]] = row
    cascades.recompute_department(department)
    return created(faculty_json(row))


@bp.route("/integrity/faculty-members", methods=["GET"])
def list_faculty():
    auth([ROLE_INTEGRITY_OFFICER, ROLE_REGISTRAR_OFFICER])
    limit, offset = pagination()
    fk_filter("department_id", department_or_404)
    rows = filter_rows(S.faculty_members, {"department_id": "department_id", "email": "email"})
    wanted = request.args.get("training_status")
    if wanted is not None:
        rows = [row for row in rows if calc.faculty_training_status(row) == wanted]
    return ok_list(rows, faculty_json, limit, offset)


@bp.route("/integrity/faculty-members/<row_id>", methods=["GET"])
def read_faculty(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_FACULTY_REPORTER, ROLE_PANEL_CHAIR,
          ROLE_REGISTRAR_OFFICER])
    return ok(faculty_json(faculty_or_404(row_id)))


@bp.route("/integrity/faculty-members/<row_id>/training-completions", methods=["POST"])
def record_training(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_FACULTY_REPORTER])
    member = faculty_or_404(row_id)
    body = validate(TRAINING_FIELDS)
    if body["completed_at"] > S.clock:
        fail("ERR_INVALID_REQUEST", "completed_at may not be after the current logical clock.")
    completion = new_immutable_row(
        faculty_id=member["id"],
        module_code=body["module_code"],
        completed_at=body["completed_at"],
    )
    S.training_completions[completion["id"]] = completion
    touch(member)
    cascades.recompute_department(S.departments.get(member["department_id"]))
    return ok(faculty_json(member))


# ---------------------------------------------------------------- students

@bp.route("/integrity/students", methods=["POST"])
def create_student():
    auth([ROLE_INTEGRITY_OFFICER])
    body = validate(STUDENT_FIELDS)
    one_at_sign(body["email"], "email")
    for existing in S.students.values():
        if existing["email"] == body["email"]:
            fail("ERR_DUPLICATE_RESOURCE", "A student with this email already exists.")
    row = new_row(
        full_name=body["full_name"],
        email=body["email"],
        program_code=body["program_code"],
        class_year=body["class_year"],
    )
    S.students[row["id"]] = row
    return created(student_json(row))


@bp.route("/integrity/students", methods=["GET"])
def list_students():
    auth([ROLE_INTEGRITY_OFFICER, ROLE_REGISTRAR_OFFICER])
    limit, offset = pagination()
    rows = filter_rows(S.students, {"email": "email"})
    standing = request.args.get("standing")
    if standing is not None:
        rows = [row for row in rows if calc.student_standing(row["id"]) == standing]
    notation = request.args.get("transcript_notation")
    if notation is not None:
        rows = [row for row in rows if calc.student_transcript_notation(row["id"]) == notation]
    return ok_list(rows, student_json, limit, offset)


@bp.route("/integrity/students/<row_id>", methods=["GET"])
def read_student(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_REGISTRAR_OFFICER, ROLE_APPEALS_DEAN, ROLE_STUDENT])
    return ok(student_json(student_or_404(row_id)))


# ---------------------------------------------------------------- offerings

@bp.route("/integrity/course-offerings", methods=["POST"])
def create_offering():
    auth([ROLE_INTEGRITY_OFFICER])
    body = validate(OFFERING_FIELDS)
    components = body["grade_components"]
    codes = [component["code"] for component in components]
    if len(codes) != len(set(codes)):
        fail("ERR_INVALID_REQUEST", "grade_components codes must be unique within the array.")
    total = sum(component["weight_pct"] for component in components)
    if total != 100:
        fail("ERR_INVALID_REQUEST", "grade_components weight_pct values must sum to exactly 100.")
    department_or_404(body["department_id"])
    faculty_or_404(body["instructor_id"])
    for existing in S.offerings.values():
        if (existing["course_code"] == body["course_code"]
                and existing["term_code"] == body["term_code"]):
            fail("ERR_DUPLICATE_RESOURCE",
                 "An offering already pairs this course_code with this term_code.")
    row = new_row(
        department_id=body["department_id"],
        instructor_id=body["instructor_id"],
        course_code=body["course_code"],
        term_code=body["term_code"],
        grade_components=[
            {
                "code": component["code"],
                "max_points": component["max_points"],
                "weight_pct": component["weight_pct"],
            }
            for component in components
        ],
    )
    S.offerings[row["id"]] = row
    return created(offering_json(row))


@bp.route("/integrity/course-offerings", methods=["GET"])
def list_offerings():
    auth([ROLE_INTEGRITY_OFFICER, ROLE_FACULTY_REPORTER, ROLE_REGISTRAR_OFFICER])
    limit, offset = pagination()
    fk_filter("department_id", department_or_404)
    fk_filter("instructor_id", faculty_or_404)
    rows = filter_rows(S.offerings, {
        "department_id": "department_id",
        "instructor_id": "instructor_id",
        "term_code": "term_code",
        "course_code": "course_code",
    })
    return ok_list(rows, offering_json, limit, offset)


@bp.route("/integrity/course-offerings/<row_id>", methods=["GET"])
def read_offering(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_FACULTY_REPORTER, ROLE_PANEL_CHAIR,
          ROLE_REGISTRAR_OFFICER])
    return ok(offering_json(offering_or_404(row_id)))
