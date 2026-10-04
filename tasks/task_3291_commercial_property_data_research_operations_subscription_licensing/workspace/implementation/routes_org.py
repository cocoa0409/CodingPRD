"""Organization and User endpoints (PRD 2.1, 2.8, 3.11)."""
from flask import Blueprint, request

import auth
import core
import lookups
import responses
from serializers import organization as ser_organization
from serializers import user as ser_user

bp = Blueprint("org", __name__, url_prefix="/data-research")

ORG_TYPES = {"DATA_PROVIDER", "BROKERAGE", "SUBSCRIBER"}
SERVICE_TIERS = {"ENTERPRISE", "MID_MARKET", "SMB"}
USER_ROLES = {
    "RESEARCH_ANALYST",
    "SEAT_USER",
    "LICENSING_ADMIN",
    "ENFORCEMENT_OFFICER",
    "BROKER_PUBLISHER",
}


@bp.post("/organizations")
def create_organization():
    user_id, role = auth.read_headers()
    payload = core.body_of(request)
    legal_name = core.require_string(payload, "legal_name")
    org_type = core.require_enum(payload, "org_type", ORG_TYPES)
    home_market = core.require_string(payload, "home_market")
    service_tier = core.optional_enum(payload, "service_tier", SERVICE_TIERS, "ENTERPRISE")
    auth.authorize_as(user_id, role, ["PlatformAdmin"])

    org = {
        "legal_name": legal_name,
        "org_type": org_type,
        "home_market": home_market,
        "service_tier": service_tier,
        "authorized_market_count": 0,
        "active_contract_count": 0,
        "status": "ACTIVE",
    }
    core.stamp_created(org)
    core.organizations[org["id"]] = org
    return responses.ok_object(ser_organization(org), 201)


@bp.get("/organizations/<organization_id>")
def get_organization(organization_id):
    auth.authorize(["PlatformAdmin", "LicensingAdmin", "EnforcementOfficer"])
    org = lookups.get_organization(organization_id)
    return responses.ok_object(ser_organization(org))


@bp.get("/organizations/<organization_id>/users")
def list_organization_users(organization_id):
    auth.authorize(["PlatformAdmin", "LicensingAdmin"])
    lookups.get_organization(organization_id)
    limit, offset = core.pagination_args(request)
    rows = [u for u in core.users.values() if u["organization_id"] == organization_id]
    return responses.paged(rows, limit, offset, ser_user)


@bp.post("/organizations/<organization_id>/users")
def create_user(organization_id):
    user_id, role = auth.read_headers()
    payload = core.body_of(request)
    email = core.require_string(payload, "email")
    full_name = core.require_string(payload, "full_name")
    user_role = core.require_enum(payload, "role", USER_ROLES)
    assigned_market = core.optional_string(payload, "assigned_market", None)
    if user_role == "RESEARCH_ANALYST" and (assigned_market is None or assigned_market == ""):
        raise core.ApiError("ERR_INVALID_REQUEST",
                            "assigned_market is required for a RESEARCH_ANALYST user.")
    auth.authorize_as(user_id, role, ["PlatformAdmin", "LicensingAdmin"])
    org = lookups.get_organization(organization_id)
    for existing in core.users.values():
        if existing["organization_id"] == org["id"] and existing["email"] == email:
            raise core.ApiError("ERR_INVALID_REQUEST",
                                "email must be unique within the organization.")

    user = {
        "organization_id": org["id"],
        "email": email,
        "full_name": full_name,
        "role": user_role,
        "assigned_market": assigned_market,
        "status": "ACTIVE",
    }
    core.stamp_created(user)
    core.users[user["id"]] = user
    return responses.ok_object(ser_user(user), 201)


@bp.get("/users")
def list_users():
    auth.authorize(["PlatformAdmin", "LicensingAdmin"])
    limit, offset = core.pagination_args(request)
    org_filter = request.args.get("organization_id")
    role_filter = request.args.get("role")
    rows = list(core.users.values())
    if org_filter:
        rows = [u for u in rows if u["organization_id"] == org_filter]
    if role_filter:
        rows = [u for u in rows if u["role"] == role_filter]
    return responses.paged(rows, limit, offset, ser_user)


@bp.get("/users/<user_id>")
def get_user(user_id):
    auth.authorize(["PlatformAdmin", "LicensingAdmin", "EnforcementOfficer", "ResearchAnalyst"])
    user = lookups.get_user(user_id)
    return responses.ok_object(ser_user(user))


@bp.post("/users/<user_id>/deactivation")
def deactivate_user(user_id):
    auth.authorize(["PlatformAdmin", "LicensingAdmin"])
    user = lookups.get_user(user_id)
    if user["status"] != "ACTIVE":
        raise core.ApiError("ERR_INVALID_STATE")
    user["status"] = "INACTIVE"
    core.touch(user)
    return responses.ok_object(ser_user(user))