"""Provider assignments: suitability, load, and the encumbering waterfall (PRD 3.5)."""
from flask import Blueprint

from auth import PROGRAM_COORDINATOR, endpoint
from calcs import (SERVICE_TYPE_ROLE_TYPES, fund_charge_waterfall,
                   instructional_dates, iso_week, refresh_available)
from envelope import created, ok
from errors import ApiError
from ledgers import leave_assignment, recomputed_provider_load
from resolve import body_ref, path_ref
from serialize import public
from store import creation_order, db, new_record, touch
from validate import (WEEKDAY_NAMES, bad, body, minutes_of, parse_date_str,
                      req_date, req_enum, req_int, req_str, req_time)

bp = Blueprint("assignments", __name__)


def covered_week_count(program, effective_from, effective_to):
    """PRD 3.5: distinct ISO weeks in the range holding an instructional date."""
    start = parse_date_str(effective_from, "effective_from")
    end = parse_date_str(effective_to, "effective_to")
    weeks = set()
    for day in instructional_dates(program):
        if start <= day <= end:
            weeks.add(iso_week(day))
    return len(weeks)


@bp.post("/esy/provider-assignments")
@endpoint((PROGRAM_COORDINATOR,))
def create_provider_assignment():
    data = body()
    # PRD 2.6 enumerates provider_id ahead of commitment_id.
    provider = body_ref(data, "provider_id", "provider")
    commitment = body_ref(data, "commitment_id", "commitment")

    commitment_id = req_str(data, "commitment_id", 1, None)
    provider_id = req_str(data, "provider_id", 1, None)
    weekday = req_enum(data, "weekday", WEEKDAY_NAMES)
    start_time = req_time(data, "start_time")
    end_time = req_time(data, "end_time")
    if minutes_of(end_time) <= minutes_of(start_time):
        raise bad("end_time must be strictly after start_time.")
    effective_from = req_date(data, "effective_from")
    effective_to = req_date(data, "effective_to")
    if parse_date_str(effective_to, "effective_to") < parse_date_str(
            effective_from, "effective_from"):
        raise bad("effective_to must not be earlier than effective_from.")
    covered_weekly_minutes = req_int(data, "covered_weekly_minutes", 1, 3000)
    expected_version = req_int(data, "expected_commitment_version")

    program = db.programs.get(commitment["program_id"])
    if weekday not in program["instructional_weekdays"]:
        raise bad("weekday must be one of the program's instructional_weekdays.")
    window_start = parse_date_str(program["session_start_date"], "effective_from")
    window_end = parse_date_str(program["session_end_date"], "effective_to")
    if (parse_date_str(effective_from, "effective_from") < window_start
            or parse_date_str(effective_to, "effective_to") > window_end):
        raise bad("effective_from and effective_to must fall inside the session window.")

    if commitment["status"] not in ("PLANNED", "ASSIGNED"):
        raise ApiError("ERR_INVALID_STATE")
    if expected_version != commitment["version"]:
        raise ApiError("ERR_STALE_COMMITMENT_VERSION")

    if parse_date_str(provider["credential_expires_on"], "credential_expires_on") \
            < parse_date_str(effective_to, "effective_to"):
        raise ApiError("ERR_PROVIDER_CREDENTIAL_EXPIRED")
    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ACTIVE")
    if provider["role_type"] not in SERVICE_TYPE_ROLE_TYPES[commitment["service_type"]]:
        raise ApiError("ERR_PROVIDER_ROLE_MISMATCH")

    # PRD 3.5: provider windows are HALF-OPEN, and the date ranges must also
    # intersect (inclusively) before a conflict is reported.
    new_start = minutes_of(start_time)
    new_end = minutes_of(end_time)
    new_from = parse_date_str(effective_from, "effective_from")
    new_to = parse_date_str(effective_to, "effective_to")
    for other in db.assignments.values():
        if other["provider_id"] != provider_id or other["status"] != "ACTIVE":
            continue
        if other["weekday"] != weekday:
            continue
        if not (new_start < minutes_of(other["end_time"])
                and minutes_of(other["start_time"]) < new_end):
            continue
        other_from = parse_date_str(other["effective_from"], "effective_from")
        other_to = parse_date_str(other["effective_to"], "effective_to")
        if new_from <= other_to and other_from <= new_to:
            raise ApiError("ERR_PROVIDER_TIME_CONFLICT")

    if recomputed_provider_load(provider, extra=covered_weekly_minutes) \
            > provider["max_weekly_minutes"]:
        raise ApiError("ERR_PROVIDER_CAPACITY_EXCEEDED")

    covered_total_minutes = covered_weekly_minutes * covered_week_count(
        program, effective_from, effective_to)
    charge = fund_charge_waterfall(program["id"], provider["rate_cents_per_minute"],
                                   covered_total_minutes, compensatory=False)
    allocation = charge["allocation"]

    assignment = new_record("ProviderAssignment", {
        "commitment_id": commitment_id,
        "provider_id": provider_id,
        "weekday": weekday,
        "start_time": start_time,
        "end_time": end_time,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "covered_weekly_minutes": covered_weekly_minutes,
        "covered_total_minutes": covered_total_minutes,
        "base_cost_cents": charge["base_cost_cents"],
        "indirect_cost_cents": charge["indirect_cost_cents"],
        "total_charge_cents": charge["total_charge_cents"],
        "charged_fund_source": allocation["fund_source"],
        "charged_budget_code": allocation["budget_code"],
        "status": "ACTIVE",
        "release_reason": None,
    })
    db.assignments[assignment["id"]] = assignment

    allocation["encumbered_amount_cents"] += charge["total_charge_cents"]
    refresh_available(allocation)
    touch(allocation)

    provider["assigned_weekly_minutes"] = recomputed_provider_load(provider)
    touch(provider)

    if commitment["status"] == "PLANNED":
        commitment["status"] = "ASSIGNED"
        touch(commitment)

    for incumbent in creation_order([a for a in db.assignments.values()
                                     if a["commitment_id"] == commitment_id
                                     and a["status"] == "ACTIVE"
                                     and a["id"] != assignment["id"]]):
        leave_assignment(incumbent, "SUPERSEDED", "SUPERSEDED_BY_NEW_ASSIGNMENT")

    return created(public(assignment))


@bp.post("/esy/provider-assignments/<assignment_id>/release")
@endpoint((PROGRAM_COORDINATOR,))
def release_provider_assignment(assignment_id):
    assignment = path_ref("assignment", assignment_id)
    data = body()
    release_reason = req_str(data, "release_reason", 1, None)

    if assignment["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    leave_assignment(assignment, "RELEASED", release_reason)

    commitment = db.commitments.get(assignment["commitment_id"])
    if commitment is not None:
        remaining = any(a["commitment_id"] == commitment["id"] and a["status"] == "ACTIVE"
                        for a in db.assignments.values())
        if not remaining and commitment["status"] == "ASSIGNED":
            commitment["status"] = "PLANNED"
        touch(commitment)
    return ok(public(assignment))
