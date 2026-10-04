"""Access grants."""
from flask import Blueprint
import db
from auth import require_role, require_company_scope, require_firm_scope
from errors import (ok, ok_list, invalid_state, not_writable,
                    grant_not_acceptable, grant_not_revocable,
                    duplicate_active_grant, firm_not_active, window_expired,
                    not_found, forbidden_role, ApiError)
from helpers import (body_json, req_str, get_or_404, paginate, sort_by_created,
                     enum_check, filter_items, company_subscription,
                     parse_dt_field)
import serializers

bp = Blueprint("grants", __name__, url_prefix="/api")

ACCESS_LEVELS = ("FULL_BOOKKEEPING", "REPORTS_READ_ONLY", "PAYROLL_ONLY")


@bp.post("/companies/<company_id>/access_grants")
def create_grant(company_id):
    role, identity = require_role(["CompanyUser"])
    get_or_404("ClientCompany", company_id)
    require_company_scope(identity, company_id)
    sub = company_subscription(company_id)
    if sub is not None and sub["lifecycle_status"] in ("CANCELLED_READ_ONLY", "CANCELLED_EXPIRED"):
        not_writable()
    data = body_json()
    body_company = data.get("company_id")
    if body_company is not None and body_company != company_id:
        not_found("company_id in body does not match path")
    au_id = req_str(data, "accountant_user_id")
    au = db.TABLES["AccountantUser"].get(au_id)
    if au is None:
        not_found("AccountantUser not found")
    firm_id = req_str(data, "firm_id")
    firm = db.TABLES["AccountantFirm"].get(firm_id)
    if firm is None:
        not_found("AccountantFirm not found")
    level = enum_check(req_str(data, "access_level"), ACCESS_LEVELS, "access_level")
    expires = parse_dt_field(data, "expires_at", required=False)
    for g in db.TABLES["AccessGrant"].values():
        if (g["company_id"] == company_id
                and g["accountant_user_id"] == au_id
                and g["grant_status"] == "ACTIVE"):
            duplicate_active_grant()
    rec = {
        "company_id": company_id,
        "accountant_user_id": au_id,
        "firm_id": firm_id,
        "access_level": level,
        "grant_status": "PENDING_ACCEPT",
        "expires_at": db.fmt(expires) if expires else None,
    }
    db.stamp_common(rec)
    db.TABLES["AccessGrant"][rec["id"]] = rec
    return ok(serializers.serialize_access_grant(rec), status=201)


@bp.get("/companies/<company_id>/access_grants")
def list_grants(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    items = [g for g in db.TABLES["AccessGrant"].values() if g["company_id"] == company_id]
    items = filter_items(items, [("grant_status", "grant_status"),
                                 ("firm_id", "firm_id")])
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_access_grant(g) for g in page],
                   limit, offset, total)


def _get_grant(company_id, gid):
    get_or_404("ClientCompany", company_id)
    rec = get_or_404("AccessGrant", gid)
    if rec["company_id"] != company_id:
        not_found("Grant not in company")
    return rec


def _auto_expire(grant):
    exp = db.parse_iso(grant.get("expires_at")) if grant.get("expires_at") else None
    if exp is not None and db.now() >= exp and \
            grant["grant_status"] in ("PENDING_ACCEPT", "ACTIVE"):
        grant["grant_status"] = "EXPIRED"
        db.touch(grant)


@bp.get("/companies/<company_id>/access_grants/<gid>")
def get_grant(company_id, gid):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    rec = _get_grant(company_id, gid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    _auto_expire(rec)
    return ok(serializers.serialize_access_grant(rec))


@bp.post("/companies/<company_id>/access_grants/<gid>/revoke")
def revoke_grant(company_id, gid):
    role, identity = require_role(["CompanyUser"])
    rec = _get_grant(company_id, gid)
    require_company_scope(identity, company_id)
    if identity.get("permission_level") not in ("PRIMARY_ADMIN", "COMPANY_ADMIN"):
        forbidden_role()
    if rec["grant_status"] not in ("PENDING_ACCEPT", "ACTIVE"):
        grant_not_revocable()
    rec["grant_status"] = "REVOKED"
    db.touch(rec)
    return ok(serializers.serialize_access_grant(rec))


@bp.post("/firms/<firm_id>/access_grants/<gid>/accept")
def accept_grant(firm_id, gid):
    role, identity = require_role(["AccountantUser"])
    firm = get_or_404("AccountantFirm", firm_id)
    rec = get_or_404("AccessGrant", gid)
    if rec["firm_id"] != firm_id:
        not_found("Grant not for firm")
    require_firm_scope(identity, firm_id)
    if rec["accountant_user_id"] != identity["id"]:
        raise ApiError("ERR_IDENTITY_MISMATCH", 403, "Only the grant recipient may accept")
    if firm["firm_status"] != "ACTIVE":
        firm_not_active()
    if rec["grant_status"] != "PENDING_ACCEPT":
        grant_not_acceptable()
    exp = db.parse_iso(rec.get("expires_at")) if rec.get("expires_at") else None
    if exp is not None and db.now() >= exp:
        rec["grant_status"] = "EXPIRED"
        db.touch(rec)
        window_expired()
    rec["grant_status"] = "ACTIVE"
    db.touch(rec)
    return ok(serializers.serialize_access_grant(rec))
