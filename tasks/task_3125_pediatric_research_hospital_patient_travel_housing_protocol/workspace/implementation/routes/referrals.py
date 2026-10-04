"""Referral endpoints: submission, screening, arrival, withdrawal (PRD §3.2, §3.3)."""

from flask import Blueprint

from db import DB, new_row, now_iso, parse_iso, touch
from errors import ApiError, ValidationFailure
from http_util import body_json, optional, required, require_role
from response import success_object
from routes._common import arg, filtered, list_response, ordered
from services import (
    apply_acceptance, apply_decline, derive_referral_computed, get_or_404,
    is_assent_required, protocol_is_frozen, recompute_protocol_derived,
    release_referral_reservation, screen_check, serialize_enrollment,
    serialize_referral, touch_only,
)

bp = Blueprint("referrals", __name__)

VALID_STAGES = {"NEWLY_DIAGNOSED", "RELAPSED", "REFRACTORY", "REMISSION"}
NON_OPERATIONAL_STATES = {"ENROLLED", "ACTIVE_TREATMENT", "SURVIVORSHIP"}


def _create_row(data, protocol, reopen_source=None, status="SUBMITTED",
                applied_tier="PENDING"):
    referral = new_row({
        "protocol_id": protocol["id"],
        "child_name": required(data, "child_name", "str"),
        "child_date_of_birth": required(data, "child_date_of_birth", "datetime"),
        "disease_group": required(data, "disease_group", "str"),
        "disease_stage": None,
        "household_state_code": required(data, "household_state_code", "str"),
        "traveling_family_member_count": None,
        "expected_treatment_days": None,
        "is_immunosuppressed": False,
        "has_febrile_neutropenia_risk": False,
        "is_self_pay": False,
        "insurance_coverage_cents": 0,
        "one_to_one_care_capability_codes": [],
        "traveling_one_to_one_codes": [],
        "eligibility_alias": "",
        "computed_age_years": 0,
        "screening_fee_cents": 0,
        "selector_window_days": 0,
        "reservation_basis_cents": 0,
        "applied_tier": applied_tier,
        "status": status,
        "enrollment_id": None,
        "decline_reason": None,
        "decline_occurred_at": None,
        "reopened_referral_id": reopen_source["id"] if reopen_source else None,
        "placed_coverages": [],
    })

    stage = required(data, "disease_stage", "str")
    if stage not in VALID_STAGES:
        raise ApiError("ERR_INVALID_REQUEST")
    referral["disease_stage"] = stage

    members = required(data, "traveling_family_member_count", "int")
    if not (1 <= members <= 6):
        raise ApiError("ERR_INVALID_REQUEST")
    referral["traveling_family_member_count"] = members

    days = required(data, "expected_treatment_days", "int")
    if not (1 <= days <= 3650):
        raise ApiError("ERR_INVALID_REQUEST")
    referral["expected_treatment_days"] = days

    if len(referral["household_state_code"]) != 2:
        raise ApiError("ERR_INVALID_REQUEST")

    try:
        parse_iso(referral["child_date_of_birth"])
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST")

    referral["is_immunosuppressed"] = optional(
        data, "is_immunosuppressed", False, "bool")
    referral["has_febrile_neutropenia_risk"] = optional(
        data, "has_febrile_neutropenia_risk", False, "bool")

    insurance = optional(data, "insurance_coverage_cents", 0, "int")
    if insurance < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    referral["insurance_coverage_cents"] = insurance

    codes = optional(data, "one_to_one_care_capability_codes", [], "list")
    for code in codes:
        if not isinstance(code, str):
            raise ApiError("ERR_INVALID_REQUEST")
    referral["one_to_one_care_capability_codes"] = list(codes)

    # An unscreened submission still has no screening fee (PRD §3.2: the fee is
    # recomputed by the screen), but its alias and age are derived at submission.
    derive_referral_computed(referral, protocol, with_fee=False)
    return referral


