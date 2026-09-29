"""Recruitment geography, the recruiter roster and seasonal coverage."""

from flask import Blueprint

import calc
import flows
from auth import read_only, require
from errors import ApiError
from envelope import success, success_list
from store import bump, mark_fresh, store, touch_only
from support import fetch, matches, paginate
from validation import (get_date, get_enum, get_id, get_int, get_state_code,
                        get_string, iso_date, pagination_params, parse_iso_date,
                        query_enum, query_string, read_body)

bp = Blueprint("areas", __name__)

ACTIVITIES = ("AGRICULTURE", "FISHING")
AREA_STATUSES = ("OPEN", "CLOSED")
CREDENTIALS = ("BASIC", "CERTIFIED", "QC_CERTIFIED")
RECRUITER_STATUSES = ("ACTIVE", "SUSPENDED")
COVERAGE_ROLES = ("PRIMARY", "BACKUP")
ASSIGNMENT_STATUSES = ("PLANNED", "ACTIVE", "COMPLETED", "CANCELLED")
OUTCOMES = ("COMPLETED", "CANCELLED")


# =========================================================================
# agricultural areas
# =========================================================================

@bp.route("/mep/areas", methods=["POST"])
@require("StateProgramAdmin")
def create_area():
    body = read_body()
    name = get_string(body, "name", required=True, min_len=1, max_len=120)
    state_code = get_state_code(body, "state_code", required=True)
    activity = get_enum(body, "primary_activity", ACTIVITIES, required=True)
    peak_start = get_date(body, "peak_season_start_date", required=True)
    peak_end = get_date(body, "peak_season_end_date", required=True)
    capacity = get_int(body, "recruiter_capacity", minimum=1, maximum=12, default=1)
    status = get_enum(body, "status", AREA_STATUSES, default="OPEN")
    if peak_start > peak_end:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "'peak_season_start_date' must not be later than 'peak_season_end_date'",
        )

    created = store.now_iso()
    row = {
        "id": store.new_id(),
        "name": name,
        "state_code": state_code,
        "primary_activity": activity,
        "peak_season_start_date": iso_date(peak_start),
        "peak_season_end_date": iso_date(peak_end),
        "recruiter_capacity": capacity,
        "status": status,
        "assigned_primary_slots_used": 0,
        "created_at": created,
        "updated_at": created,
        "version": 1,
    }
    store.areas[row["id"]] = row
    mark_fresh(row)
    return success(row, 201)


@bp.route("/mep/areas/<area_id>", methods=["GET"])
@read_only
def read_area(area_id):
    area = fetch("area", area_id)
    flows.republish_area_counter(area)
    return success(area)


@bp.route("/mep/areas/<area_id>", methods=["PATCH"])
@require("StateProgramAdmin")
def amend_area(area_id):
    area = fetch("area", area_id)
    body = read_body()
    status = get_enum(body, "status", AREA_STATUSES)
    capacity = get_int(body, "recruiter_capacity", minimum=1, maximum=12)
    peak_start = get_date(body, "peak_season_start_date")
    peak_end = get_date(body, "peak_season_end_date")

    effective_start = peak_start or parse_iso_date(area["peak_season_start_date"])
    effective_end = peak_end or parse_iso_date(area["peak_season_end_date"])
    if effective_start > effective_end:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "'peak_season_start_date' must not be later than 'peak_season_end_date'",
        )

    if status is not None:
        area["status"] = status
    if capacity is not None:
        area["recruiter_capacity"] = capacity
    if peak_start is not None:
        area["peak_season_start_date"] = iso_date(peak_start)
    if peak_end is not None:
        area["peak_season_end_date"] = iso_date(peak_end)
    bump(area)
    return success(area)


# =========================================================================
# recruiters
# =========================================================================

