"""Enrollment endpoints: consent, assent, treatment lifecycle, survivorship
(PRD §3.3, §3.8)."""

from flask import Blueprint

from db import DB, new_row, now_iso, touch
from errors import ApiError
from http_util import body_json, optional, required, require_role
from response import success_object
from routes._common import arg, filtered, list_response, ordered
from services import (
    current_pledge, derive_referral_computed, get_or_404,
    promote_next_milestone, protocol_for_enrollment, protocol_is_frozen,
    referral_for_enrollment, recompute_protocol_derived, refresh_enrollment_mirrors,
    serialize_enrollment, serialize_milestone, serialize_pledge,
    serialize_sibling_service, serialize_survivorship_enrollment, serialize_travel,
    settle_pledge, sweep_missed_milestones, travel_accumulation, touch_only,
)

bp = Blueprint("enrollments", __name__)

NON_OPERATIONAL_STATES = {"ENROLLED", "ACTIVE_TREATMENT", "SURVIVORSHIP"}


@bp.get("/programs/enrollments")
def list_enrollments():
    require_role("Any")
    referral_id = arg("referral_id")
    protocol_id = arg("protocol_id")
    enrollment_status = arg("enrollment_status")
    if enrollment_status is None:
        rows = [e for e in DB["enrollments"].values()
                if e["status"] != "WITHDRAWN"]
    else:
        rows = [e for e in DB["enrollments"].values()
                if e["status"] == enrollment_status]
    rows = ordered(rows)
    rows = filtered(rows, referral_id=referral_id, protocol_id=protocol_id)
    return list_response(rows, serialize_enrollment)