@bp.post("/programs/referrals")
def create_referral():
    require_role("IntakeCoordinator")
    data = body_json()
    protocol_id = required(data, "protocol_id", "str")
    protocol = get_or_404("protocols", protocol_id)

    reopen_source = None
    reopen_id = optional(data, "reopen_source_referral_id", None, "str")
    if reopen_id is not None:
        reopen_source = DB["referrals"].get(reopen_id)
        if reopen_source is None or reopen_source["status"] != "DECLINED":
            raise ApiError("ERR_REFERRAL_NOT_DECLINED")

    if reopen_source is None:
        referral = _create_row(data, protocol)
        DB["referrals"][referral["id"]] = referral
        return success_object(serialize_referral(referral), 201)

    # A re-open evaluates every screen precondition against the successor.
    referral = _create_row(data, protocol, reopen_source=reopen_source)
    DB["referrals"][referral["id"]] = referral
    try:
        error_id, decline_reason = screen_check(referral, protocol)
    except ValidationFailure as failure:
        DB["referrals"].pop(referral["id"], None)
        raise ApiError(failure.error_id, http_status=409)
    if error_id is not None:
        # The successor carries the new screen outcome, so a failed precondition
        # refuses the re-open rather than creating a second declined row.
        DB["referrals"].pop(referral["id"], None)
        raise ApiError(error_id)
    outcome = apply_acceptance(referral, protocol)
    if outcome != "ACCEPTED":
        DB["referrals"].pop(referral["id"], None)
        raise ApiError("ERR_HOUSING_CAPACITY_EXCEEDED" if outcome == "CAPACITY_EXCEEDED"
                       else "ERR_NO_HOUSING_AVAILABLE")
    touch(referral)
    touch(protocol)
    return success_object(serialize_referral(referral), 201)


@bp.get("/programs/referrals")
def list_referrals():
    require_role("Any")
    protocol_id = arg("protocol_id")
    enrollment_id = arg("enrollment_id")
    status = arg("status")
    household_state_code = arg("household_state_code")
    rows = ordered(DB["referrals"].values())
    rows = filtered(rows, protocol_id=protocol_id, enrollment_id=enrollment_id,
                    status=status, household_state_code=household_state_code)
    return list_response(rows, serialize_referral)


@bp.get("/programs/referrals/<referral_id>")
def get_referral(referral_id):
    require_role("Any")
    referral = get_or_404("referrals", referral_id)
    return success_object(serialize_referral(referral), 200)


@bp.post("/programs/referrals/<referral_id>/screen")
def screen_referral(referral_id):
    require_role("IntakeCoordinator")
    referral = get_or_404("referrals", referral_id)
    protocol = get_or_404("protocols", referral["protocol_id"])
    data = body_json()
    expected = required(data, "expected_protocol_version", "int")

    if referral["status"] != "SUBMITTED":
        raise ApiError("ERR_REFERRAL_NOT_SUBMITTED")
    if expected != int(protocol["version"]):
        raise ApiError("ERR_STALE_VERSION")

    # The fee is charged on every screen attempt, accepted or declined alike; it
    # never moves the protocol's available_cents and it is never refunded.
    derive_referral_computed(referral, protocol)

    try:
        error_id, decline_reason = screen_check(referral, protocol)
    except ValidationFailure as failure:
        # The target protocol is not accepting work at all: the screen itself is
        # refused and the referral is left untouched.
        raise ApiError(failure.error_id, http_status=409)

    if error_id is not None:
        apply_decline(referral, protocol, decline_reason)
        return success_object(serialize_referral(referral), 200)

    outcome = apply_acceptance(referral, protocol)
    if outcome != "ACCEPTED":
        # PRD §2.6 / §3.2: a screen the selector or the endpoint capacity test
        # cannot place turns the referral DECLINED and refuses the call with the
        # matching refusal code (capacity sorts ahead of the fiscal gates).
        apply_decline(referral, protocol, "CAPACITY_FULL" if outcome == "CAPACITY_EXCEEDED" else None)
        referral["applied_tier"] = "DECLINED"
        referral["reservation_basis_cents"] = 0
        touch(referral)
        raise ApiError("ERR_HOUSING_CAPACITY_EXCEEDED" if outcome == "CAPACITY_EXCEEDED"
                       else "ERR_NO_HOUSING_AVAILABLE")

    touch(referral)
    touch(protocol)
    return success_object(serialize_referral(referral), 200)


