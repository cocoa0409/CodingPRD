"""Companies: create, read, list."""
from datetime import timedelta
from flask import Blueprint
import db
import services
from auth import require_role, require_company_scope
from errors import ok, ok_list, invalid_request, not_found
from helpers import (body_json, req_str, get_or_404, paginate, sort_by_created,
                     enum_check, filter_items)
import serializers

bp = Blueprint("companies", __name__, url_prefix="/api")

DATA_REGIONS = ("US", "EU", "UK")


@bp.post("/companies")
def create_company():
    require_role(["PlatformAdmin"])
    data = body_json()
    legal_name = req_str(data, "legal_name")
    admin_email = req_str(data, "admin_email")
    home_country = req_str(data, "home_country")
    if len(home_country) != 2 or not home_country.isupper():
        invalid_request("home_country must be 2 uppercase letters")
    data_region = enum_check(req_str(data, "data_region"), DATA_REGIONS, "data_region")
    plan_id = req_str(data, "plan_id")
    plan = db.TABLES["SubscriptionPlan"].get(plan_id)
    if plan is None:
        not_found("SubscriptionPlan not found")
    rec = {
        "legal_name": legal_name,
        "admin_email": admin_email,
        "home_country": home_country,
        "data_region": data_region,
        "company_status": "ACTIVE",
        "primary_admin_user_id": None,
    }
    db.stamp_common(rec)
    db.TABLES["ClientCompany"][rec["id"]] = rec

    # Auto-provision the TRIAL subscription.
    now = db.now()
    sub = {
        "company_id": rec["id"],
        "plan_id": plan_id,
        "billing_owner": "CLIENT",
        "billing_firm_id": None,
        "lifecycle_status": "TRIAL",
        "billing_status": "CURRENT",
        "anchor_day": None,
        "started_at": db.fmt(now),
        "trial_ends_at": db.fmt(now + timedelta(days=30)),
        "cancelled_at": None,
        "read_only_expires_at": None,
        "monthly_price_cents": plan["list_price_cents"],
        "pending_upgrade_prompt": False,
        "payment_method_on_file": False,
    }
    db.stamp_common(sub)
    db.TABLES["Subscription"][sub["id"]] = sub
    return ok(serializers.serialize_company(rec), status=201)


@bp.get("/companies/<company_id>")
def get_company(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    rec = get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    return ok(serializers.serialize_company(rec))


@bp.get("/companies")
def list_companies():
    require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    items = list(db.TABLES["ClientCompany"].values())
    items = filter_items(items, [("primary_admin_user_id", "primary_admin_user_id")])
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_company(c) for c in page], limit, offset, total)
