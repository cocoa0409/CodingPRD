"""Billing transfers."""
from datetime import timedelta
from flask import Blueprint
import db
import services
from auth import require_role, require_company_scope, require_firm_scope
from errors import (ok, ok_list, invalid_state, not_writable, transfer_pending,
                    transfer_expired, firm_not_active, stale_version,
                    needs_primary_admin, not_found, invalid_request,
                    forbidden_role, window_expired, ApiError)
from helpers import (body_json, req_str, get_or_404, paginate, sort_by_created,
                     enum_check, filter_items, company_subscription)
import serializers

bp = Blueprint("transfers", __name__, url_prefix="/api")

OWNERS = ("CLIENT", "FIRM")
PENDING_STATES = ("PENDING_CLIENT_ACCEPT", "PENDING_FIRM_ACCEPT")


def _get_transfer(company_id, tid):
    get_or_404("ClientCompany", company_id)
    rec = get_or_404("BillingTransfer", tid)
    if rec["company_id"] != company_id:
        not_found("BillingTransfer not in company")
    return rec


def _check_not_expired(rec):
    exp = db.parse_iso(rec["expires_at"])
    if exp is not None and db.now() >= exp:
        transfer_expired()


@bp.post("/companies/<company_id>/billing_transfers")
def create_transfer(company_id):
    role, identity = require_role(["AccountantUser", "CompanyUser"])
    get_or_404("ClientCompany", company_id)
    sub = company_subscription(company_id)
    if sub is None:
        not_found("Subscription not found")
    if sub["lifecycle_status"] in ("CANCELLED_READ_ONLY", "CANCELLED_EXPIRED"):
        not_writable()
    data = body_json()
    body_company = data.get("company_id")
    if body_company is not None and body_company != company_id:
        not_found("company_id in body does not match path")
    subscription_id = req_str(data, "subscription_id")
    if subscription_id != sub["id"]:
        not_found("Subscription not found")
    firm_id = req_str(data, "initiating_firm_id")
    firm = db.TABLES["AccountantFirm"].get(firm_id)
    if firm is None:
        not_found("AccountantFirm not found")
    to_owner = enum_check(req_str(data, "to_owner"), OWNERS, "to_owner")
    if role == "AccountantUser":
        if not identity.get("is_firm_admin"):
            forbidden_role()
        if identity.get("firm_id") != firm_id:
            raise ApiError("ERR_IDENTITY_MISMATCH", 403,
                           "AccountantUser not in initiating firm")
    else:
        require_company_scope(identity, company_id)
        if identity.get("permission_level") != "PRIMARY_ADMIN":
            needs_primary_admin()
    for t in db.TABLES["BillingTransfer"].values():
        if t["subscription_id"] == sub["id"] and t["transfer_status"] in PENDING_STATES:
            transfer_pending()
    rec = {
        "company_id": company_id,
        "subscription_id": sub["id"],
        "from_owner": sub["billing_owner"],
        "to_owner": to_owner,
        "initiating_firm_id": firm_id,
        "transfer_status": "PENDING_CLIENT_ACCEPT",
        "expires_at": db.fmt(db.now() + timedelta(days=14)),
        "decline_reason": None,
    }
    db.stamp_common(rec)
    rec["proforma_monthly_cents"] = services.transfer_proforma(rec)
    db.TABLES["BillingTransfer"][rec["id"]] = rec
    return ok(serializers.serialize_billing_transfer(rec), status=201)


@bp.get("/companies/<company_id>/billing_transfers")
def list_transfers(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    items = [t for t in db.TABLES["BillingTransfer"].values()
             if t["company_id"] == company_id]
    items = filter_items(items, [("transfer_status", "transfer_status")])
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_billing_transfer(t) for t in page],
                   limit, offset, total)


