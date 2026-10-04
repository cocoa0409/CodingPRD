"""Housing assignment endpoints: booking, re-booking, activation, vacation
(PRD §2.6, §3.4)."""

from flask import Blueprint

from db import DB, new_row, touch
from errors import ApiError
from http_util import body_json, optional, required, require_role
from response import success_object
from routes._common import arg, filtered, list_response, ordered
from services import (
    assigned_tier_for_enrollment, billed_nights, facility_capacity_ok,
    find_facility_for_booking, get_or_404, housing_cost, pick_candidates,
    protocol_for_enrollment, referral_for_enrollment, recompute_facility_beds,
    recompute_pledge_derived, recompute_protocol_committed,
    serialize_assignment, settle_pledge,
)

bp = Blueprint("assignments", __name__)

VALID_VACATE_REASONS = {"TREATMENT_COMPLETE", "TRANSFERRED_AFFILIATE", "RELOCATED"}


def _referral_for(enrollment):
    return referral_for_enrollment(enrollment)


@bp.post("/programs/housing-assignments")
def create_assignment():
    require_role("HousingCoordinator")
    data = body_json()
    enrollment_id = required(data, "enrollment_id", "str")
    enrollment = get_or_404("enrollments", enrollment_id)
    start_at = required(data, "start_at", "datetime")
    end_at = required(data, "end_at", "datetime")
    optional(data, "buffer_window_days", None, "int")
    if not (start_at < end_at):
        raise ApiError("ERR_INVALID_REQUEST")

    referral = _referral_for(enrollment)
    if referral is None:
        raise ApiError("ERR_INVALID_REQUEST")

    required_tier = assigned_tier_for_enrollment(enrollment)
    # A booking with no bed available at the endpoint is a capacity refusal, not
    # an empty candidate set: PRD §2.6 keeps ERR_NO_HOUSING_AVAILABLE for "the
    # candidate set is empty" and reports ERR_HOUSING_CAPACITY_EXCEEDED when the
    # candidate exists but the window does not fit. Try the preferred residence
    # first, then fall back to any candidate that can take the window.
    candidates = pick_candidates(required_tier)
    facility = None
    for candidate in candidates:
        if (referral.get("is_immunosuppressed")
                and not candidate["immunosuppression_capable"]):
            continue
        if (referral.get("has_febrile_neutropenia_risk")
                and candidate["tier"] != "ON_CAMPUS"):
            continue
        if not facility_capacity_ok(candidate, start_at, end_at):
            continue
        facility = candidate
        break
    if facility is None:
        if candidates:
            raise ApiError("ERR_HOUSING_CAPACITY_EXCEEDED")
        raise ApiError("ERR_NO_HOUSING_AVAILABLE")

    if referral.get("is_immunosuppressed") and not facility["immunosuppression_capable"]:
        raise ApiError("ERR_HOUSING_IMMUNOSUPPRESSION_INCOMPATIBLE")
    if referral.get("has_febrile_neutropenia_risk") and facility["tier"] != "ON_CAMPUS":
        raise ApiError("ERR_HOUSING_IMMUNOSUPPRESSION_INCOMPATIBLE")

    assignment = new_row({
        "enrollment_id": enrollment["id"],
        "housing_facility_id": facility["id"],
        "start_at": start_at,
        "end_at": end_at,
        "assigned_tier": facility["tier"],
        "nightly_rate_cents": None,
        "billed_nights": billed_nights(start_at, end_at),
        "housing_cost_cents": 0,
        "is_active_occupancy": False,
        "vacated_reason": None,
        "status": "SCHEDULED",
    })
    assignment["housing_cost_cents"] = housing_cost(
        assignment["assigned_tier"], start_at, end_at)
    DB["housing_assignments"][assignment["id"]] = assignment
    recompute_facility_beds(facility)
    return success_object(serialize_assignment(assignment), 201)


