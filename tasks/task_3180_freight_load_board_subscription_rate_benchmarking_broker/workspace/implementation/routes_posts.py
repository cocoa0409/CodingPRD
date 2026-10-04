from datetime import timedelta

from flask import Blueprint, request

from db import db
from middleware import get_context, require_role
from response import APIError, success
from services import (
    check_org_active,
    check_safety_gate,
    find_active_subscription,
    get_broker,
    get_carrier,
    get_load,
    get_truck,
    lazy_expire_load,
    lazy_expire_truck,
    new_resource,
    paginate,
    parse_limit_offset,
    require_active_subscription,
    require_enum,
    require_fields,
    require_positive_int,
    sorted_by_created,
    touch,
)
from util import EQUIPMENT_TYPES, REFUND_WINDOW_HOURS, iso_ms, parse_dt

bp = Blueprint("posts", __name__)

READ_ROLES = ("PlatformAdmin", "ComplianceAnalyst", "DataOps", "BrokerAdmin", "CarrierAdmin")


def load_view(load):
    lazy_expire_load(db, load)
    broker = db.broker_orgs.get(load["broker_org_id"])
    load["broker_credit_badge"] = broker["credit_badge"] if broker else None
    status = None
    from services import _verified_authority, compute_insurance, lazy_expire_verification
    best = None
    for v in db.authority_verifications.values():
        if v.get("broker_org_id") != load["broker_org_id"]:
            continue
        compute_insurance(db, v)
        lazy_expire_verification(db, v)
        if best is None or v["created_at"] > best["created_at"]:
            best = v
    load["broker_authority_status"] = best["status"] if best else None
    return load


def truck_view(truck):
    lazy_expire_truck(db, truck)
    return truck


def _check_post_gate(org, is_broker):
    check_org_active(org)
    sub = require_active_subscription(
        db,
        broker_org_id=org["id"] if is_broker else None,
        carrier_org_id=None if is_broker else org["id"],
    )
    check_safety_gate(
        db,
        broker_org_id=org["id"] if is_broker else None,
        carrier_org_id=None if is_broker else org["id"],
    )
    return sub


def _check_post_quota(sub):
    plan = db.subscription_plans[sub["plan_id"]]
    hard_cap = plan["monthly_posting_allowance"] + plan["overage_hard_cap"]
    if sub["posts_used"] >= hard_cap:
        raise APIError("ERR_POSTING_QUOTA_EXCEEDED", 402, "Posting hard cap reached")


@bp.post("/load-posts")
def create_load():
    user_id, role = get_context()
    require_role(role, ("BrokerAdmin",))
    body = request.get_json(silent=True) or {}
    require_fields(body, ["origin", "destination", "equipment_type",
                          "pickup_window_start", "pickup_window_end", "rate_offer_cents"])
    require_enum(body["equipment_type"], EQUIPMENT_TYPES, "equipment_type")
    require_positive_int(body["rate_offer_cents"], "rate_offer_cents")
    broker = get_broker(db, user_id)
    sub = _check_post_gate(broker, True)
    start = parse_dt(body["pickup_window_start"])
    end = parse_dt(body["pickup_window_end"])
    if start is None or end is None or not (start < end):
        raise APIError("ERR_INVALID_REQUEST", 400, "pickup_window_start must be strictly before pickup_window_end")
    _check_post_quota(sub)
    load = new_resource(db, {
        "broker_org_id": broker["id"],
        "origin": body["origin"],
        "destination": body["destination"],
        "equipment_type": body["equipment_type"],
        "pickup_window_start": body["pickup_window_start"],
        "pickup_window_end": body["pickup_window_end"],
        "rate_offer_cents": body["rate_offer_cents"],
        "status": "OPEN",
        "visibility": "LISTED",
        "broker_credit_badge": None,
        "broker_authority_status": None,
    })
    db.load_posts[load["id"]] = load
    sub["posts_used"] += 1
    touch(db, sub)
    return success(load_view(load), 201)


@bp.get("/load-posts")
def list_loads():
    user_id, role = get_context()
    require_role(role, READ_ROLES)
    if role == "CarrierAdmin":
        carrier = get_carrier(db, user_id)
        check_org_active(carrier)
        sub = require_active_subscription(db, carrier_org_id=carrier["id"])
        plan = db.subscription_plans[sub["plan_id"]]
        today = iso_ms(db.clock)[:10]
        if sub.get("search_date") != today:
            sub["searches_used_today"] = 0
            sub["search_date"] = today
        if sub["searches_used_today"] >= plan["search_daily_limit"]:
            raise APIError("ERR_SEARCH_LIMIT_EXCEEDED", 402, "Daily search limit reached")
        sub["searches_used_today"] += 1
        touch(db, sub)
    limit, offset = parse_limit_offset()
    items = [load_view(l) for l in db.load_posts.values()]
    for f in ("origin", "destination", "equipment_type", "status", "broker_org_id"):
        v = request.args.get(f)
        if v is not None:
            items = [l for l in items if l.get(f) == v]
    pickup_on = request.args.get("pickup_on")
    if pickup_on is not None:
        d = parse_dt(pickup_on)
        if d is None:
            raise APIError("ERR_INVALID_REQUEST", 400, "pickup_on must be a valid datetime")
        items = [l for l in items
                 if parse_dt(l["pickup_window_start"]) is not None
                 and parse_dt(l["pickup_window_end"]) is not None
                 and parse_dt(l["pickup_window_start"]) <= d < parse_dt(l["pickup_window_end"])]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, 200, meta)


