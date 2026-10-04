from flask import Blueprint, request

from db import db
from middleware import get_context, require_role
from response import APIError, success
from services import (
    compute_insurance,
    get_broker,
    get_carrier,
    get_verification,
    lazy_expire_verification,
    new_resource,
    paginate,
    parse_limit_offset,
    require_fields,
    sorted_by_created,
    touch,
)
from util import parse_dt

bp = Blueprint("authority", __name__)

READ_ROLES = ("PlatformAdmin", "ComplianceAnalyst", "DataOps", "BrokerAdmin", "CarrierAdmin")


def ver_view(v):
    compute_insurance(db, v)
    lazy_expire_verification(db, v, touch_on_change=False)
    return v


@bp.post("/authority-verifications")
def create_verification():
    user_id, role = get_context()
    require_role(role, ("BrokerAdmin", "CarrierAdmin"))
    body = request.get_json(silent=True) or {}
    require_fields(body, ["authority_reference", "insurance_windows"])
    broker_org_id = body.get("broker_org_id")
    carrier_org_id = body.get("carrier_org_id")
    if (broker_org_id is None) == (carrier_org_id is None):
        raise APIError("ERR_INVALID_REQUEST", 400, "Exactly one of broker_org_id or carrier_org_id is required")
    windows = body["insurance_windows"]
    if not isinstance(windows, list):
        raise APIError("ERR_INVALID_REQUEST", 400, "insurance_windows must be an array")
    for w in windows:
        if not isinstance(w, dict) or parse_dt(w.get("effective_from")) is None or parse_dt(w.get("effective_to")) is None:
            raise APIError("ERR_INVALID_REQUEST", 400, "Each insurance window needs effective_from and effective_to datetimes")
    if role == "BrokerAdmin":
        if broker_org_id is None or broker_org_id != user_id:
            raise APIError("ERR_NOT_RESOURCE_OWNER", 403, "BrokerAdmin may only submit verifications for its own org")
        get_broker(db, broker_org_id)
    else:
        if carrier_org_id is None or carrier_org_id != user_id:
            raise APIError("ERR_NOT_RESOURCE_OWNER", 403, "CarrierAdmin may only submit verifications for its own org")
        get_carrier(db, carrier_org_id)
    ver = new_resource(db, {
        "broker_org_id": broker_org_id,
        "carrier_org_id": carrier_org_id,
        "authority_reference": body["authority_reference"],
        "insurance_windows": windows,
        "status": "PENDING",
        "insurance_ok": False,
        "covered_until": None,
        "coverage_gap_detected": False,
    })
    compute_insurance(db, ver)
    db.authority_verifications[ver["id"]] = ver
    return success(ver_view(ver), 201)


@bp.get("/authority-verifications/<ver_id>")
def get_verification_route(ver_id):
    _, role = get_context()
    require_role(role, READ_ROLES)
    return success(ver_view(get_verification(db, ver_id)))


@bp.get("/broker-orgs/<org_id>/authority-verifications")
def list_broker_verifications(org_id):
    _, role = get_context()
    require_role(role, READ_ROLES)
    get_broker(db, org_id)
    limit, offset = parse_limit_offset()
    items = [ver_view(v) for v in db.authority_verifications.values() if v.get("broker_org_id") == org_id]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, 200, meta)


@bp.get("/carrier-orgs/<org_id>/authority-verifications")
def list_carrier_verifications(org_id):
    _, role = get_context()
    require_role(role, READ_ROLES)
    get_carrier(db, org_id)
    limit, offset = parse_limit_offset()
    items = [ver_view(v) for v in db.authority_verifications.values() if v.get("carrier_org_id") == org_id]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, 200, meta)


@bp.post("/authority-verifications/<ver_id>/verify")
def verify_authority(ver_id):
    _, role = get_context()
    require_role(role, ("ComplianceAnalyst",))
    ver = get_verification(db, ver_id)
    if ver["status"] not in ("PENDING", "EXPIRED"):
        raise APIError("ERR_INVALID_REQUEST", 400, "Verification cannot be verified from its current state")
    if not ver.get("authority_reference"):
        raise APIError("ERR_INVALID_REQUEST", 400, "authority_reference must be non-empty")
    compute_insurance(db, ver)
    if not ver["insurance_ok"]:
        raise APIError("ERR_INSURANCE_WINDOW_GAP", 422, "Insurance windows contain a gap or do not cover the current clock")
    ver["status"] = "VERIFIED"
    touch(db, ver)
    return success(ver_view(ver))


@bp.post("/authority-verifications/<ver_id>/revoke")
def revoke_authority(ver_id):
    _, role = get_context()
    require_role(role, ("ComplianceAnalyst",))
    ver = get_verification(db, ver_id)
    if ver["status"] not in ("PENDING", "VERIFIED", "EXPIRED"):
        raise APIError("ERR_INVALID_REQUEST", 400, "Verification cannot be revoked from its current state")
    ver["status"] = "REVOKED"
    touch(db, ver)
    return success(ver_view(ver))
