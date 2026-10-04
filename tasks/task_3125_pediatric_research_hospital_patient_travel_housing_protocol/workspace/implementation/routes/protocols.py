"""Clinical protocol endpoints (PRD §2.5, §3.1)."""

from flask import Blueprint

from db import DB, new_row, touch
from errors import ApiError
from http_util import body_json, optional, required, require_role
from response import success_object
from routes._common import arg, filtered, list_response, ordered
from services import (
    MAX_PROTOCOL_BUDGET_RATE, commitment_share_ceiling, derive_age_tier,
    get_or_404, recompute_protocol_derived, serialize_hold, serialize_protocol,
    serialize_study,
)

bp = Blueprint("protocols", __name__)

VALID_STAGES = {"NEWLY_DIAGNOSED", "RELAPSED", "REFRACTORY", "REMISSION"}


@bp.post("/programs/clinical-protocols")
def create_protocol():
    require_role("ProtocolCoordinator")
    data = body_json()
    fund_id = required(data, "fund_id", "str")
    fund = get_or_404("funds", fund_id)
    protocol_code = required(data, "protocol_code", "str")
    disease_group = required(data, "disease_group", "str")
    age_min = required(data, "age_min_years", "int")
    age_max = required(data, "age_max_years", "int")
    required_stage = required(data, "required_stage", "str")
    if required_stage not in VALID_STAGES:
        raise ApiError("ERR_INVALID_REQUEST")
    budget = required(data, "protocol_budget_cents", "int")
    capacity = required(data, "capacity", "int")

    for existing in DB["protocols"].values():
        if existing["protocol_code"] == protocol_code:
            raise ApiError("ERR_DUPLICATE_ENTITY")

    ceiling = commitment_share_ceiling(fund, including_new=1)
    if budget > ceiling:
        raise ApiError("ERR_PROTOCOL_BUDGET_EXCEEDS_COMMITMENT_SHARE")

    protocol = new_row({
        "fund_id": fund_id,
        "protocol_code": protocol_code,
        "disease_group": disease_group,
        "age_min_years": age_min,
        "age_max_years": age_max,
        "required_stage": required_stage,
        "protocol_budget_cents": budget,
        "reserved_cents": 0,
        "committed_cents": 0,
        "available_cents": budget,
        "capacity": capacity,
        "enrolled_count": 0,
        "age_tier": derive_age_tier(age_min, age_max),
        "mental_capacity_floor": max(age_min, 7),
        "is_protocol_held": False,
        "is_budget_saturated": False,
        "status": "DRAFT",
    })
    recompute_protocol_derived(protocol)
    DB["protocols"][protocol["id"]] = protocol
    return success_object(serialize_protocol(protocol), 201)


@bp.get("/programs/clinical-protocols")
def list_protocols():
    require_role("Any")
    fund_id = arg("fund_id")
    rows = ordered(DB["protocols"].values())
    rows = filtered(rows, fund_id=fund_id)
    return list_response(rows, serialize_protocol)


@bp.get("/programs/clinical-protocols/<protocol_id>")
def get_protocol(protocol_id):
    require_role("Any")
    protocol = get_or_404("protocols", protocol_id)
    return success_object(serialize_protocol(protocol), 200)


@bp.post("/programs/clinical-protocols/<protocol_id>/open")
def open_protocol(protocol_id):
    require_role("ProtocolCoordinator")
    protocol = get_or_404("protocols", protocol_id)
    if protocol["status"] != "DRAFT":
        raise ApiError("ERR_PROTOCOL_NOT_IN_DRAFT")
    if int(protocol["capacity"]) <= 0:
        raise ApiError("ERR_INVALID_REQUEST")
    if int(protocol["protocol_budget_cents"]) <= 0:
        raise ApiError("ERR_INVALID_REQUEST")
    protocol["status"] = "OPEN"
    recompute_protocol_derived(protocol)
    touch(protocol)
    return success_object(serialize_protocol(protocol), 200)


