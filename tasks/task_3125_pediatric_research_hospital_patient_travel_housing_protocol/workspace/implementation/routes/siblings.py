"""Sibling support services and the ops-run checkpoint (PRD §3.10)."""

from flask import Blueprint

from db import DB, new_row, touch
from errors import ApiError
from http_util import body_json, required, require_role
from response import success_object
from routes._common import arg, filtered, list_response, ordered
from services import (
    get_or_404, referral_for_enrollment, recompute_sibling_limit,
    serialize_ledger, serialize_sibling_service,
)

bp = Blueprint("siblings", __name__)


@bp.get("/programs/sibling-support-services")
def list_sibling_services():
    require_role("Any")
    enrollment_id = arg("enrollment_id")
    service_type = arg("service_type")
    status = arg("status")
    rows = ordered(DB["sibling_services"].values())
    rows = filtered(rows, enrollment_id=enrollment_id,
                    service_type=service_type, status=status)
    return list_response(rows, serialize_sibling_service)


@bp.get("/programs/sibling-support-services/<service_id>")
def get_sibling_service(service_id):
    require_role("Any")
    service = get_or_404("sibling_services", service_id)
    return success_object(serialize_sibling_service(service), 200)


@bp.post("/programs/sibling-support-services/<service_id>/sessions")
def deliver_sessions(service_id):
    require_role("PatientSupportOfficer")
    service = get_or_404("sibling_services", service_id)
    enrollment = get_or_404("enrollments", service["enrollment_id"])
    referral = referral_for_enrollment(enrollment)
    data = body_json()
    session_count = required(data, "session_count", "int")

    if service["status"] != "ACTIVE":
        raise ApiError("ERR_SIBLING_SERVICE_NOT_ACTIVE")
    state_code = (referral or {}).get("household_state_code")
    recompute_sibling_limit(service, state_code)
    if service["has_reached_monthly_limit"]:
        raise ApiError("ERR_SIBLING_SESSION_LIMIT_REACHED")
    if session_count < 0:
        raise ApiError("ERR_INVALID_REQUEST")

    service["sessions_delivered"] = int(service["sessions_delivered"]) + session_count
    recompute_sibling_limit(service, state_code)
    touch(service)
    return success_object(serialize_sibling_service(service), 200)


@bp.post("/programs/sibling-support-services/<service_id>/cancel")
def cancel_sibling_service(service_id):
    require_role("PatientSupportOfficer")
    service = get_or_404("sibling_services", service_id)
    body_json()
    if service["status"] != "ACTIVE":
        raise ApiError("ERR_SIBLING_SERVICE_NOT_ACTIVE")
    service["status"] = "CANCELLED"
    touch(service)
    return success_object(serialize_sibling_service(service), 200)


@bp.post("/_ops/run-checkpoint")
def run_checkpoint():
    require_role("PlatformAdmin")
    data = body_json()
    advance_to_epoch = required(data, "advance_to_epoch", "int")

    frozen = 0
    for ledger in DB["ledgers"].values():
        ledger["ledger_epoch"] = advance_to_epoch
        service = DB["services"].get(ledger["family_support_service_id"])
        if service is None:
            continue
        cap = int(service["stimulation_cap_cents"] or 0)
        if int(ledger["accumulated_cents"]) > cap and ledger["status"] == "ACTIVE":
            ledger["status"] = "FROZEN"
            frozen += 1
        touch(ledger)
    return success_object({
        "ledger_epoch": advance_to_epoch,
        "frozen_ledger_count": frozen,
    }, 200)