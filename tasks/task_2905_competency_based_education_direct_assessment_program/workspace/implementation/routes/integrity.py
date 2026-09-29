"""Academic-integrity casework and the four-hop void cascade (PRD 3.7)."""
from flask import Blueprint, request

import db as store
from db import db, new_row, touch
from errors import ApiError
from middleware import (ROLE_EVALUATOR, ROLE_INTEGRITY_OFFICER,
                        ROLE_PLATFORM_ADMIN, ROLE_REGISTRAR, require)
from response import json_body, created_response, object_response, paginated
from services import calc, cascade, derive, lookup, serialize, shape

bp = Blueprint("integrity", __name__)

CASE_READ_ROLES = (ROLE_INTEGRITY_OFFICER, ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN)
SIGNAL_TYPES = ("SHARED_DEVICE", "DUPLICATE_ARTIFACT", "ATTESTATION_ANOMALY",
                "THIRD_PARTY_REPORT")
SEVERITIES = ("LOW", "MEDIUM", "HIGH")
OUTCOMES = ("SUBSTANTIATED", "DISMISSED")
SANCTIONS = ("NONE", "ATTEMPT_VOID", "TERM_SUSPENSION")
HOLDABLE_STATUSES = ("DRAFT", "UNDER_REVIEW", "ADJUDICATION")
RESOLVED_STATUSES = ("SUBSTANTIATED", "DISMISSED")


def _arg(name):
    raw = request.args.get(name, None)
    if raw is None:
        return None
    text = raw.strip()
    return text if text else None


@bp.route("/integrity-cases", methods=["POST"])
def open_case():
    caller = require(ROLE_INTEGRITY_OFFICER, ROLE_EVALUATOR)
    body = json_body()
    attempt = lookup.attempt(shape.req_id(body, "attempt_id"))
    signal_type = shape.req_enum(body, "signal_type", SIGNAL_TYPES)
    severity = shape.req_enum(body, "severity", SEVERITIES)
    note = shape.opt_str(body, "note")
    if attempt["status"] == "VOIDED":
        raise ApiError("ERR_ATTEMPT_VOIDED")
    row = new_row()
    row.update({
        "attempt_id": attempt["id"],
        "student_id": attempt["student_id"],
        "signal_type": signal_type,
        "severity": severity,
        "note": note,
        "status": "OPEN",
        "sanction": "NONE",
        "attempt_status_at_open": attempt["status"],
        "opened_by_user_id": caller.user_id,
        "resolved_by_user_id": None,
        "resolved_at_utc": None,
        "auto_raised": False,
    })
    db.cases[row["id"]] = row
    if attempt["status"] in HOLDABLE_STATUSES:
        attempt["held_from_status"] = attempt["status"]
        attempt["status"] = "INTEGRITY_HOLD"
    touch(attempt)
    return created_response(serialize.integrity_case(row))


@bp.route("/integrity-cases/<cid>", methods=["GET"])
def read_case(cid):
    require(*CASE_READ_ROLES)
    return object_response(serialize.integrity_case(lookup.case(cid)))


@bp.route("/integrity-cases", methods=["GET"])
def list_cases():
    require(*CASE_READ_ROLES)
    student_id = _arg("student_id")
    attempt_id = _arg("attempt_id")
    status = _arg("status")
    signal_type = _arg("signal_type")
    rows = []
    for row in db.cases.values():
        if student_id is not None and row["student_id"] != student_id:
            continue
        if attempt_id is not None and row["attempt_id"] != attempt_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if signal_type is not None and row["signal_type"] != signal_type:
            continue
        rows.append(row)
    return paginated(store.by_created(rows), serialize.integrity_case)


@bp.route("/integrity-cases/<cid>/investigate", methods=["POST"])
def investigate_case(cid):
    require(ROLE_INTEGRITY_OFFICER)
    case = lookup.case(cid)
    if case["status"] != "OPEN":
        raise ApiError("ERR_CASE_ALREADY_RESOLVED")
    case["status"] = "UNDER_INVESTIGATION"
    touch(case)
    return object_response(serialize.integrity_case(case))


@bp.route("/integrity-cases/<cid>/resolve", methods=["POST"])
def resolve_case(cid):
    caller = require(ROLE_INTEGRITY_OFFICER)
    case = lookup.case(cid)
    body = json_body()
    outcome = shape.req_enum(body, "outcome", OUTCOMES)
    sanction = shape.req_enum(body, "sanction", SANCTIONS)
    if case["status"] in RESOLVED_STATUSES:
        raise ApiError("ERR_CASE_ALREADY_RESOLVED")
    if case["status"] != "UNDER_INVESTIGATION":
        raise ApiError("ERR_CASE_NOT_UNDER_INVESTIGATION")
    if caller.user_id == case["opened_by_user_id"]:
        raise ApiError("ERR_CASE_RESOLVER_IS_OPENER")
    if outcome == "DISMISSED":
        sanction = "NONE"
    # hop one: the resolution itself
    case["status"] = outcome
    case["sanction"] = sanction
    case["resolved_at_utc"] = db.now()
    case["resolved_by_user_id"] = caller.user_id
    touch(case)
    attempt = db.attempts.get(case["attempt_id"])
    student = db.students.get(case["student_id"])
    program = lookup.program_of_student(student) if student else None
    if attempt is not None:
        restorable = (attempt["status"] == "INTEGRITY_HOLD"
                      and attempt["held_from_status"] is not None
                      and sanction != "ATTEMPT_VOID"
                      and not derive.attempt_has_live_case(attempt["id"]))
        if restorable:
            attempt["status"] = attempt["held_from_status"]
            attempt["held_from_status"] = None
        touch(attempt)
    if outcome != "SUBSTANTIATED":
        return object_response(serialize.integrity_case(case))
    # hop two: the sanctioned attempt is voided, which runs hops three and four
    if sanction == "ATTEMPT_VOID" and attempt is not None:
        cascade.void_attempt(attempt)
        if program is not None:
            calc.refresh_pair_standing(attempt, program)
    if sanction == "TERM_SUSPENSION" and student is not None:
        for term in derive.active_terms(student["id"]):
            cascade.close_term(term, "CANCELLED", db.now())
        if student["enrollment_status"] == "ACTIVE":
            cascade.suspend_student(student)
    # hop five: the second substantiated strike costs the student their standing
    if (student is not None
            and student["enrollment_status"] == "ACTIVE"
            and derive.integrity_strike_count(student["id"]) >= 2):
        cascade.suspend_student(student)
    return object_response(serialize.integrity_case(case))