@bp.get("/programs/housing-assignments")
def list_assignments():
    require_role("Any")
    enrollment_id = arg("enrollment_id")
    housing_facility_id = arg("housing_facility_id")
    status = arg("status")
    rows = ordered(DB["housing_assignments"].values())
    rows = filtered(rows, enrollment_id=enrollment_id,
                    housing_facility_id=housing_facility_id, status=status)
    return list_response(rows, serialize_assignment)


@bp.get("/programs/housing-assignments/<assignment_id>")
def get_assignment(assignment_id):
    require_role("Any")
    assignment = get_or_404("housing_assignments", assignment_id)
    return success_object(serialize_assignment(assignment), 200)


@bp.put("/programs/housing-assignments/<assignment_id>")
def update_assignment(assignment_id):
    require_role("HousingCoordinator")
    assignment = get_or_404("housing_assignments", assignment_id)
    enrollment = get_or_404("enrollments", assignment["enrollment_id"])
    referral = _referral_for(enrollment)
    # PRD §2.6 / §2.13: re-booking replaces a window — "The same test is re-run
    # whenever a scheduled assignment is re-booked to a new window" — so the
    # target must still be SCHEDULED; any other status meets the generic state
    # requirement and reports ERR_INVALID_STATE (HTTP 409).
    if assignment["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    data = body_json()
    start_at = optional(data, "start_at", assignment["start_at"], "str")
    end_at = optional(data, "end_at", assignment["end_at"], "str")
    if not (start_at < end_at):
        raise ApiError("ERR_INVALID_REQUEST")

    facility = DB["housing_facilities"].get(assignment["housing_facility_id"])
    required_tier = assigned_tier_for_enrollment(enrollment)
    candidate_tiers = set()
    from services import FACILITY_CAPABILITY
    candidate_tiers = set(FACILITY_CAPABILITY[required_tier])

    if facility is None or facility["tier"] not in candidate_tiers:
        replacement = find_facility_for_booking(
            {"required_tier": required_tier}, start_at, end_at,
            exclude={assignment["id"]})
        if replacement is None:
            raise ApiError("ERR_NO_HOUSING_AVAILABLE")
        facility = replacement
        assignment["housing_facility_id"] = facility["id"]

    # The step-down gate: a family may not be moved out of ON_CAMPUS until its
    # immunosuppression status has been cleared (PRD §3.4).
    if (assignment["assigned_tier"] == "ON_CAMPUS"
            and facility["tier"] != "ON_CAMPUS"
            and referral is not None
            and (referral.get("is_immunosuppressed")
                 or referral.get("has_febrile_neutropenia_risk"))):
        raise ApiError("ERR_STEP_DOWN_NOT_PERMITTED")

    if referral is not None:
        if referral.get("is_immunosuppressed") and not facility["immunosuppression_capable"]:
            raise ApiError("ERR_HOUSING_IMMUNOSUPPRESSION_INCOMPATIBLE")
        if referral.get("has_febrile_neutropenia_risk") and facility["tier"] != "ON_CAMPUS":
            raise ApiError("ERR_HOUSING_IMMUNOSUPPRESSION_INCOMPATIBLE")

    if not facility_capacity_ok_for(assignment, facility, start_at, end_at):
        replacement = find_facility_for_booking(
            {"required_tier": required_tier}, start_at, end_at,
            exclude={assignment["id"]})
        if replacement is None:
            raise ApiError("ERR_HOUSING_CAPACITY_EXCEEDED")
        facility = replacement
        assignment["housing_facility_id"] = facility["id"]

    assignment["start_at"] = start_at
    assignment["end_at"] = end_at
    assignment["assigned_tier"] = facility["tier"]
    assignment["billed_nights"] = billed_nights(start_at, end_at)
    assignment["housing_cost_cents"] = housing_cost(
        assignment["assigned_tier"], start_at, end_at)
    recompute_facility_beds(facility)
    touch(enrollment)
    return success_object(serialize_assignment(assignment), 200)


def facility_capacity_ok_for(assignment, facility, start_at, end_at):
    from services import facility_capacity_ok
    return facility_capacity_ok(facility, start_at, end_at,
                                exclude=assignment["id"])


@bp.post("/programs/housing-assignments/<assignment_id>/activate")
def activate_assignment(assignment_id):
    require_role("HousingCoordinator")
    assignment = get_or_404("housing_assignments", assignment_id)
    facility = get_or_404("housing_facilities", assignment["housing_facility_id"])
    enrollment = get_or_404("enrollments", assignment["enrollment_id"])

    if assignment["status"] != "SCHEDULED":
        raise ApiError("ERR_HOUSING_ASSIGNMENT_NOT_SCHEDULED")
    from db import clock, parse_iso
    if parse_iso(assignment["start_at"]) > clock():
        raise ApiError("ERR_OCCUPANCY_NOT_STARTED")
    if facility["status"] != "OPEN":
        raise ApiError("ERR_HOUSING_FACILITY_UNAVAILABLE")
    from services import facility_capacity_ok
    if not facility_capacity_ok(facility, assignment["start_at"],
                                assignment["end_at"], exclude=assignment["id"]):
        raise ApiError("ERR_HOUSING_CAPACITY_EXCEEDED")

    assignment["status"] = "ACTIVE"
    touch(assignment)
    recompute_facility_beds(facility)
    return success_object(serialize_assignment(assignment), 200)


@bp.post("/programs/housing-assignments/<assignment_id>/vacate")
def vacate_assignment(assignment_id):
    require_role("HousingCoordinator")
    assignment = get_or_404("housing_assignments", assignment_id)
    facility = get_or_404("housing_facilities", assignment["housing_facility_id"])
    enrollment = get_or_404("enrollments", assignment["enrollment_id"])
    data = body_json()
    reason = required(data, "vacated_reason", "str")

    if assignment["status"] != "ACTIVE":
        raise ApiError("ERR_HOUSING_ASSIGNMENT_NOT_ACTIVE")
    if reason not in VALID_VACATE_REASONS:
        raise ApiError("ERR_INVALID_VACATE_REASON")

    assignment["status"] = "VACATED"
    assignment["vacated_reason"] = reason
    assignment["is_active_occupancy"] = False
    touch(assignment)
    recompute_facility_beds(facility)

    # The enrollment's sibling session counter resets when occupancy ends.
    referral = _referral_for(enrollment)
    if referral is not None:
        for service in DB["sibling_services"].values():
            if service["enrollment_id"] == enrollment["id"]:
                service["sessions_delivered"] = 0
                service["has_reached_monthly_limit"] = False
                touch(service)

    if reason == "TREATMENT_COMPLETE":
        pledge = None
        candidates = [p for p in DB["pledges"].values()
                      if p["enrollment_id"] == enrollment["id"]]
        candidates.sort(key=lambda p: p["created_at"])
        for candidate in reversed(candidates):
            if candidate["status"] in ("ACTIVE", "SETTLED_FINAL"):
                pledge = candidate
                break
        if pledge is not None:
            recompute_pledge_derived(pledge, enrollment, referral,
                                     protocol_for_enrollment(enrollment))
            touch(pledge)
    return success_object(serialize_assignment(assignment), 200)


@bp.post("/programs/housing-assignments/<assignment_id>/cancel")
def cancel_assignment(assignment_id):
    require_role("HousingCoordinator")
    assignment = get_or_404("housing_assignments", assignment_id)
    facility = get_or_404("housing_facilities", assignment["housing_facility_id"])
    if assignment["status"] != "SCHEDULED":
        raise ApiError("ERR_HOUSING_ASSIGNMENT_NOT_SCHEDULED")
    assignment["status"] = "CANCELLED"
    touch(assignment)
    recompute_facility_beds(facility)
    return success_object(serialize_assignment(assignment), 200)