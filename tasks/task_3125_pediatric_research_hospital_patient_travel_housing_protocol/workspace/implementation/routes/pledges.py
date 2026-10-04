"""Family-support pledge endpoints and the settlement mathematics (PRD §3.5)."""

from flask import Blueprint

from db import DB, new_row, touch
from errors import ApiError
from http_util import body_json, required, require_role
from response import success_object
from routes._common import arg, filtered, list_response, ordered
from services import (
    current_pledge, get_or_404, protocol_for_enrollment, recompute_pledge_derived,
    recompute_protocol_committed, referral_for_enrollment, release_referral_reservation,
    serialize_pledge, settle_pledge,
)

bp = Blueprint("pledges", __name__)

STARTER_PER_FAMILY_DAY_CENTS = 450


def _covered_days_from_housing(enrollment):
    """The housing nights the enrollment has already accrued. A night is billed once
    its charge exists, so only occupancies that actually ran count (SCAFFOLD
    HousingAssignment: chargeable_nights x nightly_rate; a SCHEDULED booking that is
    later cancelled books nothing)."""
    nights = 0
    for assignment in DB["housing_assignments"].values():
        if assignment["enrollment_id"] != enrollment["id"]:
            continue
        if assignment["status"] in ("ACTIVE", "VACATED"):
            nights += int(assignment["billed_nights"])
    return nights


@bp.post("/programs/family-support-pledges")
def create_pledge():
    require_role("PatientSupportOfficer")
    data = body_json()
    enrollment_id = required(data, "enrollment_id", "str")
    enrollment = get_or_404("enrollments", enrollment_id)
    budget = required(data, "patient_support_budget_cents", "int")
    if budget < 0:
        raise ApiError("ERR_INVALID_REQUEST")

    # covered_days is initialized from the housing nights already accrued.
    nights = _covered_days_from_housing(enrollment)

    pledge = new_row({
        "enrollment_id": enrollment["id"],
        "patient_support_budget_cents": budget,
        "covered_days": nights,
        "provisional_settled_cents": nights * STARTER_PER_FAMILY_DAY_CENTS,
        "final_settled_cents": 0,
        "billing_permitted_cents": 0,
        "status": "ACTIVE",
    })
    DB["pledges"][pledge["id"]] = pledge
    return success_object(serialize_pledge(pledge), 201)


@bp.get("/programs/family-support-pledges")
def list_pledges():
    require_role("Any")
    enrollment_id = arg("enrollment_id")
    status = arg("status")
    rows = ordered(DB["pledges"].values())
    rows = filtered(rows, enrollment_id=enrollment_id, status=status)
    return list_response(rows, serialize_pledge)


@bp.get("/programs/family-support-pledges/<pledge_id>")
def get_pledge(pledge_id):
    require_role("Any")
    pledge = get_or_404("pledges", pledge_id)
    return success_object(serialize_pledge(pledge), 200)


@bp.post("/programs/family-support-pledges/<pledge_id>/accrue")
def accrue_pledge(pledge_id):
    require_role("PatientSupportOfficer")
    pledge = get_or_404("pledges", pledge_id)
    enrollment = get_or_404("enrollments", pledge["enrollment_id"])
    referral = referral_for_enrollment(enrollment)
    protocol = protocol_for_enrollment(enrollment)
    data = body_json()
    days = required(data, "days", "int")

    if days < 1:
        raise ApiError("ERR_INVALID_REQUEST")
    if pledge["status"] != "ACTIVE":
        raise ApiError("ERR_PLEDGE_SETTLE_NOT_ACTIVE")

    new_days = int(pledge["covered_days"]) + days
    charge = new_days * STARTER_PER_FAMILY_DAY_CENTS
    coverage = int((referral or {}).get("insurance_coverage_cents", 0))
    if charge > int(pledge["patient_support_budget_cents"]) + coverage:
        raise ApiError("ERR_SUPPORT_BUDGET_EXCEEDED")

    pledge["covered_days"] = new_days
    pledge["provisional_settled_cents"] = charge
    if protocol is not None:
        recompute_protocol_committed(protocol)
    touch(pledge)
    return success_object(serialize_pledge(pledge), 200)


@bp.post("/programs/family-support-pledges/<pledge_id>/settle")
def settle(pledge_id):
    require_role("PatientSupportOfficer")
    pledge = get_or_404("pledges", pledge_id)
    enrollment = get_or_404("enrollments", pledge["enrollment_id"])
    body_json()

    if pledge["status"] != "ACTIVE":
        raise ApiError("ERR_PLEDGE_SETTLE_NOT_ACTIVE")
    if enrollment["status"] not in ("WITHDRAWN", "COMPLETED", "ON_HIATUS", "SURVIVORSHIP"):
        raise ApiError("ERR_PLEDGE_SETTLE_ENROLLMENT_ACTIVE")

    settle_pledge(pledge)
    return success_object(serialize_pledge(pledge), 200)


@bp.post("/programs/family-support-pledges/<pledge_id>/void")
def void_pledge(pledge_id):
    require_role("PatientSupportOfficer")
    pledge = get_or_404("pledges", pledge_id)
    enrollment = get_or_404("enrollments", pledge["enrollment_id"])
    protocol = protocol_for_enrollment(enrollment)
    body_json()

    if pledge["status"] != "ACTIVE":
        raise ApiError("ERR_PLEDGE_SETTLE_NOT_ACTIVE")
    for assignment in DB["housing_assignments"].values():
        if (assignment["enrollment_id"] == enrollment["id"]
                and assignment["status"] == "ACTIVE"):
            raise ApiError("ERR_HOUSING_OCCUPANCY_ACTIVE")

    pledge["status"] = "VOIDED"
    touch(pledge)
    if protocol is not None:
        recompute_protocol_committed(protocol)
        touch(protocol)
    return success_object(serialize_pledge(pledge), 200)