@bp.get("/programs/enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    require_role("Any")
    enrollment = get_or_404("enrollments", enrollment_id)
    return success_object(serialize_enrollment(enrollment), 200)


@bp.post("/programs/enrollments/<enrollment_id>/sign-consent")
def sign_consent(enrollment_id):
    require_role("IntakeCoordinator")
    enrollment = get_or_404("enrollments", enrollment_id)
    protocol = protocol_for_enrollment(enrollment)
    referral = referral_for_enrollment(enrollment)
    data = body_json()
    consent_signer = required(data, "consent_signer", "str")
    guardian_code = required(data, "guardian_consent_signature_code", "str")
    child_code = optional(data, "child_assent_signature_code", None, "str")

    if enrollment["status"] != "PENDING_CONSENT":
        raise ApiError("ERR_ENROLLMENT_NOT_PENDING_CONSENT")
    if consent_signer not in ("GUARDIAN", "GUARDIAN_AND_CHILD"):
        raise ApiError("ERR_INVALID_REQUEST")

    # The signer the child's age demands (PRD §3.3).
    required_signer = "GUARDIAN_AND_CHILD" if enrollment["is_assent_required"] else "GUARDIAN"
    if consent_signer != required_signer:
        raise ApiError("ERR_INVALID_CONSENT_SIGNER")

    # PRD §3.3: signing is the operation that *collects* assent — `assent_state`
    # is moved to OBTAINED by this very call. The ERR_ASSENT_NOT_OBTAINED gate
    # belongs to enrollment completion, not to the signing operation, so it is
    # never applied here.

    if protocol is None or not (protocol["status"] == "OPEN"
                                and not protocol_is_frozen(protocol)):
        if protocol is not None and protocol["is_protocol_held"]:
            raise ApiError("ERR_ARM_ASSENT_BLOCKED_BY_HOLD")
        raise ApiError("ERR_ARM_ASSENT_BLOCKED_BY_HOLD")

    if referral is not None:
        # PRD §3.3: "Every traveler holding a `GUARDIAN`-type coverage placed by
        # this referral must appear in the referral's
        # `one_to_one_care_capability_codes`". The gate is about a placed
        # coverage whose holder was not cleared, so it compares the placed
        # GUARDIAN codes against the cleared list.
        placed = set(referral.get("traveling_one_to_one_codes") or [])
        cleared = set(referral.get("one_to_one_care_capability_codes") or [])
        if placed - cleared:
            raise ApiError("ERR_ONE_TO_ONE_CARE_NOT_ELIGIBLE")

    if not int(protocol["enrolled_count"]) < int(protocol["capacity"]):
        raise ApiError("ERR_PROTOCOL_CAPACITY_EXCEEDED")

    if child_code is not None:
        enrollment["assent_state"] = "OBTAINED"
        enrollment["child_assent_signed_at"] = now_iso()

    if enrollment["assent_state"] == "PENDING":
        # The child's own assent is required but no signature was supplied, so
        # the packet is incomplete: PRD §3.3's assent gate fires and the
        # enrollment cannot complete.
        raise ApiError("ERR_ASSENT_NOT_OBTAINED")

    enrollment["guardian_consent_signed_at"] = now_iso()
    enrollment["status"] = "ENROLLED"
    protocol["enrolled_count"] = int(protocol["enrolled_count"]) + 1

    if referral is not None:
        basis = int(referral.get("reservation_basis_cents") or 0)
        if basis:
            protocol["reserved_cents"] = int(protocol["reserved_cents"]) - basis
            referral["reservation_basis_cents"] = 0
            touch(referral)
    recompute_protocol_derived(protocol)
    touch(protocol)
    touch(enrollment)
    refresh_enrollment_mirrors(enrollment)
    return success_object(serialize_enrollment(enrollment), 200)


@bp.post("/programs/enrollments/<enrollment_id>/record-arm-assent")
def record_arm_assent(enrollment_id):
    require_role("IRBReviewer")
    enrollment = get_or_404("enrollments", enrollment_id)
    protocol = protocol_for_enrollment(enrollment)
    data = body_json()
    required(data, "child_assent_signature_code", "str")

    if enrollment["status"] != "PENDING_CONSENT":
        raise ApiError("ERR_ENROLLMENT_NOT_PENDING_CONSENT")
    if protocol is None or not (protocol["status"] == "OPEN"
                                and not protocol_is_frozen(protocol)):
        raise ApiError("ERR_ARM_ASSENT_BLOCKED_BY_HOLD")

    enrollment["assent_state"] = "OBTAINED"
    enrollment["child_assent_signed_at"] = now_iso()
    touch(enrollment)
    return success_object(serialize_enrollment(enrollment), 200)


@bp.post("/programs/enrollments/<enrollment_id>/start-treatment")
def start_treatment(enrollment_id):
    require_role("IntakeCoordinator")
    enrollment = get_or_404("enrollments", enrollment_id)
    if enrollment["status"] != "ENROLLED":
        raise ApiError("ERR_ENROLLMENT_NOT_ENROLLED")
    has_active = any(
        a["enrollment_id"] == enrollment["id"] and a["status"] == "ACTIVE"
        for a in DB["housing_assignments"].values())
    if not has_active:
        raise ApiError("ERR_NO_ACTIVE_HOUSING")

    enrollment["status"] = "ACTIVE_TREATMENT"
    promote_next_milestone(enrollment)
    touch(enrollment)
    return success_object(serialize_enrollment(enrollment), 200)


@bp.post("/programs/enrollments/<enrollment_id>/hiatus")
def hiatus(enrollment_id):
    require_role("IntakeCoordinator")
    enrollment = get_or_404("enrollments", enrollment_id)
    protocol = protocol_for_enrollment(enrollment)
    referral = referral_for_enrollment(enrollment)
    body_json()

    if enrollment["status"] == "PENDING_CONSENT":
        enrollment["status"] = "ON_HIATUS"
        lock = current_pledge(enrollment)
        if lock is not None:
            settle_pledge(lock)
        touch(enrollment)
        return success_object(serialize_enrollment(enrollment), 200)

    if enrollment["status"] != "ACTIVE_TREATMENT":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE_TREATMENT")

    sweep_missed_milestones(enrollment)
    outstanding = [m for m in DB["milestones"].values()
                   if m["enrollment_id"] == enrollment["id"]
                   and m["status"] in ("PENDING", "DUE")]
    if outstanding:
        raise ApiError("ERR_MILESTONES_OUTSTANDING")

    enrollment["status"] = "ON_HIATUS"
    for assignment in DB["housing_assignments"].values():
        if assignment["enrollment_id"] == enrollment["id"] and assignment["status"] == "ACTIVE":
            assignment["status"] = "VACATED"
            assignment["vacated_reason"] = "TRANSFERRED_AFFILIATE"
            assignment["is_active_occupancy"] = False
            touch(assignment)
            facility = DB["housing_facilities"].get(assignment["housing_facility_id"])
            if facility is not None:
                from services import recompute_facility_beds
                recompute_facility_beds(facility)
    lock = current_pledge(enrollment)
    if lock is not None:
        settle_pledge(lock)
    touch(enrollment)
    return success_object(serialize_enrollment(enrollment), 200)


@bp.post("/programs/enrollments/<enrollment_id>/resume")
def resume(enrollment_id):
    require_role("IntakeCoordinator")
    enrollment = get_or_404("enrollments", enrollment_id)
    protocol = protocol_for_enrollment(enrollment)
    if enrollment["status"] != "ON_HIATUS":
        raise ApiError("ERR_ENROLLMENT_NOT_ON_HIATUS")
    if protocol is None or not (protocol["status"] == "OPEN"
                                and not protocol_is_frozen(protocol)):
        raise ApiError("ERR_ARM_ASSENT_BLOCKED_BY_HOLD")

    enrollment["status"] = "ACTIVE_TREATMENT"
    pledge = new_row({
        "enrollment_id": enrollment["id"],
        "patient_support_budget_cents": 0,
        "covered_days": 0,
        "provisional_settled_cents": 0,
        "final_settled_cents": 0,
        "billing_permitted_cents": 0,
        "status": "ACTIVE",
    })
    previous = [p for p in DB["pledges"].values()
                if p["enrollment_id"] == enrollment["id"]]
    previous.sort(key=lambda p: p["created_at"])
    if previous:
        pledge["patient_support_budget_cents"] = previous[-1]["patient_support_budget_cents"]
    DB["pledges"][pledge["id"]] = pledge
    touch(enrollment)
    return success_object(serialize_enrollment(enrollment), 200)


@bp.post("/programs/enrollments/<enrollment_id>/complete-treatment")
def complete_treatment(enrollment_id):
    require_role("IntakeCoordinator")
    enrollment = get_or_404("enrollments", enrollment_id)
    protocol = protocol_for_enrollment(enrollment)
    referral = referral_for_enrollment(enrollment)
    body_json()

    if enrollment["status"] != "ACTIVE_TREATMENT":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE_TREATMENT")
    outstanding = [m for m in DB["milestones"].values()
                   if m["enrollment_id"] == enrollment["id"]
                   and m["status"] in ("DUE", "MISSED")]
    if outstanding:
        raise ApiError("ERR_MILESTONES_OUTSTANDING")
    study = None
    for candidate in DB["studies"].values():
        if candidate["protocol_id"] == protocol["id"] and candidate["status"] == "ACTIVE":
            study = candidate
            break
    if study is None:
        raise ApiError("ERR_NO_ACTIVE_SURVIVORSHIP_STUDY")

    enrollment["status"] = "SURVIVORSHIP"
    protocol["enrolled_count"] = int(protocol["enrolled_count"]) - 1
    recompute_protocol_derived(protocol)
    touch(protocol)

    survivorship = new_row({
        "study_id": study["id"],
        "enrollment_id": enrollment["id"],
        "completed_treatment_at": now_iso(),
        "adult_transition_age_years": 18,
        "next_due_at": now_iso(),
        "is_adult_follow_up": False,
        "status": "ON_STUDY",
    })
    DB["survivorship_enrollments"][survivorship["id"]] = survivorship

    for service in DB["sibling_services"].values():
        if service["enrollment_id"] == enrollment["id"] and service["status"] == "ACTIVE":
            service["status"] = "COMPLETED"
            touch(service)

    lock = current_pledge(enrollment)
    if lock is not None:
        settle_pledge(lock)
    touch(enrollment)
    return success_object(serialize_enrollment(enrollment), 200)


@bp.post("/programs/enrollments/<enrollment_id>/complete-follow-up")
def complete_follow_up(enrollment_id):
    require_role("IntakeCoordinator")
    enrollment = get_or_404("enrollments", enrollment_id)
    body_json()
    if enrollment["status"] != "SURVIVORSHIP":
        raise ApiError("ERR_ENROLLMENT_NOT_IN_SURVIVORSHIP")
    rows = [s for s in DB["survivorship_enrollments"].values()
            if s["enrollment_id"] == enrollment["id"]]
    for row in rows:
        if row["status"] != "GRADUATED":
            raise ApiError("ERR_SURVIVORSHIP_NOT_GRADUATED")
    enrollment["status"] = "COMPLETED"
    touch(enrollment)
    return success_object(serialize_enrollment(enrollment), 200)


# --- sub-collections ---------------------------------------------------------

@bp.get("/programs/enrollments/<enrollment_id>/pledges")
def list_pledges(enrollment_id):
    require_role("Any")
    get_or_404("enrollments", enrollment_id)
    status = arg("status")
    rows = ordered([p for p in DB["pledges"].values()
                    if p["enrollment_id"] == enrollment_id])
    rows = filtered(rows, status=status)
    return list_response(rows, serialize_pledge)


@bp.get("/programs/enrollments/<enrollment_id>/housing-assignments")
def list_enrollment_assignments(enrollment_id):
    require_role("Any")
    get_or_404("enrollments", enrollment_id)
    from services import serialize_assignment
    status = arg("status")
    rows = ordered([a for a in DB["housing_assignments"].values()
                    if a["enrollment_id"] == enrollment_id])
    rows = filtered(rows, status=status)
    return list_response(rows, serialize_assignment)


@bp.get("/programs/enrollments/<enrollment_id>/travel-arrangements")
def list_enrollment_travel(enrollment_id):
    require_role("Any")
    get_or_404("enrollments", enrollment_id)
    status = arg("status")
    mode = arg("mode")
    rows = ordered([t for t in DB["travel_arrangements"].values()
                    if t["enrollment_id"] == enrollment_id])
    rows = filtered(rows, status=status, mode=mode)
    return list_response(rows, serialize_travel)


@bp.get("/programs/enrollments/<enrollment_id>/travel-summary")
def travel_summary(enrollment_id):
    require_role("Any")
    enrollment = get_or_404("enrollments", enrollment_id)
    count, total = travel_accumulation(enrollment)
    return success_object({
        "enrollment_id": enrollment["id"],
        "chargeable_leg_count": count,
        "accumulated_family_day_charge_cents": total,
    }, 200)


@bp.get("/programs/enrollments/<enrollment_id>/milestones")
def list_enrollment_milestones(enrollment_id):
    require_role("Any")
    get_or_404("enrollments", enrollment_id)
    status = arg("status")
    rows = ordered([m for m in DB["milestones"].values()
                    if m["enrollment_id"] == enrollment_id])
    rows = filtered(rows, status=status)
    return list_response(rows, serialize_milestone)


@bp.get("/programs/enrollments/<enrollment_id>/survivorship-enrollments")
def list_enrollment_survivorship(enrollment_id):
    require_role("Any")
    get_or_404("enrollments", enrollment_id)
    status = arg("status")
    rows = ordered([s for s in DB["survivorship_enrollments"].values()
                    if s["enrollment_id"] == enrollment_id])
    rows = filtered(rows, status=status)
    return list_response(rows, serialize_survivorship_enrollment)


@bp.get("/programs/enrollments/<enrollment_id>/sibling-services")
def list_enrollment_siblings(enrollment_id):
    require_role("Any")
    get_or_404("enrollments", enrollment_id)
    service_type = arg("service_type")
    status = arg("status")
    rows = ordered([s for s in DB["sibling_services"].values()
                    if s["enrollment_id"] == enrollment_id])
    rows = filtered(rows, service_type=service_type, status=status)
    return list_response(rows, serialize_sibling_service)


@bp.post("/programs/enrollments/<enrollment_id>/sibling-services")
def create_sibling_service(enrollment_id):
    require_role("PatientSupportOfficer")
    enrollment = get_or_404("enrollments", enrollment_id)
    referral = referral_for_enrollment(enrollment)
    data = body_json()
    sibling_alias = required(data, "sibling_alias", "str")
    service_type = required(data, "service_type", "str")
    if service_type not in ("TUITION_STIPEND", "COUNSELING_SESSION",
                            "RECREATION_PROGRAM", "SIBLING_CAMP"):
        raise ApiError("ERR_INVALID_REQUEST")
    start_at = required(data, "delivery_window_start_at", "datetime")
    end_at = required(data, "delivery_window_end_at", "datetime")
    if not (start_at < end_at):
        raise ApiError("ERR_INVALID_REQUEST")

    for existing in DB["sibling_services"].values():
        if (existing["enrollment_id"] == enrollment["id"]
                and existing["sibling_alias"] == sibling_alias):
            raise ApiError("ERR_DUPLICATE_ENTITY")

    service = new_row({
        "enrollment_id": enrollment["id"],
        "sibling_alias": sibling_alias,
        "service_type": service_type,
        "delivery_window_start_at": start_at,
        "delivery_window_end_at": end_at,
        "sessions_delivered": 0,
        "has_reached_monthly_limit": False,
        "status": "ACTIVE",
    })
    from services import recompute_sibling_limit
    recompute_sibling_limit(service, (referral or {}).get("household_state_code"))
    DB["sibling_services"][service["id"]] = service
    return success_object(serialize_sibling_service(service), 201)


@bp.post("/programs/enrollments/<enrollment_id>/milestones")
def create_milestone(enrollment_id):
    require_role("ProtocolCoordinator")
    enrollment = get_or_404("enrollments", enrollment_id)
    data = body_json()
    sequence = required(data, "milestone_sequence", "int")
    if sequence < 1:
        raise ApiError("ERR_INVALID_REQUEST")
    description = required(data, "description", "str")
    requires_main_campus = required(data, "requires_main_campus", "bool")
    target_at = required(data, "target_at", "datetime")

    for existing in DB["milestones"].values():
        if (existing["enrollment_id"] == enrollment["id"]
                and existing["milestone_sequence"] == sequence):
            raise ApiError("ERR_DUPLICATE_ENTITY")

    milestone = new_row({
        "enrollment_id": enrollment["id"],
        "milestone_sequence": sequence,
        "description": description,
        "requires_main_campus": requires_main_campus,
        "target_at": target_at,
        "executed_at": None,
        "deferred_from_milestone_id": None,
        "affiliate_clinic_id": None,
        "status": "PENDING",
    })
    DB["milestones"][milestone["id"]] = milestone
    return success_object(serialize_milestone(milestone), 201)


@bp.post("/programs/enrollments/<enrollment_id>/travel-arrangements")
def create_travel(enrollment_id):
    require_role("PatientSupportOfficer")
    enrollment = get_or_404("enrollments", enrollment_id)
    referral = referral_for_enrollment(enrollment)
    data = body_json()
    mode = required(data, "mode", "str")
    if mode not in ("AIR_ECONOMY", "AIR_MEDICAL", "GROUND", "RAIL"):
        raise ApiError("ERR_INVALID_REQUEST")
    traveler_count = required(data, "traveler_count", "int")
    if not (2 <= traveler_count <= 6):
        raise ApiError("ERR_TRAVELER_COUNT_RANGE")
    departure_at = required(data, "departure_at", "datetime")
    return_at = optional(data, "return_at", None, "datetime")
    trip_reason = required(data, "trip_reason", "str")
    if trip_reason not in ("PROTOCOL_REVIEW", "THERAPY_ADMINISTRATION",
                           "SURVIVORSHIP_VISIT", "FAMILY_REQUEST"):
        raise ApiError("ERR_INVALID_REQUEST")
    is_required = optional(data, "is_required_travel", None, "bool")
    placements = optional(data, "placed_coverages", [], "list")

    cleaned = []
    for placement in placements:
        if not isinstance(placement, dict):
            raise ApiError("ERR_INVALID_REQUEST")
        for field in ("plan_code", "travel_window_start_at",
                      "travel_window_end_at", "coverage_cents"):
            if field not in placement or placement[field] is None:
                raise ApiError("ERR_INVALID_REQUEST")
        if not isinstance(placement["plan_code"], str):
            raise ApiError("ERR_INVALID_REQUEST")
        if not isinstance(placement["coverage_cents"], int):
            raise ApiError("ERR_INVALID_REQUEST")
        for field in ("travel_window_start_at", "travel_window_end_at"):
            if not isinstance(placement[field], str):
                raise ApiError("ERR_INVALID_REQUEST")
            from db import parse_iso
            try:
                parse_iso(placement[field])
            except ValueError:
                raise ApiError("ERR_INVALID_REQUEST")
        cleaned.append(dict(placement))

    if return_at is not None and not (departure_at < return_at):
        raise ApiError("ERR_INVALID_REQUEST")

    from services import REQUIRED_TRAVEL_REASONS
    if is_required is None:
        is_required = trip_reason in REQUIRED_TRAVEL_REASONS

    leg = new_row({
        "enrollment_id": enrollment["id"],
        "mode": mode,
        "traveler_count": traveler_count,
        "departure_at": departure_at,
        "return_at": return_at,
        "is_required_travel": is_required,
        "trip_reason": trip_reason,
        "placed_coverages": cleaned,
        "family_day_units": 0,
        "transport_cost_cents": 0,
        "fund_patient_support_balance_cents": 0,
        "fund_research_balance_cents": 0,
        "eligibility_confirmed_at": None,
        "status": "REQUESTED",
    })
    DB["travel_arrangements"][leg["id"]] = leg

    # PRD §3.2: "`traveling_one_to_one_codes` is derived on the referral as the
    # set of `coverage_type` codes of the `GUARDIAN`-type coverages the referral
    # actually places". The coverage placements ride on the travel leg, so a leg
    # that places a coverage registers it on the referral as well; the read then
    # re-derives `traveling_one_to_one_codes` from the referral's own placements.
    if referral is not None and cleaned:
        placed = list(referral.get("placed_coverages") or [])
        placed.extend(cleaned)
        referral["placed_coverages"] = placed
        # Re-derive the referral's coverage-derived fields so the newly placed
        # GUARDIAN codes are visible to the one-to-one care gate.
        protocol_for_referral = protocol_for_enrollment(enrollment)
        if protocol_for_referral is not None:
            derive_referral_computed(referral, protocol_for_referral, with_fee=False)
        touch(referral)

    return success_object(serialize_travel(leg), 201)