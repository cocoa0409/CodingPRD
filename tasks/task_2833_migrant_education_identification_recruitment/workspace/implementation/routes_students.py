"""Child identification, priority scoring, qualifying moves and interviews."""

from decimal import Decimal

from flask import Blueprint

import calc
import flows
from auth import caller_id, read_only, require
from errors import ApiError
from envelope import success, success_list
from store import bump, mark_fresh, store
from support import fetch, matches, paginate
from validation import (get_bool, get_date, get_decimal, get_enum, get_id,
                        get_int, get_state_code, get_string, iso_date,
                        pagination_params, parse_iso_date, query_bool,
                        query_enum, query_string, read_body, round_half_up)

bp = Blueprint("students", __name__)

ZERO = Decimal("0.00")

SCHOOLING = ("ENROLLED", "OUT_OF_SCHOOL")
ELIGIBILITY_STATUSES = ("NOT_ELIGIBLE", "PENDING_DETERMINATION", "ELIGIBLE",
                        "CONTINUATION", "TERM_EXPIRED")
SERVICE_STATUSES = ("UNSERVED", "PLAN_DRAFTED", "RECEIVING_SERVICES", "EXITED")
WORK_TYPES = ("AGRICULTURAL", "FISHING", "NONE")
WORKER_RELATIONSHIPS = ("SELF", "PARENT", "GUARDIAN", "SPOUSE")
PURPOSES = ("SEEK_OR_OBTAIN_QUALIFYING_WORK", "ACCOMPANY_WORKER")
MOVE_STATUSES = ("RECORDED", "VERIFIED", "REJECTED")
DECISIONS = ("VERIFIED", "REJECTED")
INTERVIEW_KINDS = ("INITIAL", "QC_REINTERVIEW")
INFORMANTS = ("PARENT", "GUARDIAN", "SELF", "EMPLOYER", "OTHER")
INTERVIEW_OUTCOMES = ("SUPPORTS_ELIGIBILITY", "CONTRADICTS_ELIGIBILITY", "INCONCLUSIVE")


def whole_years_between(start, end):
    years = end.year - start.year
    if (end.month, end.day) < (start.month, start.day):
        years -= 1
    return years


# =========================================================================
# students
# =========================================================================

@bp.route("/mep/students", methods=["POST"])
@require("Recruiter")
def create_student():
    body = read_body()
    full_name = get_string(body, "full_name", required=True, min_len=1, max_len=120)
    birth_date = get_date(body, "birth_date", required=True)
    current_state_code = get_state_code(body, "current_state_code", required=True)
    area_id = get_id(body, "area_id", required=True)
    schooling_status = get_enum(body, "schooling_status", SCHOOLING, default="ENROLLED")
    grade_level = get_int(body, "grade_level", minimum=0, maximum=12, default=None)
    interrupted = get_int(body, "school_days_interrupted", minimum=0, maximum=180, default=0)
    credit_deficit = get_int(body, "credit_deficit", minimum=0, maximum=40, default=0)
    math_below = get_bool(body, "math_below_grade", default=False)
    reading_below = get_bool(body, "reading_below_grade", default=False)
    has_credential = get_bool(body, "has_hs_credential", default=False)
    language_flag = get_bool(body, "primary_language_not_english", default=False)

    if birth_date >= store.clock_date():
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "'birth_date' must be strictly earlier than the current logical clock date",
        )

    fetch("area", area_id)

    created = store.now_iso()
    row = {
        "id": store.new_id(),
        "full_name": full_name,
        "birth_date": iso_date(birth_date),
        "current_state_code": current_state_code,
        "area_id": area_id,
        "schooling_status": schooling_status,
        "grade_level": grade_level,
        "school_days_interrupted": interrupted,
        "credit_deficit": credit_deficit,
        "math_below_grade": math_below,
        "reading_below_grade": reading_below,
        "has_hs_credential": has_credential,
        "primary_language_not_english": language_flag,
        "prior_record_student_id": None,
        "eligibility_status": "NOT_ELIGIBLE",
        "service_status": "UNSERVED",
        "pfs_score": 0,
        "pfs_variant": "INTERRUPTION_WEIGHTED",
        "pfs_flag": False,
        "eligibility_expires_on": None,
        "total_service_hours_ledger": ZERO,
        "transferred_credits_count": ZERO,
        "locally_accrued_credits": ZERO,
        "total_awarded_credits": ZERO,
        "created_at": created,
        "updated_at": created,
        "version": 1,
    }
    store.students[row["id"]] = row
    mark_fresh(row)
    flows.persist_pfs(row)
    return success(row, 201)