@bp.post("/programs/referrals/<referral_id>/arrive")
def arrive_referral(referral_id):
    require_role("IntakeCoordinator")
    referral = get_or_404("referrals", referral_id)
    protocol = get_or_404("protocols", referral["protocol_id"])
    data = body_json()
    expected = required(data, "expected_referral_version", "int")

    if referral["status"] != "ACCEPTED":
        raise ApiError("ERR_REFERRAL_NOT_ACCEPTED")
    if expected != int(referral["version"]):
        raise ApiError("ERR_STALE_VERSION")
    if not (protocol["status"] == "OPEN" and not protocol_is_frozen(protocol)):
        raise ApiError("ERR_PROTOCOL_NOT_OPEN")

    referral["status"] = "ARRIVED"
    derive_referral_computed(referral, protocol)

    enrollment = new_row({
        "referral_id": referral["id"],
        "protocol_id": protocol["id"],
        "consent_signer": "GUARDIAN",
        "assent_state": "NOT_REQUIRED",
        "is_assent_required": is_assent_required(referral, protocol),
        "guardian_consent_signed_at": None,
        "child_assent_signed_at": None,
        "status": "PENDING_CONSENT",
        "protocol_enrolled_count": int(protocol["enrolled_count"]),
        "active_family_count": 0,
    })
    if enrollment["is_assent_required"]:
        enrollment["assent_state"] = "PENDING"
    DB["enrollments"][enrollment["id"]] = enrollment
    referral["enrollment_id"] = enrollment["id"]

    touch(referral)
    return success_object(serialize_referral(referral), 200)


@bp.post("/programs/referrals/<referral_id>/withdraw")
def withdraw_referral(referral_id):
    require_role("IntakeCoordinator")
    referral = get_or_404("referrals", referral_id)
    protocol = get_or_404("protocols", referral["protocol_id"])
    body_json()

    status = referral["status"]
    if status == "SUBMITTED":
        referral["status"] = "WITHDRAWN"
        referral["applied_tier"] = "PENDING"
        touch(referral)
        return success_object(serialize_referral(referral), 200)

    if status == "ACCEPTED":
        referral["status"] = "WITHDRAWN"
        referral["decline_occurred_at"] = None
        released = release_referral_reservation(referral, protocol)
        touch(referral)
        if released:
            touch(protocol)
        return success_object(serialize_referral(referral), 200)

    if status == "ARRIVED":
        enrollment = DB["enrollments"].get(referral["enrollment_id"])
        if enrollment is not None and enrollment["status"] in (
                "ACTIVE_TREATMENT", "SURVIVORSHIP"):
            raise ApiError("ERR_ENROLLMENT_ACTIVE")
        if enrollment is not None:
            was_enrolled = enrollment["status"] == "ENROLLED"
            enrollment["status"] = "WITHDRAWN"
            touch(enrollment)
            if was_enrolled:
                # Only an enrollment that had reached ENROLLED is counted in
                # enrolled_count (SCAFFOLD Referral ARRIVED -> WITHDRAWN).
                protocol["enrolled_count"] = int(protocol["enrolled_count"]) - 1
        for assignment in DB["housing_assignments"].values():
            if enrollment is not None and assignment["enrollment_id"] == enrollment["id"]:
                if assignment["status"] in ("SCHEDULED", "ACTIVE"):
                    assignment["status"] = "CANCELLED"
                    touch(assignment)
        for pledge in DB["pledges"].values():
            if enrollment is not None and pledge["enrollment_id"] == enrollment["id"]:
                if pledge["status"] == "ACTIVE":
                    pledge["status"] = "VOIDED"
                    touch(pledge)
        if enrollment is not None and enrollment["status"] == "ENROLLED":
            # Only an enrollment that reached ENROLLED is counted in enrolled_count.
            protocol["enrolled_count"] = int(protocol["enrolled_count"]) - 1
        referral["status"] = "WITHDRAWN"
        released = release_referral_reservation(referral, protocol)
        touch(referral)
        if released:
            touch(protocol)
        return success_object(serialize_referral(referral), 200)

    raise ApiError("ERR_REFERRAL_NOT_SUBMITTED")


@bp.get("/programs/referrals/<referral_id>/enrollments")
def list_referral_enrollments(referral_id):
    require_role("Any")
    get_or_404("referrals", referral_id)
    rows = ordered([e for e in DB["enrollments"].values()
                    if e["referral_id"] == referral_id])
    return list_response(rows, serialize_enrollment)


@bp.get("/programs/referrals/<referral_id>/one-to-one-summary")
def one_to_one_summary(referral_id):
    require_role("Any")
    referral = get_or_404("referrals", referral_id)
    placed = set(referral.get("traveling_one_to_one_codes") or [])
    cleared = set(referral.get("one_to_one_care_capability_codes") or [])
    return success_object({
        "referral_id": referral["id"],
        "traveling_one_to_one_code_count": len(placed),
        "one_to_one_shortfall": bool(placed - cleared),
    }, 200)


@bp.get("/programs/referrals/<referral_id>/reopens")
def list_reopens(referral_id):
    require_role("Any")
    get_or_404("referrals", referral_id)
    rows = ordered([r for r in DB["referrals"].values()
                    if r.get("reopened_referral_id") == referral_id])
    return list_response(rows, serialize_referral)