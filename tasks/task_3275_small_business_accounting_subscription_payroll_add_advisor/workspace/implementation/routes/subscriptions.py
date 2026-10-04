"""Subscription lifecycle: get, activate, change_plan, cancel, reactivate, resume."""
from datetime import timedelta
from flask import Blueprint
import db
import services
from auth import require_role, require_company_scope
from errors import (ok, invalid_state, not_writable, stale_version,
                    needs_primary_admin, billing_blocked, reactivation_expired,
                    not_found, invalid_request, ApiError)
from helpers import body_json, req_str, get_or_404, company_subscription
import serializers

bp = Blueprint("subscriptions", __name__, url_prefix="/api/companies/<company_id>")


def _get_sub(company_id):
    get_or_404("ClientCompany", company_id)
    sub = company_subscription(company_id)
    if sub is None:
        not_found("Subscription not found")
    return sub


def _primary_admin_only(identity):
    if identity is None or identity.get("permission_level") != "PRIMARY_ADMIN":
        needs_primary_admin()


def _issue_invoice(company, sub, period_start, period_end, status="ISSUED", advance_billing=True):
    lines = services.compute_invoice_lines(company, sub, period_start, period_end)
    inv = {
        "company_id": company["id"],
        "subscription_id": sub["id"],
        "period_start": db.fmt(period_start),
        "period_end": db.fmt(period_end),
    }
    inv.update(lines)
    inv["invoice_status"] = status
    db.stamp_common(inv)
    db.TABLES["Invoice"][inv["id"]] = inv
    if advance_billing:
        sub["next_billing_at"] = db.fmt(period_end)
        db.touch(sub)
    return inv


