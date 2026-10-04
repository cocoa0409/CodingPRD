"""Payroll addon + employees."""
from flask import Blueprint
import db
import services
from auth import require_role, require_company_scope, active_grant
from errors import (ok, ok_list, invalid_state, not_writable, payroll_already_active,
                    payroll_not_active, payroll_cancel_blocked, employee_terminated,
                    needs_primary_admin, stale_version, not_found, invalid_request,
                    ApiError)
from helpers import (body_json, req_str, req_int, get_or_404, paginate,
                     sort_by_created, enum_check, filter_items,
                     company_subscription, company_payroll, parse_dt_field)
import serializers

bp = Blueprint("payroll", __name__, url_prefix="/api/companies/<company_id>")

SERVICE_LEVELS = ("SELF_SERVICE", "FULL_SERVICE")


def _sub_writable_for_payroll(company_id):
    sub = company_subscription(company_id)
    if sub is None:
        not_found("Subscription not found")
    if sub["lifecycle_status"] in ("CANCELLED_READ_ONLY", "CANCELLED_EXPIRED"):
        not_writable()
    return sub


def _recompute_filing(addon, company_id):
    addon["tax_filing_status"] = services.payroll_tax_filing_status(addon, company_id)


@bp.post("/payroll")
def create_payroll(company_id):
    role, identity = require_role(["CompanyUser"])
    get_or_404("ClientCompany", company_id)
    require_company_scope(identity, company_id)
    sub = _sub_writable_for_payroll(company_id)
    data = body_json()
    subscription_id = req_str(data, "subscription_id")
    if subscription_id != sub["id"]:
        not_found("Subscription not found for company")
    service_level = enum_check(req_str(data, "service_level"), SERVICE_LEVELS, "service_level")
    for p in db.TABLES["PayrollAddon"].values():
        if p["subscription_id"] == sub["id"] and p["addon_status"] in ("ACTIVE", "PAUSED"):
            payroll_already_active()
    rate = services.PAYROLL_RATE_CARD[service_level]
    rec = {
        "subscription_id": sub["id"],
        "service_level": service_level,
        "base_fee_cents": rate["base_fee_cents"],
        "per_employee_fee_cents": rate["per_employee_fee_cents"],
        "addon_status": "ACTIVE",
        "tax_filing_status": "NOT_READY",
        "activated_at": db.fmt(db.now()),
    }
    db.stamp_common(rec)
    db.TABLES["PayrollAddon"][rec["id"]] = rec
    return ok(serializers.serialize_payroll_addon(rec), status=201)


