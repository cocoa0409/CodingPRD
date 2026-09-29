"""Programs, competencies and assessment blueprints (PRD 3.1, 3.2)."""
from flask import Blueprint, request

import db as store
from db import db, new_row, touch
from errors import ApiError, bad_request
from middleware import (ROLE_EVALUATOR, ROLE_FACULTY_MENTOR,
                        ROLE_FINANCIAL_AID_OFFICER, ROLE_INTEGRITY_OFFICER,
                        ROLE_PLATFORM_ADMIN, ROLE_REGISTRAR, ROLE_STUDENT,
                        require)
from response import json_body, created_response, object_response, paginated
from services import derive, lookup, serialize, shape
from services.nums import ONE, ZERO, dec, rhu

bp = Blueprint("catalog", __name__)

READ_PROGRAM_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN, ROLE_FACULTY_MENTOR,
                      ROLE_EVALUATOR, ROLE_INTEGRITY_OFFICER,
                      ROLE_FINANCIAL_AID_OFFICER, ROLE_STUDENT)
LIST_PROGRAM_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN, ROLE_FACULTY_MENTOR,
                      ROLE_EVALUATOR, ROLE_INTEGRITY_OFFICER,
                      ROLE_FINANCIAL_AID_OFFICER)
READ_MAP_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN, ROLE_FACULTY_MENTOR,
                  ROLE_EVALUATOR, ROLE_INTEGRITY_OFFICER, ROLE_STUDENT)

LEVELS = ("FOUNDATION", "CORE", "CAPSTONE")
PASSING_RULES = ("WEIGHTED_ONLY", "WEIGHTED_PLUS_ALL_CRITICAL")


def _arg(name):
    raw = request.args.get(name, None)
    if raw is None:
        return None
    text = raw.strip()
    return text if text else None


# ------------------------------------------------------------------ programs

def _program_policy(body):
    return {
        "mastery_threshold_pct": shape.opt_number(
            body, "mastery_threshold_pct", 2, rhu(dec("80.00"), 2),
            maximum=dec("100"), exclusive_min=ZERO),
        "units_per_credit_hour": shape.opt_number(
            body, "units_per_credit_hour", 1, rhu(dec("3.0"), 1),
            exclusive_min=ZERO),
        "sap_min_units_per_term": shape.opt_number(
            body, "sap_min_units_per_term", None, dec("12"),
            exclusive_min=ZERO),
        "required_unit_total": shape.opt_number(
            body, "required_unit_total", None, dec("120"), exclusive_min=ZERO),
        "irr_tolerance_pct": shape.opt_number(
            body, "irr_tolerance_pct", 2, rhu(dec("5.00"), 2), minimum=ZERO),
        "irr_min_paired_reviews": shape.opt_int(
            body, "irr_min_paired_reviews", 3, minimum=1),
        "irr_suspend_rate_pct": shape.opt_number(
            body, "irr_suspend_rate_pct", 2, rhu(dec("70.00"), 2),
            maximum=dec("100"), exclusive_min=ZERO),
        "attempt_cooloff_hours": shape.opt_int(
            body, "attempt_cooloff_hours", 48, minimum=0),
        "attempts_before_endorsement": shape.opt_int(
            body, "attempts_before_endorsement", 3, minimum=1),
        "critical_dimension_min_ratio": shape.opt_number(
            body, "critical_dimension_min_ratio", 2, rhu(dec("0.70"), 2),
            maximum=ONE, exclusive_min=ZERO),
        "cadence_gate_overdue_days": shape.opt_int(
            body, "cadence_gate_overdue_days", 7, minimum=1),
        "blueprint_notice_days": shape.opt_int(
            body, "blueprint_notice_days", 14, minimum=0),
        "aid_earned_pct_full_threshold": shape.opt_number(
            body, "aid_earned_pct_full_threshold", 4, rhu(dec("0.6000"), 4),
            maximum=ONE, exclusive_min=ZERO),
        "aid_min_credit_equivalency": shape.opt_int(
            body, "aid_min_credit_equivalency", 1, minimum=0),
    }


@bp.route("/programs", methods=["POST"])
def create_program():
    require(ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN)
    body = json_body()
    code = shape.req_str(body, "code", min_len=3, max_len=16)
    if code != code.upper():
        raise bad_request("Field 'code' must be uppercase.")
    title = shape.req_str(body, "title")
    for existing in db.programs.values():
        if existing["code"] == code:
            raise bad_request("A program with this code already exists.")
    row = new_row()
    row.update({
        "code": code,
        "title": title,
        "status": "DRAFT",
        "published_at_utc": None,
    })
    row.update(_program_policy(body))
    db.programs[row["id"]] = row
    return created_response(serialize.program(row))


@bp.route("/programs/<pid>", methods=["GET"])
def read_program(pid):
    require(*READ_PROGRAM_ROLES)
    return object_response(serialize.program(lookup.program(pid)))


@bp.route("/programs", methods=["GET"])
def list_programs():
    require(*LIST_PROGRAM_ROLES)
    rows = store.by_created(list(db.programs.values()), descending=True)
    return paginated(rows, serialize.program)


