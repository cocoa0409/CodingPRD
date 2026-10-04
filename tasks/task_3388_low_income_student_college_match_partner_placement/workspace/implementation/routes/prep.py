"""PrepProgram endpoints: record enrollment, close, get."""
from flask import Blueprint

import serializers
import store
from auth import forbid, identity, require_roles
from errors import ApiError, ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_PROGRAM_OVERLAP
from response import ok_object
from validation import KIND_DATETIME, KIND_ENUM, KIND_STR, get_body, validate

bp = Blueprint("prep", __name__)

PROGRAM_TYPES = ("SUMMER", "SCHOLAR")
CLOSE_OUTCOMES = ("COMPLETED", "WITHDRAWN")


@bp.post("/prep-programs")
def create_prep_program():
    body = get_body()
    values = validate(body, [
        ("student_id", KIND_STR, True, None, None),
        ("program_type", KIND_ENUM, True, None, PROGRAM_TYPES),
        ("cohort_label", KIND_STR, True, None, None),
        ("starts_on", KIND_DATETIME, True, None, None),
        ("ends_on", KIND_DATETIME, True, None, None),
    ])
    role, _ = identity()
    require_roles(role, ("ProgramAdmin",))
    student = store.students.get(values["student_id"])
    if student is None:
        raise ApiError(ERR_NOT_FOUND, "student not found")
    # Half-open interval [starts_on, ends_on): intersects another non-WITHDRAWN
    # enrollment of the same student iff starts < other.ends and
    # other.starts < ends. Touching endpoints do not intersect.
    for existing in store.prep_programs.values():
        if existing["student_id"] != values["student_id"]:
            continue
        if existing["status"] == "WITHDRAWN":
            continue
        if values["starts_on"] < existing["ends_on"] and existing["starts_on"] < values["ends_on"]:
            raise ApiError(ERR_PROGRAM_OVERLAP, "prep enrollment interval intersects an existing one")
    program = store.create(store.prep_programs, {
        "student_id": values["student_id"],
        "program_type": values["program_type"],
        "cohort_label": values["cohort_label"],
        "starts_on": values["starts_on"],
        "ends_on": values["ends_on"],
        "status": "ENROLLED",
    })
    return ok_object(serializers.prep_program(program), 201)


@bp.post("/prep-programs/<program_id>/close")
def close_prep_program(program_id):
    body = get_body()
    values = validate(body, [("outcome", KIND_ENUM, True, None, CLOSE_OUTCOMES)])
    role, _ = identity()
    require_roles(role, ("ProgramAdmin",))
    program = store.prep_programs.get(program_id)
    if program is None:
        raise ApiError(ERR_NOT_FOUND, "prep program not found")
    if program["status"] != "ENROLLED":
        raise ApiError(ERR_INVALID_STATE, "only an ENROLLED prep program can be closed")
    program["status"] = values["outcome"]
    store.touch(program)
    return ok_object(serializers.prep_program(program))


@bp.get("/prep-programs/<program_id>")
def get_prep_program(program_id):
    role, uid = identity()
    require_roles(role, ("ProgramAdmin", "Student", "Counselor", "PartnerStaff"))
    program = store.prep_programs.get(program_id)
    if program is None:
        raise ApiError(ERR_NOT_FOUND, "prep program not found")
    if role == "Student" and uid != program["student_id"]:
        forbid("a student may only view their own prep programs")
    return ok_object(serializers.prep_program(program))