@bp.route("/mep/recruiters", methods=["POST"])
@require("StateProgramAdmin")
def create_recruiter():
    body = read_body()
    full_name = get_string(body, "full_name", required=True, min_len=1, max_len=120)
    state_code = get_state_code(body, "state_code", required=True)
    credential = get_enum(body, "credential_level", CREDENTIALS, default="BASIC")
    status = get_enum(body, "status", RECRUITER_STATUSES, default="ACTIVE")

    created = store.now_iso()
    row = {
        "id": store.new_id(),
        "full_name": full_name,
        "state_code": state_code,
        "credential_level": credential,
        "status": status,
        "active_assignment_count": 0,
        "created_at": created,
        "updated_at": created,
        "version": 1,
    }
    store.recruiters[row["id"]] = row
    mark_fresh(row)
    return success(row, 201)


@bp.route("/mep/recruiters/<recruiter_id>", methods=["GET"])
@read_only
def read_recruiter(recruiter_id):
    recruiter = fetch("recruiter", recruiter_id)
    flows.republish_recruiter_counter(recruiter)
    return success(recruiter)


@bp.route("/mep/recruiters/<recruiter_id>", methods=["PATCH"])
@require("StateProgramAdmin")
def amend_recruiter(recruiter_id):
    recruiter = fetch("recruiter", recruiter_id)
    body = read_body()
    status = get_enum(body, "status", RECRUITER_STATUSES)
    credential = get_enum(body, "credential_level", CREDENTIALS)
    full_name = get_string(body, "full_name", min_len=1, max_len=120)

    if status is not None:
        recruiter["status"] = status
    if credential is not None:
        recruiter["credential_level"] = credential
    if full_name is not None:
        recruiter["full_name"] = full_name
    bump(recruiter)
    return success(recruiter)


# =========================================================================
# coverage assignments
# =========================================================================

@bp.route("/mep/recruiter-assignments", methods=["POST"])
@require("StateProgramAdmin")
def create_assignment():
    body = read_body()
    # rung 4 -- shape
    area_id = get_id(body, "area_id", required=True)
    recruiter_id = get_id(body, "recruiter_id", required=True)
    coverage_role = get_enum(body, "coverage_role", COVERAGE_ROLES, required=True)
    starts_on = get_date(body, "starts_on", required=True)
    ends_on = get_date(body, "ends_on", required=True)
    expected_area_version = get_int(body, "expected_area_version", required=True)
    if starts_on > ends_on:
        raise ApiError("ERR_INVALID_REQUEST", "'starts_on' must not be later than 'ends_on'")

    # rung 5 -- body-referenced existence, area_id then recruiter_id
    area = fetch("area", area_id)
    recruiter = fetch("recruiter", recruiter_id)

    # rung 7 -- stale area version
    if expected_area_version != area["version"]:
        raise ApiError(
            "ERR_STALE_AREA_VERSION",
            "Area version is %s, not the expected %s" % (area["version"], expected_area_version),
        )

    # rung 19 -- peak-season containment (PRIMARY only)
    if coverage_role == "PRIMARY" and not calc.peak_season_contained(area, starts_on, ends_on):
        raise ApiError(
            "ERR_PEAK_SEASON_NOT_COVERED",
            "Primary coverage must span %s through %s" % (
                area["peak_season_start_date"], area["peak_season_end_date"]),
        )

    # rung 20 -- unbuffered recruiter interval conflict
    if calc.recruiter_conflict(recruiter_id, starts_on, ends_on):
        raise ApiError(
            "ERR_RECRUITER_ASSIGNMENT_OVERLAP",
            "Recruiter already holds coverage intersecting these dates",
        )

    # rungs 22 and 23 -- standing gates
    if recruiter["status"] != "ACTIVE":
        raise ApiError("ERR_RECRUITER_NOT_ACTIVE", "Recruiter is not ACTIVE")
    if area["status"] != "OPEN":
        raise ApiError("ERR_AREA_NOT_OPEN", "Area is not OPEN for coverage")

    # rung 29 -- buffered area occupancy
    if calc.peak_occupancy(area_id, starts_on, ends_on) > area["recruiter_capacity"]:
        raise ApiError(
            "ERR_AREA_COVERAGE_CAPACITY_EXCEEDED",
            "Buffered coverage would exceed the area capacity of %s"
            % area["recruiter_capacity"],
        )

    created = store.now_iso()
    row = {
        "id": store.new_id(),
        "recruiter_id": recruiter_id,
        "area_id": area_id,
        "coverage_role": coverage_role,
        "starts_on": iso_date(starts_on),
        "ends_on": iso_date(ends_on),
        "status": "PLANNED",
        "cancelled_reason": None,
        "created_at": created,
        "updated_at": created,
        "version": 1,
    }
    store.assignments[row["id"]] = row
    mark_fresh(row)

    flows.republish_area_counter(area)
    bump(area)
    flows.republish_recruiter_counter(recruiter)
    touch_only(recruiter)
    return success(row, 201)


