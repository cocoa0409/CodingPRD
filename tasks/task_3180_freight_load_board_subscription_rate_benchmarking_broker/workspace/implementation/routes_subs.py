from datetime import timedelta

from flask import Blueprint, request

from db import db
from middleware import get_context, require_role
from response import APIError, success
from services import (
    get_broker,
    get_carrier,
    get_plan,
    get_subscription,
    lazy_suspend_past_due_subscriptions,
    new_resource,
    paginate,
    parse_limit_offset,
    require_enum,
    require_fields,
    sorted_by_created,
    sub_view,
    touch,
)
from util import ANALYTICS_DEPTHS, PLAN_CODES, iso_ms

bp = Blueprint("subscriptions", __name__)

READ_ROLES = ("PlatformAdmin", "ComplianceAnalyst", "DataOps", "BrokerAdmin", "CarrierAdmin")


def _lazy_sub(sub):
    if sub["status"] == "PAST_DUE":
        lazy_suspend_past_due_subscriptions(db)
    return sub


@bp.post("/subscription-plans")
def create_plan():
    _, role = get_context()
    require_role(role, ("PlatformAdmin",))
    body = request.get_json(silent=True) or {}
    require_fields(body, ["code", "monthly_posting_allowance", "overage_tier1_limit",
                          "overage_hard_cap", "search_daily_limit", "analytics_depth",
                          "requires_data_contribution"])
    require_enum(body["code"], PLAN_CODES, "code")
    require_enum(body["analytics_depth"], ANALYTICS_DEPTHS, "analytics_depth")
    for f in ("monthly_posting_allowance", "overage_tier1_limit", "overage_hard_cap", "search_daily_limit"):
        v = body[f]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise APIError("ERR_INVALID_REQUEST", 400, f"{f} must be a non-negative integer")
    if not isinstance(body["requires_data_contribution"], bool):
        raise APIError("ERR_INVALID_REQUEST", 400, "requires_data_contribution must be a boolean")
    for p in db.subscription_plans.values():
        if p["code"] == body["code"]:
            raise APIError("ERR_INVALID_REQUEST", 400, "Plan code must be unique")
    plan = new_resource(db, {
        "code": body["code"],
        "monthly_posting_allowance": body["monthly_posting_allowance"],
        "overage_tier1_limit": body["overage_tier1_limit"],
        "overage_hard_cap": body["overage_hard_cap"],
        "search_daily_limit": body["search_daily_limit"],
        "analytics_depth": body["analytics_depth"],
        "requires_data_contribution": body["requires_data_contribution"],
    })
    db.subscription_plans[plan["id"]] = plan
    return success(plan, 201)


@bp.get("/subscription-plans")
def list_plans():
    _, role = get_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_limit_offset()
    items = sorted_by_created(list(db.subscription_plans.values()))
    page, meta = paginate(items, limit, offset)
    return success(page, 200, meta)


@bp.post("/subscriptions")
def create_subscription():
    _, role = get_context()
    require_role(role, ("PlatformAdmin",))
    body = request.get_json(silent=True) or {}
    require_fields(body, ["plan_id"])
    plan = get_plan(db, body["plan_id"])
    broker_org_id = body.get("broker_org_id")
    carrier_org_id = body.get("carrier_org_id")
    if (broker_org_id is None) == (carrier_org_id is None):
        raise APIError("ERR_INVALID_REQUEST", 400, "Exactly one of broker_org_id or carrier_org_id is required")
    if broker_org_id is not None:
        get_broker(db, broker_org_id)
    else:
        get_carrier(db, carrier_org_id)
    sub = new_resource(db, {
        "plan_id": plan["id"],
        "broker_org_id": broker_org_id,
        "carrier_org_id": carrier_org_id,
        "status": "ACTIVE",
        "period_start": iso_ms(db.clock),
        "period_end": iso_ms(db.clock + timedelta(days=30)),
        "posts_used": 0,
        "searches_used_today": 0,
        "search_date": iso_ms(db.clock)[:10],
        "period_price_cents": 0,
    })
    db.subscriptions[sub["id"]] = sub
    return success(sub_view(db, sub), 201)


@bp.get("/subscriptions")
def list_subscriptions():
    _, role = get_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_limit_offset()
    items = list(db.subscriptions.values())
    for f in ("plan_id", "broker_org_id", "carrier_org_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s.get(f) == v]
    items = sorted_by_created(items)
    items = [sub_view(db, _lazy_sub(s)) for s in items]
    page, meta = paginate(items, limit, offset)
    return success(page, 200, meta)


@bp.get("/subscriptions/<sub_id>")
def get_subscription_route(sub_id):
    _, role = get_context()
    require_role(role, READ_ROLES)
    sub = get_subscription(db, sub_id)
    return success(sub_view(db, _lazy_sub(sub)))


@bp.post("/subscriptions/<sub_id>/change-plan")
def change_plan(sub_id):
    _, role = get_context()
    require_role(role, ("PlatformAdmin",))
    sub = get_subscription(db, sub_id)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["plan_id", "expected_subscription_version"])
    plan = get_plan(db, body["plan_id"])
    expected = body["expected_subscription_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise APIError("ERR_INVALID_REQUEST", 400, "expected_subscription_version must be an integer")
    if expected != sub["version"]:
        raise APIError("ERR_STALE_VERSION", 412, "expected_subscription_version does not match current version")
    sub["plan_id"] = plan["id"]
    touch(db, sub)
    return success(sub_view(db, _lazy_sub(sub)))


@bp.post("/subscriptions/<sub_id>/mark-past-due")
def mark_past_due(sub_id):
    _, role = get_context()
    require_role(role, ("PlatformAdmin",))
    sub = get_subscription(db, sub_id)
    if sub["status"] != "ACTIVE":
        raise APIError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Subscription is not ACTIVE")
    sub["status"] = "PAST_DUE"
    touch(db, sub)
    return success(sub_view(db, sub))


@bp.post("/subscriptions/<sub_id>/record-payment")
def record_payment(sub_id):
    _, role = get_context()
    require_role(role, ("PlatformAdmin",))
    sub = get_subscription(db, sub_id)
    _lazy_sub(sub)
    if sub["status"] not in ("PAST_DUE", "SUSPENDED"):
        raise APIError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Subscription is not PAST_DUE or SUSPENDED")
    sub["status"] = "ACTIVE"
    touch(db, sub)
    return success(sub_view(db, sub))


@bp.post("/subscriptions/<sub_id>/cancel")
def cancel_subscription(sub_id):
    _, role = get_context()
    require_role(role, ("PlatformAdmin",))
    sub = get_subscription(db, sub_id)
    _lazy_sub(sub)
    if sub["status"] not in ("ACTIVE", "PAST_DUE", "SUSPENDED"):
        raise APIError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Subscription cannot be cancelled from its current state")
    sub["status"] = "CANCELLED"
    touch(db, sub)
    return success(sub_view(db, sub))