@bp.get("/load-posts/<load_id>")
def get_load_route(load_id):
    _, role = get_context()
    require_role(role, READ_ROLES)
    return success(load_view(get_load(db, load_id)))


@bp.post("/load-posts/<load_id>/withdraw")
def withdraw_load(load_id):
    user_id, role = get_context()
    require_role(role, ("BrokerAdmin",))
    load = get_load(db, load_id)
    broker = get_broker(db, user_id)
    check_org_active(broker)
    if load["broker_org_id"] != broker["id"]:
        raise APIError("ERR_NOT_RESOURCE_OWNER", 403, "Acting broker does not own this load post")
    lazy_expire_load(db, load)
    if load["status"] != "OPEN":
        raise APIError("ERR_LOAD_POST_NOT_OPEN", 409, "Load post is not OPEN")
    load["status"] = "WITHDRAWN"
    touch(db, load)
    created = parse_dt(load["created_at"])
    if created is not None and db.clock - created <= timedelta(hours=REFUND_WINDOW_HOURS):
        sub = find_active_subscription(db, broker_org_id=broker["id"])
        if sub is not None and sub["posts_used"] > 0:
            sub["posts_used"] -= 1
            touch(db, sub)
    return success(load_view(load))


@bp.post("/truck-posts")
def create_truck():
    user_id, role = get_context()
    require_role(role, ("CarrierAdmin",))
    body = request.get_json(silent=True) or {}
    require_fields(body, ["origin", "destination", "equipment_type", "available_from", "available_until"])
    require_enum(body["equipment_type"], EQUIPMENT_TYPES, "equipment_type")
    carrier = get_carrier(db, user_id)
    sub = _check_post_gate(carrier, False)
    af = parse_dt(body["available_from"])
    au = parse_dt(body["available_until"])
    if af is None or au is None or not (af < au):
        raise APIError("ERR_INVALID_REQUEST", 400, "available_from must be strictly before available_until")
    for t in db.truck_posts.values():
        if t["carrier_org_id"] != carrier["id"] or t["status"] != "AVAILABLE":
            continue
        eaf = parse_dt(t["available_from"])
        eau = parse_dt(t["available_until"])
        if eaf is None or eau is None:
            continue
        if af < eau and au > eaf:
            raise APIError("ERR_TRUCK_WINDOW_OVERLAP", 409, "Truck availability window overlaps an existing AVAILABLE truck")
    _check_post_quota(sub)
    truck = new_resource(db, {
        "carrier_org_id": carrier["id"],
        "origin": body["origin"],
        "destination": body["destination"],
        "equipment_type": body["equipment_type"],
        "available_from": body["available_from"],
        "available_until": body["available_until"],
        "status": "AVAILABLE",
    })
    db.truck_posts[truck["id"]] = truck
    sub["posts_used"] += 1
    touch(db, sub)
    return success(truck_view(truck), 201)


@bp.get("/truck-posts")
def list_trucks():
    _, role = get_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_limit_offset()
    items = [truck_view(t) for t in db.truck_posts.values()]
    for f in ("carrier_org_id", "origin", "destination", "equipment_type", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [t for t in items if t.get(f) == v]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, 200, meta)


@bp.get("/truck-posts/<truck_id>")
def get_truck_route(truck_id):
    _, role = get_context()
    require_role(role, READ_ROLES)
    return success(truck_view(get_truck(db, truck_id)))


@bp.post("/truck-posts/<truck_id>/withdraw")
def withdraw_truck(truck_id):
    user_id, role = get_context()
    require_role(role, ("CarrierAdmin",))
    truck = get_truck(db, truck_id)
    carrier = get_carrier(db, user_id)
    check_org_active(carrier)
    if truck["carrier_org_id"] != carrier["id"]:
        raise APIError("ERR_NOT_RESOURCE_OWNER", 403, "Acting carrier does not own this truck post")
    lazy_expire_truck(db, truck)
    if truck["status"] != "AVAILABLE":
        raise APIError("ERR_TRUCK_POST_NOT_AVAILABLE", 409, "Truck post is not AVAILABLE")
    truck["status"] = "WITHDRAWN"
    touch(db, truck)
    created = parse_dt(truck["created_at"])
    if created is not None and db.clock - created <= timedelta(hours=REFUND_WINDOW_HOURS):
        sub = find_active_subscription(db, carrier_org_id=carrier["id"])
        if sub is not None and sub["posts_used"] > 0:
            sub["posts_used"] -= 1
            touch(db, sub)
    return success(truck_view(truck))