@bp.route("/mep/recruiter-assignments/<assignment_id>", methods=["GET"])
@read_only
def read_assignment(assignment_id):
    return success(fetch("assignment", assignment_id))


@bp.route("/mep/recruiter-assignments", methods=["GET"])
@read_only
def list_assignments():
    limit, offset = pagination_params()
    filters = {
        "recruiter_id": query_string("recruiter_id"),
        "area_id": query_string("area_id"),
        "coverage_role": query_enum("coverage_role", COVERAGE_ROLES),
        "status": query_enum("status", ASSIGNMENT_STATUSES),
    }
    rows = [row for row in store.assignments.values() if matches(row, filters)]
    page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/mep/recruiter-assignments/<assignment_id>/activate", methods=["POST"])
@require("StateProgramAdmin")
def activate_assignment(assignment_id):
    assignment = fetch("assignment", assignment_id)
    if assignment["status"] != "PLANNED":
        raise ApiError(
            "ERR_ASSIGNMENT_INVALID_STATE",
            "Assignment is %s, not PLANNED" % assignment["status"],
        )
    recruiter = store.recruiters.get(assignment["recruiter_id"])
    area = store.areas.get(assignment["area_id"])
    if recruiter is None or recruiter["status"] != "ACTIVE":
        raise ApiError("ERR_RECRUITER_NOT_ACTIVE", "Recruiter is not ACTIVE")
    if area is None or area["status"] != "OPEN":
        raise ApiError("ERR_AREA_NOT_OPEN", "Area is not OPEN for coverage")

    assignment["status"] = "ACTIVE"
    bump(assignment)
    flows.republish_area_counter(area)
    bump(area)
    flows.republish_recruiter_counter(recruiter)
    bump(recruiter)
    return success(assignment)


@bp.route("/mep/recruiter-assignments/<assignment_id>/close", methods=["POST"])
@require("StateProgramAdmin")
def close_assignment(assignment_id):
    assignment = fetch("assignment", assignment_id)
    body = read_body()
    outcome = get_enum(body, "outcome", OUTCOMES, required=True)
    cancelled_reason = get_string(body, "cancelled_reason", min_len=1, max_len=240)

    current = assignment["status"]
    if outcome == "COMPLETED":
        if current != "ACTIVE":
            raise ApiError(
                "ERR_ASSIGNMENT_INVALID_STATE",
                "Only an ACTIVE assignment may be COMPLETED; this one is %s" % current,
            )
        assignment["status"] = "COMPLETED"
    else:
        if current not in ("PLANNED", "ACTIVE"):
            raise ApiError(
                "ERR_ASSIGNMENT_INVALID_STATE",
                "Assignment is already %s" % current,
            )
        assignment["status"] = "CANCELLED"
        if cancelled_reason is not None:
            assignment["cancelled_reason"] = cancelled_reason

    bump(assignment)
    recruiter = store.recruiters.get(assignment["recruiter_id"])
    area = store.areas.get(assignment["area_id"])
    if area is not None:
        flows.republish_area_counter(area)
        bump(area)
    if recruiter is not None:
        flows.republish_recruiter_counter(recruiter)
        bump(recruiter)
    return success(assignment)