@bp.get("/companies/<company_id>/billing_transfers/<tid>")
def get_transfer(company_id, tid):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    rec = _get_transfer(company_id, tid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    return ok(serializers.serialize_billing_transfer(rec))


def _complete_transfer(rec):
    sub = db.TABLES["Subscription"].get(rec["subscription_id"])
    sub["billing_owner"] = rec["to_owner"]
    sub["billing_firm_id"] = rec["initiating_firm_id"] if rec["to_owner"] == "FIRM" else None
    sub["monthly_price_cents"] = services.monthly_price_cents(sub)
    db.touch(sub)
    rec["transfer_status"] = "COMPLETED"
    db.touch(rec)


@bp.post("/companies/<company_id>/billing_transfers/<tid>/accept")
def client_accept_transfer(company_id, tid):
    role, identity = require_role(["CompanyUser"])
    rec = _get_transfer(company_id, tid)
    require_company_scope(identity, company_id)
    if identity.get("permission_level") != "PRIMARY_ADMIN":
        needs_primary_admin()
    _check_not_expired(rec)
    if rec["transfer_status"] != "PENDING_CLIENT_ACCEPT":
        invalid_state("Transfer not PENDING_CLIENT_ACCEPT")
    sub = db.TABLES["Subscription"].get(rec["subscription_id"])
    if sub["lifecycle_status"] not in ("ACTIVE", "TRIAL", "REACTIVATED"):
        invalid_state("Subscription not in an acceptable state")
    data = body_json()
    expected = data.get("expected_subscription_version")
    if expected is None:
        invalid_request("expected_subscription_version is required")
    if expected != sub["version"]:
        stale_version()
    _complete_transfer(rec)
    return ok(serializers.serialize_billing_transfer(rec))


@bp.post("/companies/<company_id>/billing_transfers/<tid>/counter")
def counter_transfer(company_id, tid):
    role, identity = require_role(["CompanyUser"])
    rec = _get_transfer(company_id, tid)
    require_company_scope(identity, company_id)
    if identity.get("permission_level") != "PRIMARY_ADMIN":
        needs_primary_admin()
    _check_not_expired(rec)
    if rec["transfer_status"] != "PENDING_CLIENT_ACCEPT":
        invalid_state("Transfer not PENDING_CLIENT_ACCEPT")
    rec["transfer_status"] = "PENDING_FIRM_ACCEPT"
    db.touch(rec)
    return ok(serializers.serialize_billing_transfer(rec))


@bp.post("/companies/<company_id>/billing_transfers/<tid>/decline")
def decline_transfer(company_id, tid):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    rec = _get_transfer(company_id, tid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
        if identity.get("permission_level") != "PRIMARY_ADMIN":
            needs_primary_admin()
    else:
        if not identity.get("is_firm_admin"):
            forbidden_role()
        if identity.get("firm_id") != rec["initiating_firm_id"]:
            raise ApiError("ERR_IDENTITY_MISMATCH", 403, "Not the initiating firm")
    if rec["transfer_status"] not in PENDING_STATES:
        invalid_state("Transfer not pending")
    data = body_json()
    reason = req_str(data, "decline_reason")
    rec["transfer_status"] = "DECLINED"
    rec["decline_reason"] = reason
    db.touch(rec)
    return ok(serializers.serialize_billing_transfer(rec))


@bp.post("/companies/<company_id>/billing_transfers/<tid>/cancel")
def cancel_transfer(company_id, tid):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    rec = _get_transfer(company_id, tid)
    if rec["transfer_status"] not in PENDING_STATES:
        invalid_state("Transfer not pending")
    # initiating party: PRIMARY_ADMIN if from_owner == CLIENT else firm_admin
    if rec["from_owner"] == "CLIENT":
        if role != "CompanyUser":
            forbidden_role()
        require_company_scope(identity, company_id)
        if identity.get("permission_level") != "PRIMARY_ADMIN":
            needs_primary_admin()
    else:
        if role != "AccountantUser":
            forbidden_role()
        if not identity.get("is_firm_admin"):
            forbidden_role()
        if identity.get("firm_id") != rec["initiating_firm_id"]:
            raise ApiError("ERR_IDENTITY_MISMATCH", 403, "Not the initiating firm")
    rec["transfer_status"] = "CANCELLED"
    db.touch(rec)
    return ok(serializers.serialize_billing_transfer(rec))


@bp.post("/firms/<firm_id>/billing_transfers/<tid>/accept")
def firm_accept_transfer(firm_id, tid):
    role, identity = require_role(["AccountantUser"])
    firm = get_or_404("AccountantFirm", firm_id)
    rec = get_or_404("BillingTransfer", tid)
    if rec["initiating_firm_id"] != firm_id:
        not_found("Transfer not for firm")
    require_firm_scope(identity, firm_id)
    if not identity.get("is_firm_admin"):
        forbidden_role()
    _check_not_expired(rec)
    if rec["transfer_status"] != "PENDING_FIRM_ACCEPT":
        invalid_state("Transfer not PENDING_FIRM_ACCEPT")
    if firm["firm_status"] != "ACTIVE":
        firm_not_active()
    _complete_transfer(rec)
    return ok(serializers.serialize_billing_transfer(rec))
