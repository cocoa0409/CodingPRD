"""Student self-service: record read and privacy directives (PRD §3.8)."""
from flask import Blueprint

import db
from auth import ROLE_CLEARINGHOUSE_OPS, ROLE_LEARNER, authenticate, require_role
from core import (
    ERR_DIRECTIVE_WINDOW_INVALID,
    ERR_STALE_VERSION,
    ERR_STUDENT_NOT_FOUND,
    ERR_UNAUTHORIZED,
    get_body,
    list_response,
    ok_object,
    parse_dt,
    raise_err,
    req_date,
    req_enum,
    req_int,
)

bp = Blueprint("students", __name__)

DIRECTIVE_TYPES = ("FULL_BLOCK", "DIRECTORY_BLOCK", "RESEARCH_OPT_OUT")
ACCESS_ROLES = (ROLE_CLEARINGHOUSE_OPS, ROLE_LEARNER)


def _check_access(caller, student_id):
    # Learner path ownership (priority 3) precedes existence (priority 10).
    if caller.role == ROLE_LEARNER and caller.user_id != student_id:
        raise_err(ERR_UNAUTHORIZED, "a learner acts only on their own student record")


def _get_student(sid):
    s = db.store.students.get(sid)
    if s is None:
        raise_err(ERR_STUDENT_NOT_FOUND, "student record not found")
    return s


@bp.route("/students/<sid>", methods=["GET"])
def get_student(sid):
    caller = authenticate()
    require_role(caller, *ACCESS_ROLES)
    _check_access(caller, sid)
    return ok_object(db.serialize(_get_student(sid)))


@bp.route("/students/<sid>/privacy-directives", methods=["POST"])
def create_directive(sid):
    caller = authenticate()
    require_role(caller, *ACCESS_ROLES)
    _check_access(caller, sid)
    data = get_body()
    directive_type = req_enum(data, "directive_type", DIRECTIVE_TYPES)
    effective_from = req_date(data, "effective_from")
    effective_to = None
    if data.get("effective_to") is not None:
        effective_to = parse_dt(data["effective_to"], "effective_to")
    expected_version = req_int(data, "expected_student_version")

    student = _get_student(sid)
    # OCC is checked before any window arithmetic (PRD §3.8).
    if expected_version != student["version"]:
        raise_err(ERR_STALE_VERSION, "expected_student_version is stale")
    if effective_to is not None and not effective_to > effective_from:
        raise_err(ERR_DIRECTIVE_WINDOW_INVALID, "effective_to must be strictly after effective_from")

    # A same-type ACTIVE directive is superseded by the new one.
    for d in db.store.directives.values():
        if (
            d["student_id"] == sid
            and d["directive_type"] == directive_type
            and d["status"] == "ACTIVE"
        ):
            d["status"] = "SUPERSEDED"
            db.touch(d)

    directive = db.new_entity(
        {
            "student_id": sid,
            "directive_type": directive_type,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": "ACTIVE",
        }
    )
    db.store.directives[directive["id"]] = directive
    # The student record's version increments as part of the create mutation.
    db.touch(student)
    return ok_object(db.serialize(directive), 201)


@bp.route("/students/<sid>/privacy-directives", methods=["GET"])
def list_directives(sid):
    caller = authenticate()
    require_role(caller, *ACCESS_ROLES)
    _check_access(caller, sid)
    _get_student(sid)
    items = db.sorted_created(d for d in db.store.directives.values() if d["student_id"] == sid)
    return list_response(items, db.serialize)
