"""Enrollment endpoints."""
from flask import Blueprint, request

import db
from errors import (
    err_cross_market_reference,
    err_driver_ineligible,
    err_enrollment_duplicate,
    err_fraud_restricted,
    err_invalid_request,
    err_invalid_state,
    err_program_window_conflict,
)
from middleware import require_roles
from response import success_object
from services import (
    enrollment_view,
    get_driver_or_404,
    get_enrollment_or_404,
    get_program_or_404,
    new_entity,
    touch,
    touch_expiry,
)

bp = Blueprint("enrollments", __name__)


@bp.post("/incentive-programs/<pid>/enrollments")
@require_roles("IncentiveOps")
def create_enrollment(pid, _user_id, _role):
    p = get_program_or_404(pid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    driver_id = body.get("driver_id")
    if not isinstance(driver_id, str):
        raise err_invalid_request("driver_id is required")
    driver = get_driver_or_404(driver_id)

    # state gate: program must be ACTIVE to enroll
    if p["status"] != "ACTIVE":
        raise err_invalid_state("Program is not ACTIVE")

    # priority 4: fraud gate
    if driver["fraud_posture"] == "RESTRICTED":
        raise err_fraud_restricted()

    # priority 5: temporal / capacity
    if p["program_type"] == "BONUS_ZONE" and p.get("capacity") is not None:
        active_count = sum(
            1
            for e in db.enrollments.values()
            if e["program_id"] == p["id"] and e["status"] == "ACTIVE"
        )
        if active_count >= p["capacity"]:
            raise err_program_window_conflict("BONUS_ZONE capacity exceeded")

    # priority 6: referential coherence
    if driver["market_id"] != p["market_id"]:
        raise err_cross_market_reference("Driver home market differs from program market")

    # priority 7: eligibility gate
    if driver["rate_posture"] == "INELIGIBLE":
        raise err_driver_ineligible()

    # duplicate check
    for e in db.enrollments.values():
        if e["driver_id"] == driver["id"] and e["program_id"] == p["id"] and e["status"] == "ACTIVE":
            raise err_enrollment_duplicate()

    enr = new_entity(
        {
            "driver_id": driver["id"],
            "program_id": p["id"],
            "status": "ACTIVE",
            "progress_count": 0,
            "streak_broken": False,
            "payout_cents": 0,
            "earned_qualifying_cents": 0,
        }
    )
    db.enrollments[enr["id"]] = enr
    return success_object(enrollment_view(enr), 201)


@bp.get("/enrollments/<eid>")
@require_roles("PlatformAdmin", "IncentiveOps", "PaymentsOfficer", "Driver")
def get_enrollment(eid, _user_id, _role):
    e = get_enrollment_or_404(eid)
    touch_expiry("enrollment", e)
    return success_object(enrollment_view(e))


@bp.post("/enrollments/<eid>/cancel")
@require_roles("IncentiveOps", "Driver")
def cancel_enrollment_endpoint(eid, _user_id, _role):
    e = get_enrollment_or_404(eid)
    touch_expiry("enrollment", e)
    if e["status"] != "ACTIVE":
        raise err_invalid_state("Enrollment is not ACTIVE")
    from services import cancel_enrollment

    cancel_enrollment(e)
    return success_object(enrollment_view(e))
