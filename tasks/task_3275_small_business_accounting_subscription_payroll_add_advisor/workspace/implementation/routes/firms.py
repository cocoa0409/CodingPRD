"""Firms and accountant users."""
from flask import Blueprint
import db
from auth import require_role, require_firm_scope
from errors import ok, ok_list, duplicate, invalid_state, billing_blocked, invalid_request
from helpers import body_json, req_str, req_number, get_or_404, paginate, sort_by_created, enum_check
import serializers

bp = Blueprint("firms", __name__, url_prefix="/api")

TIERS = ("SILVER", "GOLD", "PLATINUM")


@bp.post("/firms")
def create_firm():
    require_role(["PlatformAdmin"])
    data = body_json()
    firm_name = req_str(data, "firm_name")
    pct = req_number(data, "wholesale_discount_pct")
    if pct < 0 or pct > 0.50:
        invalid_request("wholesale_discount_pct must be between 0 and 0.50")
    tier = enum_check(req_str(data, "proadvisor_tier"), TIERS, "proadvisor_tier")
    rec = {
        "firm_name": firm_name,
        "wholesale_discount_pct": pct,
        "proadvisor_tier": tier,
        "firm_status": "ACTIVE",
    }
    db.stamp_common(rec)
    db.TABLES["AccountantFirm"][rec["id"]] = rec
    return ok(serializers.serialize_firm(rec), status=201)


@bp.get("/firms/<firm_id>")
def get_firm(firm_id):
    role, identity = require_role(["PlatformAdmin", "AccountantUser"])
    rec = get_or_404("AccountantFirm", firm_id)
    if role == "AccountantUser":
        require_firm_scope(identity, firm_id)
    return ok(serializers.serialize_firm(rec))


@bp.post("/firms/<firm_id>/suspend")
def suspend_firm(firm_id):
    require_role(["PlatformAdmin"])
    firm = get_or_404("AccountantFirm", firm_id)
    if firm["firm_status"] != "ACTIVE":
        invalid_state("Firm not ACTIVE")
    firm["firm_status"] = "SUSPENDED"
    db.touch(firm)
    for g in db.TABLES["AccessGrant"].values():
        if g["firm_id"] == firm_id and g["grant_status"] == "ACTIVE":
            g["grant_status"] = "REVOKED"
            db.touch(g)
    return ok(serializers.serialize_firm(firm))


@bp.post("/firms/<firm_id>/reactivate")
def reactivate_firm(firm_id):
    require_role(["PlatformAdmin"])
    firm = get_or_404("AccountantFirm", firm_id)
    if firm["firm_status"] != "SUSPENDED":
        invalid_state("Firm not SUSPENDED")
    firm["firm_status"] = "ACTIVE"
    db.touch(firm)
    return ok(serializers.serialize_firm(firm))


@bp.post("/firms/<firm_id>/close")
def close_firm(firm_id):
    require_role(["PlatformAdmin"])
    firm = get_or_404("AccountantFirm", firm_id)
    if firm["firm_status"] not in ("ACTIVE", "SUSPENDED"):
        invalid_state("Firm already CLOSED")
    for s in db.TABLES["Subscription"].values():
        if (s.get("billing_firm_id") == firm_id and s["billing_owner"] == "FIRM"
                and s["lifecycle_status"] in ("TRIAL", "ACTIVE", "PAST_DUE", "SUSPENDED")):
            billing_blocked()
    for g in db.TABLES["AccessGrant"].values():
        if g["firm_id"] == firm_id and g["grant_status"] in ("PENDING_ACCEPT", "ACTIVE"):
            billing_blocked()
    firm["firm_status"] = "CLOSED"
    db.touch(firm)
    for t in db.TABLES["BillingTransfer"].values():
        if t["initiating_firm_id"] == firm_id and \
                t["transfer_status"] in ("PENDING_CLIENT_ACCEPT", "PENDING_FIRM_ACCEPT"):
            t["transfer_status"] = "CANCELLED"
            db.touch(t)
    return ok(serializers.serialize_firm(firm))


@bp.post("/firms/<firm_id>/users")
def create_accountant_user(firm_id):
    require_role(["PlatformAdmin"])
    firm = get_or_404("AccountantFirm", firm_id)
    data = body_json()
    body_firm_id = data.get("firm_id")
    if body_firm_id is not None and body_firm_id != firm_id:
        from errors import not_found
        not_found("firm_id in body does not match path")
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    for u in db.TABLES["AccountantUser"].values():
        if u["firm_id"] == firm_id and u["email"] == email:
            duplicate("email already exists within firm")
    rec = {
        "firm_id": firm_id,
        "full_name": full_name,
        "email": email,
        "is_firm_admin": bool(data.get("is_firm_admin", False)),
        "user_status": "ACTIVE",
    }
    db.stamp_common(rec)
    db.TABLES["AccountantUser"][rec["id"]] = rec
    return ok(serializers.serialize_accountant_user(rec), status=201)


@bp.get("/firms/<firm_id>/users")
def list_accountant_users(firm_id):
    role, identity = require_role(["PlatformAdmin", "AccountantUser"])
    get_or_404("AccountantFirm", firm_id)
    if role == "AccountantUser":
        require_firm_scope(identity, firm_id)
    items = [u for u in db.TABLES["AccountantUser"].values() if u["firm_id"] == firm_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_accountant_user(u) for u in page],
                   limit, offset, total)


@bp.get("/firms/<firm_id>/users/<user_id>")
def get_accountant_user(firm_id, user_id):
    role, identity = require_role(["PlatformAdmin", "AccountantUser"])
    get_or_404("AccountantFirm", firm_id)
    rec = get_or_404("AccountantUser", user_id)
    if rec["firm_id"] != firm_id:
        from errors import not_found
        not_found("AccountantUser not in firm")
    if role == "AccountantUser":
        require_firm_scope(identity, firm_id)
    return ok(serializers.serialize_accountant_user(rec))