@bp.route("/mep/students/<student_id>", methods=["GET"])
@read_only
def read_student(student_id):
    return success(fetch("student", student_id))


@bp.route("/mep/students", methods=["GET"])
@read_only
def list_students():
    limit, offset = pagination_params()
    filters = {
        "area_id": query_string("area_id"),
        "prior_record_student_id": query_string("prior_record_student_id"),
        "eligibility_status": query_enum("eligibility_status", ELIGIBILITY_STATUSES),
        "service_status": query_enum("service_status", SERVICE_STATUSES),
        "schooling_status": query_enum("schooling_status", SCHOOLING),
        "pfs_flag": query_bool("pfs_flag"),
    }
    rows = [row for row in store.students.values() if matches(row, filters)]
    page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/mep/students/<student_id>", methods=["PATCH"])
@require("Recruiter", "ServiceCoordinator")
def amend_student(student_id):
    student = fetch("student", student_id)
    body = read_body()
    current_state_code = get_state_code(body, "current_state_code")
    area_id = get_id(body, "area_id")
    schooling_status = get_enum(body, "schooling_status", SCHOOLING)
    grade_level = get_int(body, "grade_level", minimum=0, maximum=12)
    interrupted = get_int(body, "school_days_interrupted", minimum=0, maximum=180)
    credit_deficit = get_int(body, "credit_deficit", minimum=0, maximum=40)
    math_below = get_bool(body, "math_below_grade")
    reading_below = get_bool(body, "reading_below_grade")
    has_credential = get_bool(body, "has_hs_credential")
    language_flag = get_bool(body, "primary_language_not_english")

    if area_id is not None:
        fetch("area", area_id)

    if current_state_code is not None:
        student["current_state_code"] = current_state_code
    if area_id is not None:
        student["area_id"] = area_id
    if schooling_status is not None:
        student["schooling_status"] = schooling_status
    if grade_level is not None:
        student["grade_level"] = grade_level
    elif "grade_level" in body and body["grade_level"] is None:
        student["grade_level"] = None
    if interrupted is not None:
        student["school_days_interrupted"] = interrupted
    if credit_deficit is not None:
        student["credit_deficit"] = credit_deficit
    if math_below is not None:
        student["math_below_grade"] = math_below
    if reading_below is not None:
        student["reading_below_grade"] = reading_below
    if has_credential is not None:
        student["has_hs_credential"] = has_credential
    if language_flag is not None:
        student["primary_language_not_english"] = language_flag

    flipped = flows.persist_pfs(student)
    bump(student)
    if flipped:
        flows.run_allocation(student)
    return success(student)


@bp.route("/mep/students/<student_id>/pfs-assessment", methods=["GET"])
@read_only
def read_pfs_assessment(student_id):
    student = fetch("student", student_id)
    return success(calc.pfs_assessment(student))


# =========================================================================
# qualifying moves
# =========================================================================

@bp.route("/mep/qualifying-moves", methods=["POST"])
@require("Recruiter")
def create_move():
    body = read_body()
    student_id = get_id(body, "student_id", required=True)
    from_state = get_state_code(body, "from_state_code", required=True)
    to_state = get_state_code(body, "to_state_code", required=True)
    move_date = get_date(body, "move_date", required=True)
    work_type = get_enum(body, "work_type", WORK_TYPES, required=True)
    relationship = get_enum(body, "worker_relationship", WORKER_RELATIONSHIPS, required=True)
    purpose = get_enum(body, "purpose", PURPOSES, required=True)
    distance = get_decimal(body, "distance_miles", required=True, exclusive_minimum=ZERO)

    student = fetch("student", student_id)

    if move_date > store.clock_date():
        raise ApiError(
            "ERR_MOVE_DATE_IN_FUTURE",
            "'move_date' is later than the current logical clock date",
        )

    created = store.now_iso()
    row = {
        "id": store.new_id(),
        "student_id": student_id,
        "from_state_code": from_state,
        "to_state_code": to_state,
        "move_date": iso_date(move_date),
        "work_type": work_type,
        "worker_relationship": relationship,
        "purpose": purpose,
        "distance_miles": round_half_up(distance),
        "status": "RECORDED",
        "adjudicated_on": None,
        "student_age_at_move": whole_years_between(
            parse_iso_date(student["birth_date"]), move_date),
        "created_at": created,
        "updated_at": created,
        "version": 1,
    }
    store.moves[row["id"]] = row
    mark_fresh(row)
    return success(row, 201)