@bp.route("/programs/<pid>/publish", methods=["POST"])
def publish_program(pid):
    require(ROLE_REGISTRAR)
    program = lookup.program(pid)
    if program["status"] != "DRAFT":
        raise ApiError("ERR_PROGRAM_ALREADY_PUBLISHED")
    active = [c for c in lookup.competencies_of(program["id"])
              if c["status"] == "ACTIVE"]
    if not active:
        raise bad_request(
            "A program needs at least one active competency to be published.")
    program["status"] = "PUBLISHED"
    program["published_at_utc"] = db.now()
    touch(program)
    return object_response(serialize.program(program))


# -------------------------------------------------------------- competencies

def _guard_prerequisite(competency_row, program_id, prerequisite_id):
    """Rules 25 and 26 of PRD 2.11, in that order."""
    if prerequisite_id is None:
        return
    parent = db.competencies.get(prerequisite_id)
    if parent["program_id"] != program_id:
        raise ApiError("ERR_PREREQUISITE_PROGRAM_MISMATCH")
    if competency_row is not None and prerequisite_id == competency_row["id"]:
        raise ApiError("ERR_PREREQUISITE_CYCLE")
    seen = set()
    cursor = parent
    while cursor is not None:
        if cursor["id"] in seen:
            raise ApiError("ERR_PREREQUISITE_CYCLE")
        seen.add(cursor["id"])
        if competency_row is not None and cursor["id"] == competency_row["id"]:
            raise ApiError("ERR_PREREQUISITE_CYCLE")
        nxt = cursor.get("prerequisite_competency_id")
        cursor = db.competencies.get(nxt) if nxt else None


@bp.route("/competencies", methods=["POST"])
def create_competency():
    require(ROLE_REGISTRAR)
    body = json_body()
    program = lookup.program(shape.req_id(body, "program_id"))
    prerequisite_id = shape.opt_id(body, "prerequisite_competency_id")
    if prerequisite_id is not None:
        lookup.competency(prerequisite_id)
    code = shape.req_str(body, "code")
    title = shape.req_str(body, "title")
    unit_value = shape.req_number(body, "unit_value", 2, exclusive_min=ZERO)
    level = shape.req_enum(body, "level", LEVELS)
    threshold = shape.opt_number(body, "mastery_threshold_pct", 2,
                                 maximum=dec("100"), exclusive_min=ZERO)
    for existing in lookup.competencies_of(program["id"]):
        if existing["code"] == code:
            raise bad_request(
                "A competency with this code already exists in the program.")
    _guard_prerequisite(None, program["id"], prerequisite_id)
    row = new_row()
    row.update({
        "program_id": program["id"],
        "code": code,
        "title": title,
        "unit_value": unit_value,
        "level": level,
        "mastery_threshold_pct": threshold,
        "prerequisite_competency_id": prerequisite_id,
        "status": "ACTIVE",
    })
    db.competencies[row["id"]] = row
    touch(program)
    return created_response(serialize.competency(row))


@bp.route("/competencies/<cid>", methods=["GET"])
def read_competency(cid):
    require(*READ_MAP_ROLES)
    return object_response(serialize.competency(lookup.competency(cid)))


