"""Plans CRUD."""
from flask import Blueprint
import db
from auth import require_role
from errors import ok, ok_list, duplicate
from helpers import body_json, req_str, req_int, get_or_404, paginate, sort_by_created
import serializers

bp = Blueprint("plans", __name__, url_prefix="/api")


@bp.post("/plans")
def create_plan():
    require_role(["PlatformAdmin"])
    data = body_json()
    plan_code = req_str(data, "plan_code")
    list_price_cents = req_int(data, "list_price_cents")
    max_seats = req_int(data, "max_seats")
    for p in db.TABLES["SubscriptionPlan"].values():
        if p["plan_code"] == plan_code:
            duplicate("plan_code already exists")
    rec = {
        "plan_code": plan_code,
        "list_price_cents": list_price_cents,
        "max_seats": max_seats,
        "feature_inventory": bool(data.get("feature_inventory", False)),
        "feature_project_profitability": bool(data.get("feature_project_profitability", False)),
        "feature_multi_currency": bool(data.get("feature_multi_currency", False)),
        "feature_bank_rules": bool(data.get("feature_bank_rules", False)),
        "plan_rank": req_int(data, "plan_rank"),
    }
    db.stamp_common(rec, kind_has_version=False)
    db.TABLES["SubscriptionPlan"][rec["id"]] = rec
    return ok(serializers.serialize_plan(rec), status=201)


@bp.get("/plans/<plan_id>")
def get_plan(plan_id):
    require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    rec = get_or_404("SubscriptionPlan", plan_id)
    return ok(serializers.serialize_plan(rec))


@bp.get("/plans")
def list_plans():
    require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    items = sort_by_created(list(db.TABLES["SubscriptionPlan"].values()))
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_plan(p) for p in page], limit, offset, total)