@bp.route("/mep/qualifying-moves/<move_id>", methods=["GET"])
@read_only
def read_move(move_id):
    return success(fetch("move", move_id))


@bp.route("/mep/qualifying-moves", methods=["GET"])
@read_only
def list_moves():
    limit, offset = pagination_params()
    filters = {
        "student_id": query_string("student_id"),
        "status": query_enum("status", MOVE_STATUSES),
        "work_type": query_enum("work_type", WORK_TYPES),
    }
    rows = [row for row in store.moves.values() if matches(row, filters)]
    page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/mep/qualifying-moves/<move_id>/adjudicate", methods=["POST"])
@require("StateProgramAdmin")
def adjudicate_move(move_id):
    move = fetch("move", move_id)
    body = read_body()
    decision = get_enum(body, "decision", DECISIONS, required=True)

    if move["status"] != "RECORDED":
        raise ApiError(
            "ERR_MOVE_ALREADY_ADJUDICATED",
            "Move has already been adjudicated as %s" % move["status"],
        )
    if decision == "VERIFIED" and move["work_type"] == "NONE":
        raise ApiError(
            "ERR_MOVE_NOT_QUALIFYING",
            "A move with a work_type of NONE can never be verified",
        )

    move["status"] = decision
    move["adjudicated_on"] = store.clock_instant()
    bump(move)

    student = store.students.get(move["student_id"])
    if student is not None:
        flipped = flows.persist_pfs(student)
        bump(student)
        if flipped:
            flows.run_allocation(student)
    return success(move)


# =========================================================================
# interview records (immutable)
# =========================================================================

@bp.route("/mep/interview-records", methods=["POST"])
@require("Recruiter", "QualityControlReviewer")
def create_interview():
    body = read_body()
    student_id = get_id(body, "student_id", required=True)
    move_id = get_id(body, "move_id", required=True)
    kind = get_enum(body, "interview_kind", INTERVIEW_KINDS, required=True)
    coe_id = get_id(body, "coe_id")
    conducted_on = get_date(body, "conducted_on", required=True)
    informant = get_enum(body, "informant_relationship", INFORMANTS, required=True)
    corroboration = get_int(body, "corroboration_count", minimum=0, maximum=10, default=0)
    outcome = get_enum(body, "outcome", INTERVIEW_OUTCOMES, required=True)
    notes = get_string(body, "documentation_notes", required=True, min_len=1, max_len=2000)

    if kind == "QC_REINTERVIEW" and coe_id is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "'coe_id' is required when interview_kind is QC_REINTERVIEW",
        )
    if kind == "INITIAL" and coe_id is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "'coe_id' must be absent when interview_kind is INITIAL",
        )

    fetch("student", student_id)
    move = fetch("move", move_id)
    if coe_id is not None:
        fetch("coe", coe_id)

    if move["student_id"] != student_id:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "The referenced qualifying move does not belong to this student",
        )
    if conducted_on > store.clock_date():
        raise ApiError(
            "ERR_MOVE_DATE_IN_FUTURE",
            "'conducted_on' is later than the current logical clock date",
        )

    created = store.now_iso()
    row = {
        "id": store.new_id(),
        "student_id": student_id,
        "move_id": move_id,
        "coe_id": coe_id,
        "interview_kind": kind,
        "recruiter_id": caller_id(),
        "conducted_on": iso_date(conducted_on),
        "informant_relationship": informant,
        "corroboration_count": corroboration,
        "outcome": outcome,
        "documentation_notes": notes,
        "created_at": created,
    }
    store.interviews[row["id"]] = row
    return success(row, 201)


@bp.route("/mep/interview-records/<interview_id>", methods=["GET"])
@read_only
def read_interview(interview_id):
    return success(fetch("interview", interview_id))


@bp.route("/mep/interview-records", methods=["GET"])
@read_only
def list_interviews():
    limit, offset = pagination_params()
    filters = {
        "student_id": query_string("student_id"),
        "move_id": query_string("move_id"),
        "recruiter_id": query_string("recruiter_id"),
        "coe_id": query_string("coe_id"),
        "interview_kind": query_enum("interview_kind", INTERVIEW_KINDS),
        "outcome": query_enum("outcome", INTERVIEW_OUTCOMES),
    }
    rows = [row for row in store.interviews.values() if matches(row, filters)]
    page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total)