@bp.get("/payroll")
def get_payroll(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    addon = company_payroll(company_id)
    if addon is None:
        not_found("PayrollAddon not found")
    _recompute_filing(addon, company_id)
    return ok(serializers.serialize_payroll_addon(addon))


@bp.post("/payroll/pause")
def pause_payroll(company_id):
    role, identity = require_role(["CompanyUser"])
    get_or_404("ClientCompany", company_id)
    require_company_scope(identity, company_id)
    _sub_writable_for_payroll(company_id)
    addon = company_payroll(company_id)
    if addon is None:
        not_found("PayrollAddon not found")
    if addon["addon_status"] != "ACTIVE":
        invalid_state("PayrollAddon not ACTIVE")
    addon["addon_status"] = "PAUSED"
    db.touch(addon)
    return ok(serializers.serialize_payroll_addon(addon))


@bp.post("/payroll/resume")
def resume_payroll(company_id):
    role, identity = require_role(["CompanyUser"])
    get_or_404("ClientCompany", company_id)
    require_company_scope(identity, company_id)
    sub = _sub_writable_for_payroll(company_id)
    addon = company_payroll(company_id)
    if addon is None:
        not_found("PayrollAddon not found")
    if addon["addon_status"] != "PAUSED":
        invalid_state("PayrollAddon not PAUSED")
    if sub["lifecycle_status"] not in ("ACTIVE", "REACTIVATED"):
        invalid_state("Parent subscription not ACTIVE/REACTIVATED")
    addon["addon_status"] = "ACTIVE"
    db.touch(addon)
    return ok(serializers.serialize_payroll_addon(addon))


@bp.post("/payroll/cancel")
def cancel_payroll(company_id):
    role, identity = require_role(["CompanyUser"])
    get_or_404("ClientCompany", company_id)
    require_company_scope(identity, company_id)
    _sub_writable_for_payroll(company_id)
    if identity.get("permission_level") != "PRIMARY_ADMIN":
        needs_primary_admin()
    addon = company_payroll(company_id)
    if addon is None:
        not_found("PayrollAddon not found")
    if addon["addon_status"] not in ("ACTIVE", "PAUSED"):
        invalid_state("PayrollAddon not cancellable")
    _recompute_filing(addon, company_id)
    if addon["service_level"] == "FULL_SERVICE" and addon["tax_filing_status"] == "FILED_CURRENT":
        payroll_cancel_blocked()
    addon["addon_status"] = "CANCELLED"
    db.touch(addon)
    return ok(serializers.serialize_payroll_addon(addon))


@bp.post("/payroll/employees")
def create_employee(company_id):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    else:
        active_grant(identity, company_id, ("FULL_BOOKKEEPING", "PAYROLL_ONLY"))
    sub = company_subscription(company_id)
    data = body_json()
    addon_id = req_str(data, "payroll_addon_id")
    addon = db.TABLES["PayrollAddon"].get(addon_id)
    if addon is None or sub is None or addon["subscription_id"] != sub["id"]:
        not_found("PayrollAddon not found")
    if addon["addon_status"] != "ACTIVE":
        payroll_not_active()
    legal_name = req_str(data, "legal_name")
    hire_date = parse_dt_field(data, "hire_date")
    rec = {
        "payroll_addon_id": addon["id"],
        "legal_name": legal_name,
        "hire_date": db.fmt(hire_date),
        "employment_status": "ACTIVE",
        "terminated_at": None,
    }
    db.stamp_common(rec)
    db.TABLES["PayrollEmployee"][rec["id"]] = rec
    return ok(serializers.serialize_payroll_employee(rec), status=201)


@bp.get("/payroll/employees")
def list_employees(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    sub = company_subscription(company_id)
    items = []
    if sub is not None:
        addon_ids = {p["id"] for p in db.TABLES["PayrollAddon"].values()
                     if p["subscription_id"] == sub["id"]}
        items = [e for e in db.TABLES["PayrollEmployee"].values()
                 if e["payroll_addon_id"] in addon_ids]
    items = filter_items(items, [("employment_status", "employment_status")])
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_payroll_employee(e) for e in page],
                   limit, offset, total)


@bp.get("/payroll/employees/<eid>")
def get_employee(company_id, eid):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    rec = get_or_404("PayrollEmployee", eid)
    return ok(serializers.serialize_payroll_employee(rec))


@bp.post("/payroll/employees/<eid>/terminate")
def terminate_employee(company_id, eid):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    rec = get_or_404("PayrollEmployee", eid)
    addon = db.TABLES["PayrollAddon"].get(rec["payroll_addon_id"])
    if addon is None:
        not_found("PayrollAddon not found")
    sub = db.TABLES["Subscription"].get(addon["subscription_id"])
    if sub is None or sub["company_id"] != company_id:
        not_found("Employee not in company")
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
        if identity.get("permission_level") not in ("PRIMARY_ADMIN", "COMPANY_ADMIN"):
            from errors import forbidden_role
            forbidden_role()
    else:
        active_grant(identity, company_id, ("FULL_BOOKKEEPING", "PAYROLL_ONLY"))
    if addon["addon_status"] != "ACTIVE":
        payroll_not_active()
    if sub["lifecycle_status"] not in ("ACTIVE", "REACTIVATED", "PAST_DUE"):
        invalid_state("Subscription not in a payroll-terminable state")
    if rec["employment_status"] == "TERMINATED":
        employee_terminated()
    data = body_json()
    expected = data.get("expected_payroll_addon_version")
    if expected is None:
        invalid_request("expected_payroll_addon_version is required")
    if expected != addon["version"]:
        stale_version()
    rec["employment_status"] = "TERMINATED"
    rec["terminated_at"] = db.fmt(db.now())
    db.touch(rec)
    db.touch(addon)
    return ok(serializers.serialize_payroll_employee(rec))
