"""Clock + Organization endpoints."""
import flask

import db
from helpers import (err, success, get_json_body, require_fields, require_int,
                     parse_pagination, list_response, stamp_new, touch)
from middleware import authenticate, require_role, check_ownership
from services import price_level_for

bp = flask.Blueprint("clock_orgs", __name__)


@bp.post("/licensing/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    require_role(role, ("ProgramAdministrator",))
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    try:
        clk = db.set_clock(body["to_iso8601"])
    except Exception:
        err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant.", 400)
    return success({"current_utc": db.now_iso()}, status=200, response_type="object")


@bp.post("/licensing/organizations")
def create_org():
    _, role = authenticate()
    require_role(role, ("ProgramAdministrator",))
    body = get_json_body()
    require_fields(body, ["legal_name", "qualified_device_count"])
    if not isinstance(body["legal_name"], str):
        err("ERR_INVALID_REQUEST", "legal_name must be a string.", 400)
    qdc = require_int(body, "qualified_device_count", minimum=1)
    org = {
        "legal_name": body["legal_name"],
        "qualified_device_count": qdc,
        "price_level": price_level_for(qdc),
    }
    stamp_new(org, with_version=True)
    db.organizations[org["id"]] = org
    return success(org, status=201, response_type="object")


@bp.get("/licensing/organizations/<org_id>")
def get_org(org_id):
    user_id, role = authenticate()
    require_role(role, ("ProgramAdministrator", "LicensingSpecialist", "CustomerAdmin", "Auditor"))
    org = db.organizations.get(org_id)
    if org is None:
        err("ERR_NOT_FOUND", "Organization not found.", 404)
    check_ownership(user_id, role, org["id"])
    return success(org, status=200, response_type="object")


@bp.get("/licensing/organizations")
def list_orgs():
    _, role = authenticate()
    require_role(role, ("ProgramAdministrator", "LicensingSpecialist", "Auditor"))
    limit, offset = parse_pagination()
    return list_response(list(db.organizations.values()), limit, offset)


@bp.patch("/licensing/organizations/<org_id>")
def patch_org(org_id):
    _, role = authenticate()
    require_role(role, ("ProgramAdministrator",))
    org = db.organizations.get(org_id)
    if org is None:
        err("ERR_NOT_FOUND", "Organization not found.", 404)
    body = get_json_body()
    if "legal_name" in body:
        if not isinstance(body["legal_name"], str):
            err("ERR_INVALID_REQUEST", "legal_name must be a string.", 400)
        org["legal_name"] = body["legal_name"]
    if "qualified_device_count" in body:
        qdc = require_int(body, "qualified_device_count", minimum=1)
        org["qualified_device_count"] = qdc
        org["price_level"] = price_level_for(qdc)
    touch(org)
    return success(org, status=200, response_type="object")


@bp.get("/licensing/organizations/<org_id>/agreements")
def list_org_agreements(org_id):
    user_id, role = authenticate()
    require_role(role, ("ProgramAdministrator", "LicensingSpecialist", "CustomerAdmin", "Auditor"))
    org = db.organizations.get(org_id)
    if org is None:
        err("ERR_NOT_FOUND", "Organization not found.", 404)
    check_ownership(user_id, role, org["id"])
    limit, offset = parse_pagination()
    items = [a for a in db.agreements.values() if a["organization_id"] == org_id]
    return list_response(items, limit, offset)