@bp.route("/competencies", methods=["GET"])
def list_competencies():
    require(*READ_MAP_ROLES)
    rows = list(db.competencies.values())
    program_id = _arg("program_id")
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    prerequisite_id = _arg("prerequisite_competency_id")
    if prerequisite_id is not None:
        rows = [r for r in rows
                if r["prerequisite_competency_id"] == prerequisite_id]
    status = _arg("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    level = _arg("level")
    if level is not None:
        rows = [r for r in rows if r["level"] == level]
    rows = store.sort_rows(rows, [(lambda r: r["code"], False)])
    return paginated(rows, serialize.competency)


@bp.route("/competencies/<cid>/prerequisite", methods=["POST"])
def set_prerequisite(cid):
    require(ROLE_REGISTRAR)
    competency = lookup.competency(cid)
    body = json_body()
    prerequisite_id = shape.opt_id(body, "prerequisite_competency_id")
    if prerequisite_id is not None:
        lookup.competency(prerequisite_id)
    program = lookup.program_of_competency(competency)
    if program is None or program["status"] != "PUBLISHED":
        raise ApiError("ERR_PROGRAM_NOT_PUBLISHED")
    _guard_prerequisite(competency, competency["program_id"], prerequisite_id)
    competency["prerequisite_competency_id"] = prerequisite_id
    touch(competency)
    return object_response(serialize.competency(competency))


@bp.route("/competencies/<cid>/retire", methods=["POST"])
def retire_competency(cid):
    require(ROLE_REGISTRAR)
    competency = lookup.competency(cid)
    if competency["status"] != "ACTIVE":
        raise ApiError("ERR_COMPETENCY_RETIRED")
    for att in db.attempts.values():
        if (att["competency_id"] == competency["id"]
                and att["status"] in derive.LIVE_ATTEMPT_STATUSES):
            raise bad_request(
                "A competency with attempts still in flight cannot be retired.")
    for other in db.competencies.values():
        if (other["prerequisite_competency_id"] == competency["id"]
                and other["status"] == "ACTIVE"):
            raise bad_request(
                "An active competency still names this one as its prerequisite.")
    competency["status"] = "RETIRED"
    touch(competency)
    for blueprint_row in lookup.blueprints_of(competency["id"]):
        if blueprint_row["status"] == "PUBLISHED":
            blueprint_row["effective_to_utc"] = db.now()
            blueprint_row["status"] = "SUPERSEDED"
            touch(blueprint_row)
    program = lookup.program_of_competency(competency)
    if program is not None:
        touch(program)
    return object_response(serialize.competency(competency))


# ---------------------------------------------------------------- blueprints

def _read_dimensions(body):
    raw = body.get("dimensions", None)
    if raw is None:
        raise bad_request("Field 'dimensions' is required.")
    if not isinstance(raw, list):
        raise bad_request("Field 'dimensions' must be an array.")
    if len(raw) < 1 or len(raw) > 8:
        raise ApiError("ERR_RUBRIC_WEIGHTS_INVALID")
    dimensions = []
    codes = set()
    total = ZERO
    for element in raw:
        if not isinstance(element, dict):
            raise bad_request("Each rubric dimension must be an object.")
        code = element.get("code", None)
        if not isinstance(code, str) or code.strip() == "":
            raise ApiError("ERR_RUBRIC_WEIGHTS_INVALID")
        code = code.strip()
        if code in codes:
            raise ApiError("ERR_RUBRIC_WEIGHTS_INVALID")
        codes.add(code)
        weight = dec(element.get("weight", None))
        if weight is None or weight <= ZERO:
            raise ApiError("ERR_RUBRIC_WEIGHTS_INVALID")
        weight = rhu(weight, 4)
        max_score = element.get("max_score", None)
        if isinstance(max_score, bool):
            raise ApiError("ERR_RUBRIC_WEIGHTS_INVALID")
        if isinstance(max_score, float) and float(max_score).is_integer():
            max_score = int(max_score)
        if not isinstance(max_score, int) or max_score <= 0:
            raise ApiError("ERR_RUBRIC_WEIGHTS_INVALID")
        critical = element.get("critical", False)
        if critical is None:
            critical = False
        if not isinstance(critical, bool):
            raise bad_request("A rubric dimension's 'critical' must be boolean.")
        total = total + weight
        dimensions.append({"code": code, "weight": weight,
                           "max_score": max_score, "critical": critical})
    if total != ONE:
        raise ApiError("ERR_RUBRIC_WEIGHTS_INVALID")
    return dimensions


@bp.route("/assessment-blueprints", methods=["POST"])
def publish_blueprint():
    require(ROLE_REGISTRAR)
    body = json_body()
    competency = lookup.competency(shape.req_id(body, "competency_id"))
    expected = shape.req_expected_version(body, "expected_competency_version")
    passing_rule = shape.req_enum(body, "passing_rule", PASSING_RULES)
    reader_count = shape.req_int(body, "required_evaluator_count")
    if reader_count not in (1, 2):
        raise bad_request("Field 'required_evaluator_count' must be 1 or 2.")
    effective_from = shape.req_instant(body, "effective_from_utc")
    if competency["status"] != "ACTIVE":
        raise ApiError("ERR_COMPETENCY_RETIRED")
    if expected != competency["version"]:
        raise ApiError("ERR_STALE_VERSION")
    dimensions = _read_dimensions(body)
    program = lookup.program_of_competency(competency)
    current = derive.current_published_blueprint(competency)
    if current is not None:
        if effective_from <= current["effective_from_utc"]:
            raise ApiError("ERR_BLUEPRINT_WINDOW_NOT_CONTIGUOUS")
        earliest = store.add_days(db.now(), program["blueprint_notice_days"])
        if effective_from < earliest:
            raise ApiError("ERR_BLUEPRINT_NOTICE_TOO_SHORT")
    row = new_row()
    row.update({
        "competency_id": competency["id"],
        "dimensions": dimensions,
        "passing_rule": passing_rule,
        "required_evaluator_count": reader_count,
        "effective_from_utc": effective_from,
        "effective_to_utc": None,
        "status": "PUBLISHED",
    })
    if current is not None:
        current["effective_to_utc"] = effective_from
        current["status"] = "SUPERSEDED"
        touch(current)
    db.blueprints[row["id"]] = row
    touch(competency)
    return created_response(serialize.blueprint(row))


@bp.route("/assessment-blueprints/<bid>", methods=["GET"])
def read_blueprint(bid):
    require(*READ_MAP_ROLES)
    return object_response(serialize.blueprint(lookup.blueprint(bid)))


@bp.route("/assessment-blueprints", methods=["GET"])
def list_blueprints():
    require(*READ_MAP_ROLES)
    rows = list(db.blueprints.values())
    competency_id = _arg("competency_id")
    if competency_id is not None:
        rows = [r for r in rows if r["competency_id"] == competency_id]
    status = _arg("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = store.sort_rows(rows, [(lambda r: r["effective_from_utc"], False)])
    return paginated(rows, serialize.blueprint)
