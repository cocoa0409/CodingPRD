"""Affiliate clinic and affiliation agreement endpoints (PRD §3.7)."""

from flask import Blueprint

from db import DB, new_row, touch
from errors import ApiError
from http_util import body_json, optional, required, require_role
from response import success_object
from routes._common import arg, filtered, list_response, ordered
from services import (
    get_or_404, get_optional, referral_for_enrollment, serialize_agreement,
    serialize_clinic, serialize_milestone,
)

bp = Blueprint("affiliates", __name__)


@bp.post("/programs/affiliate-clinics")
def create_clinic():
    require_role("AffiliateClinicCoordinator")
    data = body_json()
    clinic_code = required(data, "clinic_code", "str")
    name = required(data, "name", "str")
    state_code = required(data, "state_code", "str")
    is_active = optional(data, "is_active", True, "bool")
    if len(state_code) != 2:
        raise ApiError("ERR_INVALID_REQUEST")

    for existing in DB["clinics"].values():
        if existing["clinic_code"] == clinic_code:
            raise ApiError("ERR_DUPLICATE_ENTITY")

    clinic = new_row({
        "clinic_code": clinic_code,
        "name": name,
        "state_code": state_code,
        "is_active": is_active,
    })
    DB["clinics"][clinic["id"]] = clinic
    return success_object(serialize_clinic(clinic), 201)


@bp.get("/programs/affiliate-clinics")
def list_clinics():
    require_role("Any")
    state_code = arg("state_code")
    rows = ordered(DB["clinics"].values())
    rows = filtered(rows, state_code=state_code)
    return list_response(rows, serialize_clinic)


@bp.get("/programs/affiliate-clinics/<clinic_id>")
def get_clinic(clinic_id):
    require_role("Any")
    clinic = get_or_404("clinics", clinic_id)
    return success_object(serialize_clinic(clinic), 200)


@bp.post("/programs/affiliate-clinics/<clinic_id>/affiliations")
def create_affiliation(clinic_id):
    require_role("AffiliateClinicCoordinator")
    clinic = get_or_404("clinics", clinic_id)
    data = body_json()
    protocol_id = required(data, "protocol_id", "str")
    protocol = get_or_404("protocols", protocol_id)
    protocol_version = required(data, "protocol_version", "str")
    effective_start_at = required(data, "effective_start_at", "datetime")

    agreement = new_row({
        "clinic_id": clinic["id"],
        "protocol_id": protocol["id"],
        "protocol_version": protocol_version,
        "effective_start_at": effective_start_at,
        "is_cross_state": False,
        "status": "PENDING",
    })
    DB["affiliations"][agreement["id"]] = agreement
    # is_cross_state is true exactly when the affiliate's state_code differs from
    # the referring family's household_state_code (SCAFFOLD §1.1).
    referring_states = {
        r["household_state_code"] for r in DB["referrals"].values()
        if r.get("protocol_id") == protocol["id"] and r.get("household_state_code")
    }
    agreement["is_cross_state"] = any(
        state != clinic["state_code"] for state in referring_states)
    return success_object(serialize_agreement(agreement), 201)


@bp.get("/programs/affiliate-clinics/<clinic_id>/affiliations")
def list_clinic_affiliations(clinic_id):
    require_role("Any")
    get_or_404("clinics", clinic_id)
    status = arg("status")
    rows = ordered([a for a in DB["affiliations"].values()
                    if a["clinic_id"] == clinic_id])
    rows = filtered(rows, status=status)
    return list_response(rows, serialize_agreement)


@bp.get("/programs/affiliate-clinics/<clinic_id>/protocols")
def list_clinic_protocols(clinic_id):
    require_role("Any")
    get_or_404("clinics", clinic_id)
    status = arg("status")
    rows = ordered([a for a in DB["affiliations"].values()
                    if a["clinic_id"] == clinic_id])
    rows = filtered(rows, status=status)
    return list_response(rows, serialize_agreement)


@bp.get("/programs/affiliate-clinics/<clinic_id>/milestones")
def list_clinic_milestones(clinic_id):
    require_role("Any")
    get_or_404("clinics", clinic_id)
    status = arg("status")
    rows = ordered([m for m in DB["milestones"].values()
                    if m["affiliate_clinic_id"] == clinic_id])
    rows = filtered(rows, status=status)
    return list_response(rows, serialize_milestone)


@bp.get("/programs/affiliations")
def list_affiliations():
    require_role("Any")
    protocol_id = arg("protocol_id")
    clinic_id = arg("clinic_id")
    status = arg("status")
    rows = ordered(DB["affiliations"].values())
    rows = filtered(rows, protocol_id=protocol_id, clinic_id=clinic_id, status=status)
    return list_response(rows, serialize_agreement)


@bp.post("/programs/affiliations/<agreement_id>/activate")
def activate_affiliation(agreement_id):
    require_role("AffiliateClinicCoordinator")
    agreement = get_or_404("affiliations", agreement_id)
    clinic = get_or_404("clinics", agreement["clinic_id"])
    protocol = get_optional("protocols", agreement["protocol_id"])
    body_json()
    if agreement["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")
    if not clinic["is_active"]:
        raise ApiError("ERR_INVALID_REQUEST")
    if protocol is None:
        raise ApiError("ERR_PROTOCOL_NOT_FOUND")
    agreement["status"] = "ACTIVE"
    touch(agreement)
    return success_object(serialize_agreement(agreement), 200)


@bp.post("/programs/affiliations/<agreement_id>/suspend")
def suspend_affiliation(agreement_id):
    require_role("AffiliateClinicCoordinator")
    agreement = get_or_404("affiliations", agreement_id)
    body_json()
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    agreement["status"] = "SUSPENDED"
    touch(agreement)
    return success_object(serialize_agreement(agreement), 200)


@bp.post("/programs/affiliations/<agreement_id>/terminate")
def terminate_affiliation(agreement_id):
    require_role("AffiliateClinicCoordinator")
    agreement = get_or_404("affiliations", agreement_id)
    body_json()
    if agreement["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE")
    agreement["status"] = "TERMINATED"
    touch(agreement)
    return success_object(serialize_agreement(agreement), 200)