@bp.post("/programs/clinical-protocols/<protocol_id>/close")
def close_protocol(protocol_id):
    require_role("ProtocolCoordinator")
    protocol = get_or_404("protocols", protocol_id)
    body_json()  # a malformed body is ERR_INVALID_REQUEST
    if protocol["status"] != "OPEN":
        raise ApiError("ERR_PROTOCOL_NOT_OPEN")
    if int(protocol["enrolled_count"]) != 0:
        raise ApiError("ERR_PROTOCOL_HAS_ENROLLED_PATIENTS")
    protocol["status"] = "CLOSED"
    for study in DB["studies"].values():
        if study["protocol_id"] == protocol["id"] and study["status"] == "ACTIVE":
            study["status"] = "CLOSED"
            touch(study)
    for pledge in DB["pledges"].values():
        enrollment = DB["enrollments"].get(pledge["enrollment_id"])
        if enrollment is None or enrollment["protocol_id"] != protocol["id"]:
            continue
        if enrollment["status"] != "WITHDRAWN":
            continue
        if pledge["status"] == "ACTIVE":
            pledge["status"] = "VOIDED"
            touch(pledge)
    touch(protocol)
    return success_object(serialize_protocol(protocol), 200)


@bp.post("/programs/clinical-protocols/<protocol_id>/release-hold")
def release_hold(protocol_id):
    require_role("ProtocolCoordinator")
    protocol = get_or_404("protocols", protocol_id)
    if protocol["status"] != "HELD":
        raise ApiError("ERR_PROTOCOL_NOT_HELD")
    for hold in DB["holds"].values():
        if hold["protocol_id"] != protocol["id"]:
            continue
        if hold["status"] == "ACTIVE":
            raise ApiError("ERR_PROTOCOL_HOLD_ACTIVE")
    protocol["is_protocol_held"] = False
    protocol["status"] = "OPEN"
    recompute_protocol_derived(protocol)
    touch(protocol)
    return success_object(serialize_protocol(protocol), 200)


@bp.get("/programs/clinical-protocols/<protocol_id>/funding-posture")
def funding_posture(protocol_id):
    require_role("Any")
    protocol = get_or_404("protocols", protocol_id)
    recompute_protocol_derived(protocol)
    return success_object({
        "protocol_id": protocol["id"],
        "protocol_version": protocol["version"],
        "protocol_status": protocol["status"],
        "capacity": protocol["capacity"],
        "enrolled_count": protocol["enrolled_count"],
        "protocol_budget_cents": protocol["protocol_budget_cents"],
        "reserved_cents": protocol["reserved_cents"],
        "committed_cents": protocol["committed_cents"],
        "available_cents": protocol["available_cents"],
        "is_budget_saturated": protocol["is_budget_saturated"],
        "is_protocol_held": protocol["is_protocol_held"],
    }, 200)


@bp.get("/programs/clinical-protocols/<protocol_id>/referrals")
def list_protocol_referrals(protocol_id):
    require_role("Any")
    get_or_404("protocols", protocol_id)
    from services import serialize_referral
    status = arg("status")
    rows = ordered([r for r in DB["referrals"].values()
                    if r["protocol_id"] == protocol_id])
    rows = filtered(rows, status=status)
    return list_response(rows, serialize_referral)


@bp.get("/programs/clinical-protocols/<protocol_id>/studies")
def list_protocol_studies(protocol_id):
    require_role("Any")
    get_or_404("protocols", protocol_id)
    rows = ordered([s for s in DB["studies"].values()
                    if s["protocol_id"] == protocol_id])
    return list_response(rows, serialize_study)


@bp.get("/programs/clinical-protocols/<protocol_id>/holds")
def list_protocol_holds(protocol_id):
    require_role("Any")
    get_or_404("protocols", protocol_id)
    status = arg("status")
    rows = ordered([h for h in DB["holds"].values()
                    if h["protocol_id"] == protocol_id])
    rows = filtered(rows, status=status)
    return list_response(rows, serialize_hold)


@bp.get("/programs/clinical-protocols/<protocol_id>/affiliations")
def list_protocol_affiliations(protocol_id):
    require_role("Any")
    get_or_404("protocols", protocol_id)
    from services import serialize_agreement
    clinic_id = arg("clinic_id")
    status = arg("status")
    rows = ordered([a for a in DB["affiliations"].values()
                    if a["protocol_id"] == protocol_id])
    rows = filtered(rows, clinic_id=clinic_id, status=status)
    return list_response(rows, serialize_agreement)