@bp.get("/subscription")
def get_subscription(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    sub = _get_sub(company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    sub["monthly_price_cents"] = services.monthly_price_cents(sub)
    return ok(serializers.serialize_subscription(sub))


@bp.post("/subscription/activate")
def activate_subscription(company_id):
    role, identity = require_role(["CompanyUser"])
    sub = _get_sub(company_id)
    require_company_scope(identity, company_id)
    data = body_json()
    token = req_str(data, "payment_method_token")
    _primary_admin_only(identity)
    if sub["lifecycle_status"] != "TRIAL":
        invalid_state("Subscription not in TRIAL")
    sub["payment_method_on_file"] = True
    sub["lifecycle_status"] = "ACTIVE"
    now = db.now()
    sub["anchor_day"] = min(now.day, 28)
    sub["monthly_price_cents"] = services.monthly_price_cents(sub)
    db.touch(sub)
    company = db.TABLES["ClientCompany"].get(company_id)
    # PRD: "An invoice is born DRAFT" — the activation invoice is no
    # exception: it is created in DRAFT covering the first billing period,
    # [activation, activation + 30d), and the platform operator issues it on
    # the billing date (the issue endpoint is idempotent for an invoice
    # already ISSUED, so the activation flow that moves it to ISSUED state is
    # represented by issuing it through the same path).
    period_end = now + timedelta(days=30)
    _issue_invoice(company, sub, now, period_end, status="DRAFT")
    return ok(serializers.serialize_subscription(sub))


@bp.post("/subscription/change_plan")
def change_plan(company_id):
    role, identity = require_role(["CompanyUser"])
    sub = _get_sub(company_id)
    require_company_scope(identity, company_id)
    if sub["lifecycle_status"] in ("CANCELLED_READ_ONLY", "CANCELLED_EXPIRED"):
        not_writable()
    _primary_admin_only(identity)
    data = body_json()
    plan_id = req_str(data, "plan_id")
    expected = data.get("expected_subscription_version")
    if expected is None:
        invalid_request("expected_subscription_version is required")
    plan = db.TABLES["SubscriptionPlan"].get(plan_id)
    if plan is None:
        not_found("SubscriptionPlan not found")
    if expected != sub["version"]:
        stale_version()
    sub["plan_id"] = plan_id
    sub["monthly_price_cents"] = services.monthly_price_cents(sub)
    sub["pending_upgrade_prompt"] = False
    db.touch(sub)
    return ok(serializers.serialize_subscription(sub))


def _cancel_cascade(sub, company):
    company_id = company["id"]
    now = db.now()
    sub["lifecycle_status"] = "CANCELLED_READ_ONLY"
    sub["cancelled_at"] = db.fmt(now)
    sub["read_only_expires_at"] = db.fmt(now + timedelta(days=365))
    sub["pending_upgrade_prompt"] = False
    db.touch(sub)
    for p in db.TABLES["PayrollAddon"].values():
        if p["subscription_id"] == sub["id"] and p["addon_status"] in ("ACTIVE", "PAUSED"):
            p["addon_status"] = "CANCELLED"
            db.touch(p)
    for g in db.TABLES["AccessGrant"].values():
        if g["company_id"] == company_id and g["grant_status"] == "ACTIVE":
            g["grant_status"] = "REVOKED"
            db.touch(g)
    for c in db.TABLES["BankConnection"].values():
        if c["company_id"] == company_id and \
                c["connection_status"] in ("PENDING_AUTH", "ACTIVE", "STALE"):
            c["connection_status"] = "DISCONNECTED"
            db.touch(c)
    for i in db.TABLES["AppIntegration"].values():
        if i["company_id"] == company_id and \
                i["integration_status"] in ("LINKED", "ACTIVE", "CONFLICT_PAUSED"):
            i["integration_status"] = "DISCONNECTED"
            db.touch(i)
    for r in db.TABLES["Reconciliation"].values():
        if r["company_id"] == company_id and r["recon_status"] in ("DRAFT", "IN_PROGRESS"):
            r["recon_status"] = "LOCKED"
            db.touch(r)
    for m in db.TABLES["MigrationJob"].values():
        if m["company_id"] == company_id and m["migration_status"] in ("QUEUED", "CONVERTING"):
            m["migration_status"] = "CANCELLED"
            db.touch(m)
    company["company_status"] = "READ_ONLY"
    db.touch(company)


@bp.post("/subscription/cancel")
def cancel_subscription(company_id):
    role, identity = require_role(["CompanyUser"])
    sub = _get_sub(company_id)
    require_company_scope(identity, company_id)
    _primary_admin_only(identity)
    if sub["lifecycle_status"] not in ("TRIAL", "ACTIVE", "PAST_DUE", "SUSPENDED", "REACTIVATED"):
        invalid_state("Subscription cannot be cancelled from current state")
    for t in db.TABLES["BillingTransfer"].values():
        if t["subscription_id"] == sub["id"] and \
                t["transfer_status"] in ("PENDING_CLIENT_ACCEPT", "PENDING_FIRM_ACCEPT"):
            billing_blocked()
    for r in db.TABLES["Reconciliation"].values():
        if r["company_id"] == company_id and r["recon_status"] in ("DRAFT", "IN_PROGRESS"):
            billing_blocked()
    company = db.TABLES["ClientCompany"].get(company_id)
    _cancel_cascade(sub, company)
    return ok(serializers.serialize_subscription(sub))


@bp.post("/subscription/reactivate")
def reactivate_subscription(company_id):
    role, identity = require_role(["CompanyUser"])
    sub = _get_sub(company_id)
    require_company_scope(identity, company_id)
    _primary_admin_only(identity)
    if sub["lifecycle_status"] != "CANCELLED_READ_ONLY":
        invalid_state("Subscription not in CANCELLED_READ_ONLY")
    data = body_json()
    token = req_str(data, "payment_method_token")
    now = db.now()
    exp = db.parse_iso(sub.get("read_only_expires_at"))
    if exp is not None and now >= exp:
        reactivation_expired()
    sub["payment_method_on_file"] = True
    sub["lifecycle_status"] = "REACTIVATED"
    sub["cancelled_at"] = None
    sub["read_only_expires_at"] = None
    sub["monthly_price_cents"] = services.monthly_price_cents(sub)
    db.touch(sub)
    company = db.TABLES["ClientCompany"].get(company_id)
    company["company_status"] = "ACTIVE"
    db.touch(company)
    return ok(serializers.serialize_subscription(sub))


@bp.post("/subscription/resume")
def resume_subscription(company_id):
    role, identity = require_role(["CompanyUser"])
    sub = _get_sub(company_id)
    require_company_scope(identity, company_id)
    _primary_admin_only(identity)
    if sub["lifecycle_status"] != "SUSPENDED":
        invalid_state("Subscription not SUSPENDED")
    for inv in db.TABLES["Invoice"].values():
        if inv["subscription_id"] == sub["id"] and \
                inv["invoice_status"] in ("ISSUED", "PAST_DUE"):
            billing_blocked()
    sub["lifecycle_status"] = "ACTIVE"
    sub["billing_status"] = "CURRENT"
    db.touch(sub)
    for p in db.TABLES["PayrollAddon"].values():
        if p["subscription_id"] == sub["id"] and p["addon_status"] == "PAUSED":
            p["addon_status"] = "ACTIVE"
            db.touch(p)
    return ok(serializers.serialize_subscription(sub))
