"""HTTP routes for the Franchise Supply Chain API."""
import uuid
from datetime import timedelta
from functools import wraps

from flask import request

from db import db
from errors import ApiError, ok, parse_ts, format_ts, week_of
import services as S

READ_ROLES = ("Any", "SupplyChainAdmin", "StoreManager", "RouteCoordinator")


# ---------------------------------------------------------------------------
# Auth & validation helpers
# ---------------------------------------------------------------------------

def _auth(allowed):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in S.VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       "X-User-ID and X-User-Role headers must be present and valid", 400)
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                       "Caller role is valid but not allowed for this endpoint", 403)
    return user_id, role


def require(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = _auth(roles)
            return fn(user_id, role, *args, **kwargs)
        return wrapper
    return deco


def body():
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body", 400)
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object", 400)
    return data


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} is required and must be a non-empty string", 400)
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} is required and must be an integer", 400)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be >= {minimum}", 400)
    return v


def req_num(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} is required and must be a number", 400)
    return v


def req_enum(data, field, values):
    v = data.get(field)
    if v not in values:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(values)}", 400)
    return v


def req_ts(data, field):
    if field not in data:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} is required", 400)
    return parse_ts(data[field], field)


def pagination_params():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "limit and offset must be integers", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be 1..100 and offset >= 0", 400)
    return limit, offset


def list_response(records, serializer):
    limit, offset = pagination_params()
    records = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(records)
    page = records[offset:offset + limit]
    return ok([serializer(r) for r in page], pagination={
        "limit": limit, "offset": offset,
        "total_count": total, "has_more": offset + limit < total,
    })


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Scoped getters (404s left to right)
# ---------------------------------------------------------------------------

def get_center(center_id):
    c = db.centers.get(center_id)
    if c is None:
        raise ApiError("ERR_CENTER_NOT_FOUND", "SupplyCenter with given ID does not exist", 404)
    return c


def get_store(center_id, store_id):
    get_center(center_id)
    s = db.stores.get(store_id)
    if s is None or s["center_id"] != center_id:
        raise ApiError("ERR_STORE_NOT_FOUND", "Store with given ID does not exist in this center", 404)
    return s


def get_product(center_id, product_id):
    get_center(center_id)
    p = db.products.get(product_id)
    if p is None or p["center_id"] != center_id:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", "Product with given ID does not exist in this center", 404)
    return p


def get_order(center_id, order_id):
    get_center(center_id)
    o = db.orders.get(order_id)
    if o is None or o["center_id"] != center_id:
        raise ApiError("ERR_ORDER_NOT_FOUND", "PurchaseOrder with given ID does not exist", 404)
    return o


def get_scoped_order(center_id, store_id, order_id):
    get_store(center_id, store_id)
    o = db.orders.get(order_id)
    if o is None or o["center_id"] != center_id:
        raise ApiError("ERR_ORDER_NOT_FOUND", "PurchaseOrder with given ID does not exist", 404)
    return o


def get_line(center_id, order_id, line_id):
    get_order(center_id, order_id)
    l = db.lines.get(line_id)
    if l is None or l["order_id"] != order_id:
        raise ApiError("ERR_ORDER_NOT_FOUND", "OrderLine with given ID does not exist on this order", 404)
    return l


def get_route(center_id, route_id):
    get_center(center_id)
    r = db.routes.get(route_id)
    if r is None or r["center_id"] != center_id:
        raise ApiError("ERR_ROUTE_NOT_FOUND", "DeliveryRoute with given ID does not exist", 404)
    return r


def get_stop(center_id, route_id, stop_id):
    get_route(center_id, route_id)
    s = db.stops.get(stop_id)
    if s is None or s["route_id"] != route_id:
        raise ApiError("ERR_ROUTE_NOT_FOUND", "DeliveryStop with given ID does not exist on this route", 404)
    return s


def get_price_book(center_id, pb_id):
    get_center(center_id)
    p = db.price_books.get(pb_id)
    if p is None or p["center_id"] != center_id:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", "PriceBook with given ID does not exist in this center", 404)
    return p


def get_promotion(center_id, promo_id):
    get_center(center_id)
    p = db.promotions.get(promo_id)
    if p is None or p["center_id"] != center_id:
        raise ApiError("ERR_PROMOTION_NOT_FOUND", "PromotionEvent with given ID does not exist", 404)
    return p


def get_pool(center_id, pool_id):
    get_center(center_id)
    p = db.pools.get(pool_id)
    if p is None or p["center_id"] != center_id:
        raise ApiError("ERR_POOL_NOT_FOUND", "RebatePool with given ID does not exist", 404)
    return p


def get_ledger(center_id, ledger_id):
    get_center(center_id)
    e = db.ledgers.get(ledger_id)
    if e is None:
        raise ApiError("ERR_LEDGER_NOT_FOUND", "RebateLedger with given ID does not exist", 404)
    pool = db.pools.get(e["pool_id"])
    if pool is None or pool["center_id"] != center_id:
        raise ApiError("ERR_LEDGER_NOT_FOUND", "RebateLedger with given ID does not exist", 404)
    return e


def get_agreement(center_id, agreement_id):
    get_center(center_id)
    a = db.agreements.get(agreement_id)
    if a is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", "ComplianceAgreement with given ID does not exist", 404)
    store = db.stores.get(a["store_id"])
    if store is None or store["center_id"] != center_id:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", "ComplianceAgreement with given ID does not exist", 404)
    return a


def get_scoped_agreement(center_id, store_id, agreement_id):
    get_store(center_id, store_id)
    a = db.agreements.get(agreement_id)
    if a is None or a["store_id"] != store_id:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", "ComplianceAgreement with given ID does not exist", 404)
    return a


def get_plan(center_id, plan_id):
    get_center(center_id)
    p = db.plans.get(plan_id)
    if p is None or p["center_id"] != center_id:
        raise ApiError("ERR_PLAN_NOT_FOUND", "CapacityPlan with given ID does not exist", 404)
    return p


def get_variance(center_id, variance_id):
    get_center(center_id)
    v = db.variances.get(variance_id)
    if v is None:
        raise ApiError("ERR_VARIANCE_NOT_FOUND", "FoodCostVariance with given ID does not exist", 404)
    store = db.stores.get(v["store_id"])
    if store is None or store["center_id"] != center_id:
        raise ApiError("ERR_VARIANCE_NOT_FOUND", "FoodCostVariance with given ID does not exist", 404)
    return v


def get_scoped_variance(center_id, store_id, variance_id):
    get_store(center_id, store_id)
    v = db.variances.get(variance_id)
    if v is None or v["store_id"] != store_id:
        raise ApiError("ERR_VARIANCE_NOT_FOUND", "FoodCostVariance with given ID does not exist", 404)
    return v


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _base(rec):
    return {
        "id": rec["id"],
        "created_at": format_ts(rec["created_at"]),
        "updated_at": format_ts(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_center(c):
    return {**_base(c),
            "center_code": c["center_code"],
            "display_name": c["display_name"],
            "base_weekly_capacity_units": c["base_weekly_capacity_units"],
            "surge_capacity_multiplier": c["surge_capacity_multiplier"],
            "ops_run_index": c["ops_run_index"],
            "rebate_pool_balance_cents": c["rebate_pool_balance_cents"],
            "rebate_pool_locked_cents": c["rebate_pool_locked_cents"],
            "posture": c["posture"],
            "status": c["status"]}


def ser_store(s):
    return {**_base(s),
            "center_id": s["center_id"],
            "store_number": s["store_number"],
            "operator_name": s["operator_name"],
            "compliance_tier": s["compliance_tier"],
            "exclusive_purchase_pct": s["exclusive_purchase_pct"],
            "rebate_eligibility_status": s["rebate_eligibility_status"],
            "outstanding_balance_cents": s["outstanding_balance_cents"],
            "credit_limit_cents": s["credit_limit_cents"],
            "status": s["status"]}


def ser_product(p):
    return {**_base(p),
            "center_id": p["center_id"],
            "sku": p["sku"],
            "name": p["name"],
            "category": p["category"],
            "base_cost_cents_per_unit": p["base_cost_cents_per_unit"],
            "shelf_life_days": p["shelf_life_days"],
            "is_promotion_eligible": p["is_promotion_eligible"],
            "status": p["status"]}


def ser_price_book(p):
    return {**_base(p),
            "center_id": p["center_id"],
            "product_id": p["product_id"],
            "store_tier": p["store_tier"],
            "markup_pct": p["markup_pct"],
            "min_quantity": p["min_quantity"],
            "effective_from": format_ts(p["effective_from"]),
            "effective_until": format_ts(p["effective_until"]),
            "status": p["status"]}


def ser_route(r):
    return {**_base(r),
            "center_id": r["center_id"],
            "route_code": r["route_code"],
            "day_of_week": r["day_of_week"],
            "truck_capacity_units": r["truck_capacity_units"],
            "assigned_store_ids": r["assigned_store_ids"],
            "status": r["status"],
            "dispatched_at": format_ts(r["dispatched_at"]) if r["dispatched_at"] else None}


def ser_stop(s):
    return {**_base(s),
            "route_id": s["route_id"],
            "store_id": s["store_id"],
            "sequence_number": s["sequence_number"],
            "estimated_arrival": format_ts(s["estimated_arrival"]),
            "actual_arrival": format_ts(s["actual_arrival"]) if s["actual_arrival"] else None,
            "status": s["status"]}


def ser_order(o):
    return {**_base(o),
            "store_id": o["store_id"],
            "center_id": o["center_id"],
            "week_start_date": format_ts(o["week_start_date"]),
            "status": o["status"],
            "subtotal_cents": o["subtotal_cents"],
            "markup_cents": o["markup_cents"],
            "delivery_fee_cents": o["delivery_fee_cents"],
            "total_cents": o["total_cents"],
            "theoretical_usage_cents": o["theoretical_usage_cents"],
            "actual_usage_cents": o["actual_usage_cents"],
            "food_cost_variance_pct": o["food_cost_variance_pct"],
            "promotion_id": o["promotion_id"],
            "route_id": o["route_id"]}


def ser_line(l):
    return {**_base(l),
            "order_id": l["order_id"],
            "product_id": l["product_id"],
            "quantity": l["quantity"],
            "unit_price_cents": l["unit_price_cents"],
            "extended_price_cents": l["extended_price_cents"],
            "theoretical_usage_cents": l["theoretical_usage_cents"],
            "status": l["status"]}


def ser_promotion(p):
    return {**_base(p),
            "center_id": p["center_id"],
            "promotion_code": p["promotion_code"],
            "start_date": format_ts(p["start_date"]),
            "end_date": format_ts(p["end_date"]),
            "surge_multiplier": p["surge_multiplier"],
            "affected_product_ids": p["affected_product_ids"],
            "capacity_reserved_units": p["capacity_reserved_units"],
            "status": p["status"]}


def ser_pool(p):
    return {**_base(p),
            "center_id": p["center_id"],
            "quarter": p["quarter"],
            "pool_total_cents": p["pool_total_cents"],
            "distributed_cents": p["distributed_cents"],
            "holdback_cents": p["holdback_cents"],
            "status": p["status"]}


def ser_ledger(e):
    return {**_base(e),
            "pool_id": e["pool_id"],
            "store_id": e["store_id"],
            "entry_type": e["entry_type"],
            "amount_cents": e["amount_cents"],
            "running_balance_cents": e["running_balance_cents"],
            "source_order_id": e["source_order_id"],
            "settlement_date": format_ts(e["settlement_date"]) if e["settlement_date"] else None,
            "status": e["status"]}


def ser_agreement(a):
    return {**_base(a),
            "store_id": a["store_id"],
            "agreement_type": a["agreement_type"],
            "start_date": format_ts(a["start_date"]),
            "end_date": format_ts(a["end_date"]) if a["end_date"] else None,
            "exclusive_purchase_threshold": a["exclusive_purchase_threshold"],
            "status": a["status"],
            "breach_count": a["breach_count"],
            "cure_deadline": format_ts(a["cure_deadline"]) if a["cure_deadline"] else None}


def ser_plan(p):
    return {**_base(p),
            "center_id": p["center_id"],
            "week_start_date": format_ts(p["week_start_date"]),
            "baseline_units": p["baseline_units"],
            "surge_units": p["surge_units"],
            "allocated_units": p["allocated_units"],
            "available_units": p["available_units"],
            "status": p["status"]}


def ser_variance(v):
    return {**_base(v),
            "store_id": v["store_id"],
            "week_start_date": format_ts(v["week_start_date"]),
            "theoretical_cents": v["theoretical_cents"],
            "actual_cents": v["actual_cents"],
            "variance_cents": v["variance_cents"],
            "variance_pct": v["variance_pct"],
            "severity": v["severity"],
            "status": v["status"]}


# ---------------------------------------------------------------------------
# Ownership / state helpers
# ---------------------------------------------------------------------------

def check_store_ownership(store_id, user_id):
    if store_id != user_id:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                       "StoreManager may only act on behalf of their own store", 403)


def center_operational(center):
    if not (center["status"] == "ACTIVE" and center["posture"] in ("ACTIVE", "SURGE_MODE")):
        raise ApiError("ERR_CENTER_NOT_ACTIVE", "SupplyCenter is not ACTIVE or SURGE_MODE", 409)


def expect_state(rec, allowed, message="Resource is in wrong state for requested operation"):
    if rec["status"] not in allowed:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", message, 409)


# ---------------------------------------------------------------------------
# SupplyCenter endpoints
# ---------------------------------------------------------------------------

def create_center(user_id, role):
    d = body()
    center_code = req_str(d, "center_code")
    display_name = req_str(d, "display_name")
    capacity = req_int(d, "base_weekly_capacity_units")
    multiplier = d.get("surge_capacity_multiplier", 1.0)
    if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "surge_capacity_multiplier must be a number", 400)
    if any(c["center_code"] == center_code for c in db.centers.values()):
        raise ApiError("ERR_INVALID_REQUEST", "center_code must be unique", 400)
    rec = S.new_record()
    rec.update({
        "id": new_id(),
        "center_code": center_code,
        "display_name": display_name,
        "base_weekly_capacity_units": capacity,
        "surge_capacity_multiplier": multiplier,
        "ops_run_index": 0,
        "rebate_pool_balance_cents": 0,
        "rebate_pool_locked_cents": 0,
        "posture": "ACTIVE",
        "status": "DRAFT",
    })
    db.centers[rec["id"]] = rec
    return ok(ser_center(rec), 201)


def get_center_ep(user_id, role, center_id):
    return ok(ser_center(get_center(center_id)))


def activate_center(user_id, role, center_id):
    center = get_center(center_id)
    expect_state(center, ("DRAFT", "SUSPENDED"))
    if center["status"] == "DRAFT":
        if center["base_weekly_capacity_units"] <= 0:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "base_weekly_capacity_units must be greater than zero", 409)
        if not any(p["center_id"] == center["id"] and p["status"] == "ACTIVE"
                   for p in db.products.values()):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "At least one Product with status=ACTIVE is required", 409)
        center["posture"] = "ACTIVE"
    else:
        S.recompute_posture(center)
    center["status"] = "ACTIVE"
    S.touch(center)
    return ok(ser_center(center))


def suspend_center(user_id, role, center_id):
    body()
    center = get_center(center_id)
    expect_state(center, ("ACTIVE",))
    center["status"] = "SUSPENDED"
    center["posture"] = "SUSPENDED"
    S.touch(center)
    for r in db.routes.values():
        if r["center_id"] == center["id"] and r["status"] == "PLANNED":
            r["status"] = "CANCELLED"
            S.touch(r)
            for o in db.orders.values():
                if o.get("route_id") == r["id"] and o["status"] == "CONFIRMED":
                    o["status"] = "SUBMITTED"
                    o["route_id"] = None
                    S.touch(o)
    for o in db.orders.values():
        if o["center_id"] == center["id"] and o["status"] in ("DRAFT", "SUBMITTED"):
            o["status"] = "REJECTED"
            S.touch(o)
    return ok(ser_center(center))


def decommission_center(user_id, role, center_id):
    center = get_center(center_id)
    expect_state(center, ("ACTIVE",))
    if any(s["center_id"] == center["id"] and s["status"] == "ACTIVE" for s in db.stores.values()):
        raise ApiError("ERR_CENTER_HAS_ACTIVE_STORES",
                       "Cannot decommission center with ACTIVE stores", 409)
    if any(o["center_id"] == center["id"] and o["status"] in ("SUBMITTED", "CONFIRMED", "LOADED", "DELIVERED")
           for o in db.orders.values()):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Center has purchase orders in flight", 409)
    if any(r["center_id"] == center["id"] and r["status"] in ("PLANNED", "DISPATCHED")
           for r in db.routes.values()):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Center has routes in PLANNED or DISPATCHED", 409)
    if any(p["center_id"] == center["id"] and p["status"] != "CLOSED" for p in db.pools.values()):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "All RebatePools must be CLOSED", 409)
    center["status"] = "DECOMMISSIONED"
    S.touch(center)
    for s in db.stores.values():
        if s["center_id"] == center["id"] and s["status"] != "TERMINATED":
            s["status"] = "TERMINATED"
            S.touch(s)
            for a in db.agreements.values():
                if a["store_id"] == s["id"] and a["status"] not in ("TERMINATED",):
                    a["status"] = "TERMINATED"
                    S.touch(a)
    return ok(ser_center(center))


def run_ops(user_id, role, center_id):
    center = get_center(center_id)
    S.run_ops_checkpoint(center)
    return ok(ser_center(center))


# ---------------------------------------------------------------------------
# Store endpoints
# ---------------------------------------------------------------------------

def create_store(user_id, role, center_id):
    center = get_center(center_id)
    d = body()
    store_number = req_str(d, "store_number")
    operator_name = req_str(d, "operator_name")
    credit_limit = req_int(d, "credit_limit_cents")
    if any(s["center_id"] == center["id"] and s["store_number"] == store_number
           for s in db.stores.values()):
        raise ApiError("ERR_INVALID_REQUEST", "store_number must be unique within center", 400)
    rec = S.new_record()
    rec.update({
        "id": new_id(),
        "center_id": center["id"],
        "store_number": store_number,
        "operator_name": operator_name,
        "compliance_tier": "FULL_COMPLIANCE",
        "exclusive_purchase_pct": 0.0,
        "rebate_eligibility_status": "ELIGIBLE",
        "outstanding_balance_cents": 0,
        "credit_limit_cents": credit_limit,
        "status": "ONBOARDING",
    })
    db.stores[rec["id"]] = rec
    return ok(ser_store(rec), 201)


def get_store_ep(user_id, role, center_id, store_id):
    return ok(ser_store(get_store(center_id, store_id)))


def list_stores_scoped(user_id, role, center_id):
    get_center(center_id)
    records = [s for s in db.stores.values() if s["center_id"] == center_id]
    return _filter_stores(records)


def _filter_stores(records):
    status = request.args.get("status")
    tier = request.args.get("compliance_tier")
    center_id = request.args.get("center_id")
    if status:
        records = [s for s in records if s["status"] == status]
    if tier:
        records = [s for s in records if s["compliance_tier"] == tier]
    if center_id:
        records = [s for s in records if s["center_id"] == center_id]
    return list_response(records, ser_store)


def activate_store(user_id, role, center_id, store_id):
    store = get_store(center_id, store_id)
    center = db.centers[center_id]
    expect_state(store, ("ONBOARDING", "SUSPENDED"))
    if store["status"] == "ONBOARDING":
        center_operational(center)
        if not any(a["store_id"] == store["id"] and a["status"] == "ACTIVE"
                   for a in db.agreements.values()):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Store must hold at least one ACTIVE compliance agreement", 409)
    else:
        if store["outstanding_balance_cents"] > store["credit_limit_cents"]:
            raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED",
                           "Store outstanding balance exceeds credit limit", 409)
    store["status"] = "ACTIVE"
    S.touch(store)
    return ok(ser_store(store))


def suspend_store(user_id, role, center_id, store_id):
    body()
    store = get_store(center_id, store_id)
    expect_state(store, ("ACTIVE",))
    S.suspend_store_cascade(store)
    return ok(ser_store(store))


def terminate_store(user_id, role, center_id, store_id):
    store = get_store(center_id, store_id)
    expect_state(store, ("ACTIVE",))
    if any(o["store_id"] == store["id"] and o["status"] in ("SUBMITTED", "CONFIRMED", "LOADED", "DELIVERED")
           for o in db.orders.values()):
        raise ApiError("ERR_STORE_HAS_ACTIVE_ORDERS",
                       "Cannot terminate store with non-terminal purchase orders", 409)
    if store["outstanding_balance_cents"] != 0:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Store outstanding balance must be zero", 409)
    store["status"] = "TERMINATED"
    S.touch(store)
    for a in db.agreements.values():
        if a["store_id"] == store["id"] and a["status"] != "TERMINATED":
            a["status"] = "TERMINATED"
            S.touch(a)
    return ok(ser_store(store))


# ---------------------------------------------------------------------------
# Product endpoints
# ---------------------------------------------------------------------------

def create_product(user_id, role, center_id):
    center = get_center(center_id)
    d = body()
    sku = req_str(d, "sku")
    name = req_str(d, "name")
    category = req_enum(d, "category", {"DOUGH", "FOOD_INGREDIENT", "EQUIPMENT", "SMALLWARES", "PACKAGING"})
    base_cost = req_int(d, "base_cost_cents_per_unit")
    shelf_life = d.get("shelf_life_days")
    if shelf_life is not None and (isinstance(shelf_life, bool) or not isinstance(shelf_life, int)):
        raise ApiError("ERR_INVALID_REQUEST", "shelf_life_days must be an integer or null", 400)
    promo_eligible = d.get("is_promotion_eligible", False)
    if not isinstance(promo_eligible, bool):
        raise ApiError("ERR_INVALID_REQUEST", "is_promotion_eligible must be a boolean", 400)
    if any(p["center_id"] == center["id"] and p["sku"] == sku for p in db.products.values()):
        raise ApiError("ERR_INVALID_REQUEST", "sku must be unique within center", 400)
    rec = S.new_record()
    rec.update({
        "id": new_id(),
        "center_id": center["id"],
        "sku": sku,
        "name": name,
        "category": category,
        "base_cost_cents_per_unit": base_cost,
        "shelf_life_days": shelf_life,
        "is_promotion_eligible": promo_eligible,
        "status": "ACTIVE",
    })
    db.products[rec["id"]] = rec
    return ok(ser_product(rec), 201)


def get_product_ep(user_id, role, center_id, product_id):
    return ok(ser_product(get_product(center_id, product_id)))


def list_products_scoped(user_id, role, center_id):
    get_center(center_id)
    records = [p for p in db.products.values() if p["center_id"] == center_id]
    return _filter_products(records)


def _filter_products(records):
    category = request.args.get("category")
    status = request.args.get("status")
    center_id = request.args.get("center_id")
    if category:
        records = [p for p in records if p["category"] == category]
    if status:
        records = [p for p in records if p["status"] == status]
    if center_id:
        records = [p for p in records if p["center_id"] == center_id]
    return list_response(records, ser_product)


def discontinue_product(user_id, role, center_id, product_id):
    product = get_product(center_id, product_id)
    expect_state(product, ("ACTIVE",))
    product["status"] = "DISCONTINUED"
    S.touch(product)
    return ok(ser_product(product))


def recall_product(user_id, role, center_id, product_id):
    body()
    product = get_product(center_id, product_id)
    expect_state(product, ("ACTIVE", "DISCONTINUED"))
    product["status"] = "RECALLED"
    S.touch(product)
    return ok(ser_product(product))


# ---------------------------------------------------------------------------
# PriceBook endpoints
# ---------------------------------------------------------------------------

def create_price_book(user_id, role, center_id):
    center = get_center(center_id)
    d = body()
    product_id = d.get("product_id")
    product = db.products.get(product_id) if isinstance(product_id, str) else None
    if product is None or product["center_id"] != center_id:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", "Product with given ID does not exist in this center", 404)
    store_tier = req_enum(d, "store_tier", {"STANDARD", "VOLUME_DISCOUNT", "PREMIUM"})
    markup = req_num(d, "markup_pct")
    min_qty = d.get("min_quantity", 1)
    if isinstance(min_qty, bool) or not isinstance(min_qty, int) or min_qty < 1:
        raise ApiError("ERR_INVALID_REQUEST", "min_quantity must be an integer >= 1", 400)
    effective_from = req_ts(d, "effective_from")
    effective_until = req_ts(d, "effective_until")
    if "expected_center_version" not in d:
        raise ApiError("ERR_INVALID_REQUEST", "expected_center_version is required", 400)
    expected = d["expected_center_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", "expected_center_version must be an integer", 400)
    if expected != center["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_center_version does not match current center version", 412)
    if product["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCT_UNAVAILABLE", "Product is DISCONTINUED or RECALLED", 409)
    for pb in db.price_books.values():
        if (pb["center_id"] == center_id and pb["product_id"] == product_id
                and pb["store_tier"] == store_tier and pb["status"] == "ACTIVE"
                and effective_from < pb["effective_until"] and pb["effective_from"] < effective_until):
            raise ApiError("ERR_PRICE_BOOK_OVERLAP",
                           "Price book effective window overlaps with existing ACTIVE book", 409)
    if effective_from >= effective_until:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "effective_from must be strictly before effective_until", 400)
    rec = S.new_record()
    rec.update({
        "id": new_id(),
        "center_id": center_id,
        "product_id": product_id,
        "store_tier": store_tier,
        "markup_pct": markup,
        "min_quantity": min_qty,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "status": "ACTIVE",
    })
    db.price_books[rec["id"]] = rec
    S.touch(center)
    return ok(ser_price_book(rec), 201)


def get_price_book_ep(user_id, role, center_id, price_book_id):
    return ok(ser_price_book(get_price_book(center_id, price_book_id)))


def list_price_books_scoped(user_id, role, center_id):
    get_center(center_id)
    records = [p for p in db.price_books.values() if p["center_id"] == center_id]
    return _filter_price_books(records)


def _filter_price_books(records):
    product_id = request.args.get("product_id")
    store_tier = request.args.get("store_tier")
    status = request.args.get("status")
    center_id = request.args.get("center_id")
    if product_id:
        records = [p for p in records if p["product_id"] == product_id]
    if store_tier:
        records = [p for p in records if p["store_tier"] == store_tier]
    if status:
        records = [p for p in records if p["status"] == status]
    if center_id:
        records = [p for p in records if p["center_id"] == center_id]
    return list_response(records, ser_price_book)


# ---------------------------------------------------------------------------
# DeliveryRoute / DeliveryStop endpoints
# ---------------------------------------------------------------------------

def _route_load(route_id):
    load = 0
    for o in db.orders.values():
        if o.get("route_id") == route_id and o["status"] in ("CONFIRMED", "LOADED"):
            load += S.order_units(o)
    return load


def create_route(user_id, role, center_id):
    center = get_center(center_id)
    d = body()
    route_code = req_str(d, "route_code")
    day = req_enum(d, "day_of_week",
                   {"MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"})
    capacity = req_int(d, "truck_capacity_units")
    store_ids = d.get("assigned_store_ids", [])
    if not isinstance(store_ids, list) or not all(isinstance(x, str) for x in store_ids):
        raise ApiError("ERR_INVALID_REQUEST", "assigned_store_ids must be a list of store ids", 400)
    for sid in store_ids:
        store = db.stores.get(sid)
        if store is None or store["center_id"] != center_id:
            raise ApiError("ERR_STORE_NOT_FOUND", "Store with given ID does not exist in this center", 404)
    rec = S.new_record()
    rec.update({
        "id": new_id(),
        "center_id": center_id,
        "route_code": route_code,
        "day_of_week": day,
        "truck_capacity_units": capacity,
        "assigned_store_ids": store_ids,
        "status": "PLANNED",
        "dispatched_at": None,
    })
    db.routes[rec["id"]] = rec
    now = db.clock.now()
    for i, sid in enumerate(store_ids):
        stop = S.new_record()
        stop.update({
            "id": new_id(),
            "route_id": rec["id"],
            "store_id": sid,
            "sequence_number": i + 1,
            "estimated_arrival": now + timedelta(hours=i + 1),
            "actual_arrival": None,
            "status": "PENDING",
        })
        db.stops[stop["id"]] = stop
    return ok(ser_route(rec), 201)


def get_route_ep(user_id, role, center_id, route_id):
    return ok(ser_route(get_route(center_id, route_id)))


def list_routes_scoped(user_id, role, center_id):
    get_center(center_id)
    records = [r for r in db.routes.values() if r["center_id"] == center_id]
    return _filter_routes(records)


def _filter_routes(records):
    day = request.args.get("day_of_week")
    status = request.args.get("status")
    center_id = request.args.get("center_id")
    if day:
        records = [r for r in records if r["day_of_week"] == day]
    if status:
        records = [r for r in records if r["status"] == status]
    if center_id:
        records = [r for r in records if r["center_id"] == center_id]
    return list_response(records, ser_route)


def dispatch_route(user_id, role, center_id, route_id):
    route = get_route(center_id, route_id)
    center = db.centers[center_id]
    expect_state(route, ("PLANNED",))
    center_operational(center)
    for sid in route["assigned_store_ids"]:
        store = db.stores.get(sid)
        if store is None or store["status"] != "ACTIVE":
            raise ApiError("ERR_STORE_NOT_ACTIVE", "All assigned stores must be ACTIVE", 409)
    if _route_load(route["id"]) > route["truck_capacity_units"]:
        raise ApiError("ERR_ROUTE_OVERLOADED", "Route load exceeds truck capacity", 409)
    route["status"] = "DISPATCHED"
    route["dispatched_at"] = db.clock.now()
    S.touch(route)
    for stop in db.stops.values():
        if stop["route_id"] == route["id"]:
            if stop["status"] != "PENDING":
                stop["status"] = "PENDING"
                S.touch(stop)
    return ok(ser_route(route))


def cancel_route(user_id, role, center_id, route_id):
    body()
    route = get_route(center_id, route_id)
    expect_state(route, ("PLANNED", "DISPATCHED"))
    if route["status"] == "PLANNED":
        for o in db.orders.values():
            if o.get("route_id") == route["id"] and o["status"] == "CONFIRMED":
                o["status"] = "SUBMITTED"
                o["route_id"] = None
                S.touch(o)
    else:
        stops = [s for s in db.stops.values() if s["route_id"] == route["id"]]
        if any(s["status"] == "COMPLETED" for s in stops):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Cannot cancel a dispatched route with completed stops", 409)
        for s in stops:
            s["status"] = "SKIPPED"
            S.touch(s)
        for o in db.orders.values():
            if o.get("route_id") == route["id"] and o["status"] == "LOADED":
                o["status"] = "CONFIRMED"
                S.touch(o)
                for l in db.lines.values():
                    if l["order_id"] == o["id"] and l["status"] == "SHIPPED":
                        l["status"] = "CONFIRMED"
                        S.touch(l)
    route["status"] = "CANCELLED"
    S.touch(route)
    return ok(ser_route(route))


def get_stop_ep(user_id, role, center_id, route_id, stop_id):
    return ok(ser_stop(get_stop(center_id, route_id, stop_id)))


def list_stops_scoped(user_id, role, center_id, route_id):
    get_route(center_id, route_id)
    records = [s for s in db.stops.values() if s["route_id"] == route_id]
    return _filter_stops(records)


def _filter_stops(records):
    status = request.args.get("status")
    route_id = request.args.get("route_id")
    store_id = request.args.get("store_id")
    if status:
        records = [s for s in records if s["status"] == status]
    if route_id:
        records = [s for s in records if s["route_id"] == route_id]
    if store_id:
        records = [s for s in records if s["store_id"] == store_id]
    return list_response(records, ser_stop)


def arrive_stop(user_id, role, center_id, route_id, stop_id):
    stop = get_stop(center_id, route_id, stop_id)
    expect_state(stop, ("PENDING",))
    stop["status"] = "ARRIVED"
    stop["actual_arrival"] = db.clock.now()
    S.touch(stop)
    return ok(ser_stop(stop))


def complete_stop(user_id, role, center_id, route_id, stop_id):
    stop = get_stop(center_id, route_id, stop_id)
    expect_state(stop, ("ARRIVED",))
    stop["status"] = "COMPLETED"
    S.touch(stop)
    S.maybe_complete_route(db.routes[route_id])
    return ok(ser_stop(stop))


def skip_stop(user_id, role, center_id, route_id, stop_id):
    body()
    stop = get_stop(center_id, route_id, stop_id)
    expect_state(stop, ("PENDING", "ARRIVED"))
    stop["status"] = "SKIPPED"
    S.touch(stop)
    S.maybe_complete_route(db.routes[route_id])
    return ok(ser_stop(stop))


# ---------------------------------------------------------------------------
# PurchaseOrder / OrderLine endpoints
# ---------------------------------------------------------------------------

def create_order(user_id, role, center_id, store_id):
    store = get_store(center_id, store_id)
    check_store_ownership(store_id, user_id)
    d = body()
    week_start = req_ts(d, "week_start_date")
    promo_id = d.get("promotion_id")
    if promo_id is not None:
        if not isinstance(promo_id, str):
            raise ApiError("ERR_INVALID_REQUEST", "promotion_id must be a string", 400)
        promo = db.promotions.get(promo_id)
        if promo is None or promo["center_id"] != center_id:
            raise ApiError("ERR_PROMOTION_NOT_FOUND", "PromotionEvent with given ID does not exist", 404)
    rec = S.new_record()
    center = db.centers[center_id]
    rec.update({
        "id": new_id(),
        "store_id": store_id,
        "center_id": center_id,
        "week_start_date": week_start,
        "status": "DRAFT",
        "subtotal_cents": 0,
        "markup_cents": 0,
        "delivery_fee_cents": 0,
        "total_cents": 0,
        "theoretical_usage_cents": 0,
        "actual_usage_cents": 0,
        "food_cost_variance_pct": None,
        "promotion_id": promo_id,
        "route_id": None,
        "created_ops_index": center["ops_run_index"],
    })
    db.orders[rec["id"]] = rec
    return ok(ser_order(rec), 201)


def get_order_ep(user_id, role, center_id, order_id):
    return ok(ser_order(get_order(center_id, order_id)))


def list_orders_scoped(user_id, role, center_id):
    get_center(center_id)
    records = [o for o in db.orders.values() if o["center_id"] == center_id]
    return _filter_orders(records)


def _filter_orders(records):
    store_id = request.args.get("store_id")
    status = request.args.get("status")
    week = request.args.get("week_start_date")
    promo_id = request.args.get("promotion_id")
    route_id = request.args.get("route_id")
    center_id = request.args.get("center_id")
    if store_id:
        records = [o for o in records if o["store_id"] == store_id]
    if status:
        records = [o for o in records if o["status"] == status]
    if week:
        w = parse_ts(week, "week_start_date")
        records = [o for o in records if o["week_start_date"] == w]
    if promo_id:
        records = [o for o in records if o.get("promotion_id") == promo_id]
    if route_id:
        records = [o for o in records if o.get("route_id") == route_id]
    if center_id:
        records = [o for o in records if o["center_id"] == center_id]
    return list_response(records, ser_order)


def add_order_line(user_id, role, center_id, store_id, order_id):
    store = get_store(center_id, store_id)
    check_store_ownership(store_id, user_id)
    order = get_scoped_order(center_id, store_id, order_id)
    expect_state(order, ("DRAFT",))
    d = body()
    product_id = d.get("product_id")
    product = db.products.get(product_id) if isinstance(product_id, str) else None
    if product is None or product["center_id"] != center_id:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", "Product with given ID does not exist in this center", 404)
    quantity = req_int(d, "quantity", minimum=1)
    if product["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCT_UNAVAILABLE", "Product is DISCONTINUED or RECALLED", 409)
    unit_price = S.price_line(product, quantity)
    rec = S.new_record()
    rec.update({
        "id": new_id(),
        "order_id": order_id,
        "product_id": product_id,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "extended_price_cents": quantity * unit_price,
        "theoretical_usage_cents": 0,
        "status": "PENDING",
    })
    db.lines[rec["id"]] = rec
    S.compute_po_totals(order)
    S.touch(order)
    return ok(ser_line(rec), 201)


def list_order_lines(user_id, role, center_id, order_id):
    get_order(center_id, order_id)
    records = [l for l in db.lines.values() if l["order_id"] == order_id]
    return _filter_lines(records)


def _filter_lines(records):
    order_id = request.args.get("order_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    if order_id:
        records = [l for l in records if l["order_id"] == order_id]
    if product_id:
        records = [l for l in records if l["product_id"] == product_id]
    if status:
        records = [l for l in records if l["status"] == status]
    return list_response(records, ser_line)


def submit_order(user_id, role, center_id, store_id, order_id):
    store = get_store(center_id, store_id)
    check_store_ownership(store_id, user_id)
    order = get_scoped_order(center_id, store_id, order_id)
    center = db.centers[center_id]
    if store["status"] != "ACTIVE":
        raise ApiError("ERR_STORE_NOT_ACTIVE", "Store is not ACTIVE", 409)
    center_operational(center)
    expect_state(order, ("DRAFT",))
    d = body()
    if "expected_store_version" not in d:
        raise ApiError("ERR_INVALID_REQUEST", "expected_store_version is required", 400)
    expected = d["expected_store_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", "expected_store_version must be an integer", 400)
    if expected != store["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_store_version does not match current store version", 412)
    lines = [l for l in db.lines.values() if l["order_id"] == order_id]
    if not lines:
        raise ApiError("ERR_ORDER_HAS_NO_LINES", "Cannot submit purchase order with zero lines", 409)
    # Re-price provisional lines off the current price book.
    for l in lines:
        if l["status"] == "PENDING":
            product = db.products[l["product_id"]]
            l["unit_price_cents"] = S.price_line(product, l["quantity"])
            l["extended_price_cents"] = l["quantity"] * l["unit_price_cents"]
            S.touch(l)
    S.compute_po_totals(order)
    if order["total_cents"] > store["credit_limit_cents"] - store["outstanding_balance_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED",
                       "Order total exceeds store credit limit minus outstanding balance", 409)
    order["status"] = "SUBMITTED"
    S.touch(order)
    S.touch(store)
    return ok(ser_order(order))


def confirm_order(user_id, role, center_id, order_id):
    order = get_order(center_id, order_id)
    center = db.centers[center_id]
    expect_state(order, ("SUBMITTED",))
    promo_id = order.get("promotion_id")
    if promo_id:
        promo = db.promotions.get(promo_id)
        if promo is None or promo["status"] not in ("CONFIRMED", "EXECUTING"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Referenced promotion must be CONFIRMED or EXECUTING", 409)
    units = S.order_units(order)
    week = week_of(order["week_start_date"])
    plans = [p for p in db.plans.values()
             if p["center_id"] == center_id and week_of(p["week_start_date"]) == week]
    plan = plans[0] if plans else None
    if plan is not None and plan["status"] == "LOCKED":
        raise ApiError("ERR_CAPACITY_PLAN_LOCKED", "Capacity plan is LOCKED; modifications blocked", 409)
    if plan is None or S.plan_available(plan) < units:
        raise ApiError("ERR_CAPACITY_EXCEEDED",
                       "Weekly capacity plan has insufficient available units", 409)
    if center["posture"] == "CONSTRAINED":
        raise ApiError("ERR_CAPACITY_EXCEEDED",
                       "Center is CONSTRAINED; new order confirmations blocked", 409)
    candidates = sorted(
        (r for r in db.routes.values()
         if r["center_id"] == center_id and r["status"] == "PLANNED"
         and order["store_id"] in r["assigned_store_ids"]),
        key=lambda r: (r["created_at"], r["id"]))
    # Assign the next PLANNED route covering the store; the truck-capacity check
    # fires at dispatch (PRD §3.6), where an over-capacity load is refused with
    # ERR_ROUTE_OVERLOADED.
    route = candidates[0] if candidates else None
    if route is None:
        raise ApiError("ERR_NO_ROUTE_AVAILABLE", "No PLANNED route covers this store for the order week", 409)
    order["status"] = "CONFIRMED"
    order["route_id"] = route["id"]
    S.touch(order)
    for l in db.lines.values():
        if l["order_id"] == order_id and l["status"] == "PENDING":
            l["status"] = "CONFIRMED"
            S.touch(l)
    S.allocate_units(plan, units)
    return ok(ser_order(order))


def load_order(user_id, role, center_id, order_id):
    order = get_order(center_id, order_id)
    expect_state(order, ("CONFIRMED",))
    route = db.routes.get(order.get("route_id") or "")
    if route is None or route["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Assigned route is not DISPATCHED", 409)
    order["status"] = "LOADED"
    S.touch(order)
    for l in db.lines.values():
        if l["order_id"] == order_id and l["status"] == "CONFIRMED":
            l["status"] = "SHIPPED"
            S.touch(l)
    return ok(ser_order(order))


def deliver_order(user_id, role, center_id, order_id):
    order = get_order(center_id, order_id)
    expect_state(order, ("LOADED",))
    d = body()
    actual = req_int(d, "actual_usage_cents")
    route_id = order.get("route_id")
    stop = next((s for s in db.stops.values()
                 if s["route_id"] == route_id and s["store_id"] == order["store_id"]), None)
    if stop is None or stop["status"] != "ARRIVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "DeliveryStop for this store is not ARRIVED", 409)
    order["actual_usage_cents"] = actual
    order["status"] = "DELIVERED"
    S.touch(order)
    for l in db.lines.values():
        if l["order_id"] == order_id and l["status"] == "SHIPPED":
            l["status"] = "DELIVERED"
            product = db.products[l["product_id"]]
            factor = S.YIELD_FACTORS.get(product["category"], 0.0)
            l["theoretical_usage_cents"] = S.floor_cents(
                S.dec(l["quantity"]) * S.dec(product["base_cost_cents_per_unit"]) * S.dec(factor))
            S.touch(l)
    order["theoretical_usage_cents"] = sum(
        l["theoretical_usage_cents"] for l in db.lines.values()
        if l["order_id"] == order_id and l["status"] == "DELIVERED")
    S.compute_po_totals(order)
    return ok(ser_order(order))


def settle_order_ep(user_id, role, center_id, order_id):
    order = get_order(center_id, order_id)
    expect_state(order, ("DELIVERED",))
    lines = [l for l in db.lines.values() if l["order_id"] == order_id]
    if not all(l["status"] in ("DELIVERED", "SHORTED") for l in lines):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "All OrderLines must be DELIVERED or SHORTED", 409)
    S.settle_order(order)
    return ok(ser_order(order))


def cancel_order(user_id, role, center_id, store_id, order_id):
    body()
    store = get_store(center_id, store_id)
    check_store_ownership(store_id, user_id)
    order = get_scoped_order(center_id, store_id, order_id)
    if store["status"] != "ACTIVE":
        raise ApiError("ERR_STORE_NOT_ACTIVE", "Store is not ACTIVE", 409)
    expect_state(order, ("DRAFT", "SUBMITTED"))
    order["status"] = "CANCELLED"
    S.touch(order)
    for l in db.lines.values():
        if l["order_id"] == order_id and l["status"] == "PENDING":
            l["status"] = "CANCELLED"
            S.touch(l)
    return ok(ser_order(order))


def reject_order(user_id, role, center_id, order_id):
    body()
    order = get_order(center_id, order_id)
    expect_state(order, ("SUBMITTED",))
    order["status"] = "REJECTED"
    S.touch(order)
    return ok(ser_order(order))


def mark_line_shorted(user_id, role, center_id, order_id, line_id):
    order = get_order(center_id, order_id)
    line = get_line(center_id, order_id, line_id)
    expect_state(line, ("SHIPPED",))
    line["status"] = "SHORTED"
    S.touch(line)
    S.compute_po_totals(order)
    S.touch(order)
    week = week_of(order["week_start_date"])
    plan = next((p for p in db.plans.values()
                 if p["center_id"] == center_id and week_of(p["week_start_date"]) == week), None)
    if plan is not None:
        S.deallocate_units(plan, line["quantity"])
    return ok(ser_line(line))


# ---------------------------------------------------------------------------
# Promotion endpoints
# ---------------------------------------------------------------------------

def create_promotion(user_id, role, center_id):
    center = get_center(center_id)
    d = body()
    code = req_str(d, "promotion_code")
    start = req_ts(d, "start_date")
    end = req_ts(d, "end_date")
    multiplier = req_num(d, "surge_multiplier")
    affected = d.get("affected_product_ids", [])
    if not isinstance(affected, list) or not all(isinstance(x, str) for x in affected):
        raise ApiError("ERR_INVALID_REQUEST", "affected_product_ids must be a list of product ids", 400)
    for pid in affected:
        product = db.products.get(pid)
        if product is None or product["center_id"] != center_id:
            raise ApiError("ERR_PRODUCT_NOT_FOUND", "Product with given ID does not exist in this center", 404)
    if start >= end:
        raise ApiError("ERR_INVALID_DATE_RANGE", "start_date must be strictly before end_date", 400)
    rec = S.new_record()
    rec.update({
        "id": new_id(),
        "center_id": center_id,
        "promotion_code": code,
        "start_date": start,
        "end_date": end,
        "surge_multiplier": multiplier,
        "affected_product_ids": affected,
        "capacity_reserved_units": 0,
        "status": "FORECASTED",
    })
    db.promotions[rec["id"]] = rec
    return ok(ser_promotion(rec), 201)


def get_promotion_ep(user_id, role, center_id, promotion_id):
    return ok(ser_promotion(get_promotion(center_id, promotion_id)))


def list_promotions_scoped(user_id, role, center_id):
    get_center(center_id)
    records = [p for p in db.promotions.values() if p["center_id"] == center_id]
    return _filter_promotions(records)


def _filter_promotions(records):
    status = request.args.get("status")
    center_id = request.args.get("center_id")
    if status:
        records = [p for p in records if p["status"] == status]
    if center_id:
        records = [p for p in records if p["center_id"] == center_id]
    return list_response(records, ser_promotion)


def confirm_promotion(user_id, role, center_id, promotion_id):
    promo = get_promotion(center_id, promotion_id)
    center = db.centers[center_id]
    center_operational(center)
    expect_state(promo, ("FORECASTED",))
    for other in db.promotions.values():
        if (other["id"] != promo["id"] and other["center_id"] == center_id
                and other["status"] in ("CONFIRMED", "EXECUTING")
                and promo["start_date"] < other["end_date"] and other["start_date"] < promo["end_date"]
                and set(other["affected_product_ids"]) & set(promo["affected_product_ids"])):
            raise ApiError("ERR_PROMOTION_OVERLAP",
                           "Promotion dates overlap with existing CONFIRMED/EXECUTING promotion", 409)
    promo["status"] = "CONFIRMED"
    center["surge_capacity_multiplier"] = promo["surge_multiplier"]
    S.recompute_posture(center)
    S.touch(center)
    S.touch(promo)
    # Raise surge units on capacity plans whose week overlaps the promotion window.
    surge_per_plan = {}
    for plan in db.plans.values():
        if plan["center_id"] != center_id:
            continue
        week_start = week_of(plan["week_start_date"])
        week_end = week_start + timedelta(days=7)
        if week_start < promo["end_date"] and week_end > promo["start_date"]:
            add = S.floor_cents(S.dec(plan["baseline_units"]) * (S.dec(promo["surge_multiplier"]) - 1))
            surge_per_plan[plan["id"]] = add
            plan["surge_units"] += add
            plan["available_units"] = S.plan_available(plan)
            S.touch(plan)
    promo["capacity_reserved_units"] = sum(surge_per_plan.values())
    return ok(ser_promotion(promo))


def close_promotion(user_id, role, center_id, promotion_id):
    promo = get_promotion(center_id, promotion_id)
    center = db.centers[center_id]
    expect_state(promo, ("EXECUTING",))
    promo["status"] = "CLOSED"
    S.touch(promo)
    center["surge_capacity_multiplier"] = 1.0
    S.recompute_posture(center)
    S.touch(center)
    now_week = week_of(db.clock.now())
    for plan in db.plans.values():
        if plan["center_id"] == center_id and week_of(plan["week_start_date"]) > now_week:
            if plan["surge_units"]:
                plan["surge_units"] = 0
                plan["available_units"] = S.plan_available(plan)
                S.touch(plan)
    return ok(ser_promotion(promo))


def cancel_promotion(user_id, role, center_id, promotion_id):
    body()
    promo = get_promotion(center_id, promotion_id)
    center = db.centers[center_id]
    expect_state(promo, ("FORECASTED", "CONFIRMED"))
    if promo["status"] == "CONFIRMED":
        if any(o.get("promotion_id") == promo["id"]
               and o["status"] in ("CONFIRMED", "LOADED", "DELIVERED", "SETTLED")
               for o in db.orders.values()):
            raise ApiError("ERR_PROMOTION_HAS_COMMITTED_ORDERS",
                           "Cannot cancel promotion with CONFIRMED or later purchase orders", 409)
    for o in db.orders.values():
        if o.get("promotion_id") == promo["id"] and o["status"] in ("DRAFT", "SUBMITTED"):
            o["status"] = "REJECTED"
            S.touch(o)
    promo["status"] = "CANCELLED"
    S.touch(promo)
    S.recompute_posture(center)
    S.touch(center)
    return ok(ser_promotion(promo))


# ---------------------------------------------------------------------------
# RebatePool / RebateLedger endpoints
# ---------------------------------------------------------------------------

def create_pool(user_id, role, center_id):
    center = get_center(center_id)
    d = body()
    quarter = req_str(d, "quarter")
    rec = S.new_record()
    rec.update({
        "id": new_id(),
        "center_id": center_id,
        "quarter": quarter,
        "pool_total_cents": 0,
        "distributed_cents": 0,
        "holdback_cents": 0,
        "status": "OPEN",
    })
    db.pools[rec["id"]] = rec
    return ok(ser_pool(rec), 201)


def get_pool_ep(user_id, role, center_id, pool_id):
    return ok(ser_pool(get_pool(center_id, pool_id)))


def list_pools_scoped(user_id, role, center_id):
    get_center(center_id)
    records = [p for p in db.pools.values() if p["center_id"] == center_id]
    return _filter_pools(records)


def _filter_pools(records):
    quarter = request.args.get("quarter")
    status = request.args.get("status")
    center_id = request.args.get("center_id")
    if quarter:
        records = [p for p in records if p["quarter"] == quarter]
    if status:
        records = [p for p in records if p["status"] == status]
    if center_id:
        records = [p for p in records if p["center_id"] == center_id]
    return list_response(records, ser_pool)


def calculate_pool(user_id, role, center_id, pool_id):
    pool = get_pool(center_id, pool_id)
    expect_state(pool, ("OPEN",))
    settled_total = sum(o["total_cents"] for o in db.orders.values()
                        if o["center_id"] == center_id and o["status"] == "SETTLED"
                        and S.quarter_of(o["week_start_date"]) == pool["quarter"])
    pool["pool_total_cents"] = S.floor_cents(S.dec(settled_total) * S.dec(S.POOL_RATE))
    accruals = {}
    for e in db.ledgers.values():
        if e["pool_id"] == pool["id"] and e["entry_type"] == "ACCRUAL" and e["status"] != "VOIDED":
            accruals[e["store_id"]] = accruals.get(e["store_id"], 0) + e["amount_cents"]
    holdback = sum(e["amount_cents"] for e in db.ledgers.values()
                   if e["pool_id"] == pool["id"] and e["entry_type"] == "HOLDBACK" and e["status"] != "VOIDED")
    pool["holdback_cents"] = holdback
    pool["distributed_cents"] = pool["pool_total_cents"] - holdback
    pool["status"] = "CALCULATING"
    S.touch(pool)
    return ok(ser_pool(pool))


def settle_pool(user_id, role, center_id, pool_id):
    pool = get_pool(center_id, pool_id)
    center = db.centers[center_id]
    expect_state(pool, ("CALCULATING",))
    entries = [e for e in db.ledgers.values() if e["pool_id"] == pool["id"]]
    if pool["pool_total_cents"] - pool["holdback_cents"] < 0:
        raise ApiError("ERR_POOL_INSUFFICIENT", "Rebate pool balance insufficient for settlement", 409)
    accruals = {}
    for e in entries:
        if e["entry_type"] == "ACCRUAL" and e["status"] != "VOIDED":
            accruals[e["store_id"]] = accruals.get(e["store_id"], 0) + e["amount_cents"]
    total_accrual = sum(accruals.values())
    if total_accrual > 0 and pool["pool_total_cents"] > 0:
        now = db.clock.now()
        settlement_date = now + timedelta(days=S.HOLDBACK_DAYS)
        for store_id, acc in accruals.items():
            store = db.stores.get(store_id)
            if store is None or store["rebate_eligibility_status"] == "INELIGIBLE":
                continue
            amount = S.floor_cents(S.dec(pool["pool_total_cents"]) * S.dec(acc) / S.dec(total_accrual))
            if amount > 0:
                S.create_ledger_entry(pool["id"], store_id, "SETTLEMENT", amount,
                                      settlement_date=settlement_date)
    # Cascade: all PENDING entries (including newly scheduled SETTLEMENTs) -> POSTED.
    for e in db.ledgers.values():
        if e["pool_id"] == pool["id"] and e["status"] == "PENDING":
            e["status"] = "POSTED"
            S.touch(e)
    pool["status"] = "SETTLING"
    S.touch(pool)
    S.touch(center)
    return ok(ser_pool(pool))


def get_ledger_ep(user_id, role, center_id, ledger_id):
    return ok(ser_ledger(get_ledger(center_id, ledger_id)))


def list_ledgers_scoped(user_id, role, center_id):
    get_center(center_id)
    records = [e for e in db.ledgers.values()
               if db.pools.get(e["pool_id"]) and db.pools[e["pool_id"]]["center_id"] == center_id]
    return _filter_ledgers(records)


def _filter_ledgers(records):
    pool_id = request.args.get("pool_id")
    store_id = request.args.get("store_id")
    source_order_id = request.args.get("source_order_id")
    entry_type = request.args.get("entry_type")
    status = request.args.get("status")
    if pool_id:
        records = [e for e in records if e["pool_id"] == pool_id]
    if store_id:
        records = [e for e in records if e["store_id"] == store_id]
    if source_order_id:
        records = [e for e in records if e.get("source_order_id") == source_order_id]
    if entry_type:
        records = [e for e in records if e["entry_type"] == entry_type]
    if status:
        records = [e for e in records if e["status"] == status]
    return list_response(records, ser_ledger)


def void_ledger(user_id, role, center_id, ledger_id):
    body()
    entry = get_ledger(center_id, ledger_id)
    if entry["status"] == "SETTLED":
        raise ApiError("ERR_REBATE_ALREADY_SETTLED", "Rebate ledger entry is already SETTLED", 409)
    expect_state(entry, ("PENDING", "POSTED"))
    pool = db.pools.get(entry["pool_id"])
    entry["status"] = "VOIDED"
    S.touch(entry)
    if pool is not None:
        if entry["entry_type"] == "HOLDBACK":
            pool["holdback_cents"] -= entry["amount_cents"]
        else:
            pool["distributed_cents"] -= entry["amount_cents"]
        S.touch(pool)
        S.maybe_auto_close_pool(pool)
    return ok(ser_ledger(entry))


# ---------------------------------------------------------------------------
# ComplianceAgreement endpoints
# ---------------------------------------------------------------------------

def create_agreement(user_id, role, center_id, store_id):
    store = get_store(center_id, store_id)
    d = body()
    agreement_type = req_enum(d, "agreement_type",
                              {"EXCLUSIVE_PURCHASE", "APPROVED_SUPPLIER", "BRAND_STANDARD"})
    start = req_ts(d, "start_date")
    end = d.get("end_date")
    if end is not None:
        end = parse_ts(end, "end_date")
        if start >= end:
            raise ApiError("ERR_INVALID_DATE_RANGE", "start_date must be strictly before end_date", 400)
    threshold = req_num(d, "exclusive_purchase_threshold")
    rec = S.new_record()
    rec.update({
        "id": new_id(),
        "store_id": store["id"],
        "agreement_type": agreement_type,
        "start_date": start,
        "end_date": end,
        "exclusive_purchase_threshold": threshold,
        "status": "PROPOSED",
        "breach_count": 0,
        "cure_deadline": None,
        "consecutive_breach_weeks": 0,
    })
    db.agreements[rec["id"]] = rec
    return ok(ser_agreement(rec), 201)


def get_agreement_ep(user_id, role, center_id, agreement_id):
    return ok(ser_agreement(get_agreement(center_id, agreement_id)))


def list_agreements_scoped(user_id, role, center_id):
    get_center(center_id)
    store_ids = {s["id"] for s in db.stores.values() if s["center_id"] == center_id}
    records = [a for a in db.agreements.values() if a["store_id"] in store_ids]
    return _filter_agreements(records)


def _filter_agreements(records):
    store_id = request.args.get("store_id")
    status = request.args.get("status")
    if store_id:
        records = [a for a in records if a["store_id"] == store_id]
    if status:
        records = [a for a in records if a["status"] == status]
    return list_response(records, ser_agreement)


def activate_agreement(user_id, role, center_id, store_id, agreement_id):
    store = get_store(center_id, store_id)
    agreement = get_scoped_agreement(center_id, store_id, agreement_id)
    expect_state(agreement, ("PROPOSED",))
    if store["status"] not in ("ACTIVE", "ONBOARDING"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Store must be ACTIVE or ONBOARDING to activate an agreement", 409)
    agreement["status"] = "ACTIVE"
    agreement["consecutive_breach_weeks"] = 0
    S.touch(agreement)
    # Activation re-evaluates the store's rebate_eligibility_status (PRD §3.2),
    # which is computed from the trailing four-week exclusive_purchase_pct.
    S.recompute_exclusive_pct(store)
    S.touch(store)
    return ok(ser_agreement(agreement))


def cure_agreement(user_id, role, center_id, store_id, agreement_id):
    store = get_store(center_id, store_id)
    agreement = get_scoped_agreement(center_id, store_id, agreement_id)
    expect_state(agreement, ("BREACHED",))
    if store["exclusive_purchase_pct"] < agreement["exclusive_purchase_threshold"]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Current exclusive_purchase_pct must be at or above threshold to cure", 409)
    agreement["status"] = "CURED"
    S.touch(agreement)
    S.recompute_store_derived(store)
    S.touch(store)
    return ok(ser_agreement(agreement))


def terminate_agreement(user_id, role, center_id, store_id, agreement_id):
    store = get_store(center_id, store_id)
    agreement = get_scoped_agreement(center_id, store_id, agreement_id)
    expect_state(agreement, ("BREACHED",))
    agreement["status"] = "TERMINATED"
    S.touch(agreement)
    store["rebate_eligibility_status"] = "INELIGIBLE"
    store["compliance_tier"] = "NON_COMPLIANT"
    S.touch(store)
    return ok(ser_agreement(agreement))


# ---------------------------------------------------------------------------
# CapacityPlan endpoints
# ---------------------------------------------------------------------------

def create_plan(user_id, role, center_id):
    center = get_center(center_id)
    d = body()
    week_start = req_ts(d, "week_start_date")
    baseline = S.floor_cents(S.dec(center["base_weekly_capacity_units"]) * S.dec(center["surge_capacity_multiplier"]))
    rec = S.new_record()
    rec.update({
        "id": new_id(),
        "center_id": center_id,
        "week_start_date": week_start,
        "baseline_units": baseline,
        "surge_units": 0,
        "allocated_units": 0,
        "available_units": baseline,
        "status": "OPEN",
    })
    db.plans[rec["id"]] = rec
    return ok(ser_plan(rec), 201)


def get_plan_ep(user_id, role, center_id, plan_id):
    return ok(ser_plan(get_plan(center_id, plan_id)))


def list_plans_scoped(user_id, role, center_id):
    get_center(center_id)
    records = [p for p in db.plans.values() if p["center_id"] == center_id]
    return _filter_plans(records)


def _filter_plans(records):
    week = request.args.get("week_start_date")
    status = request.args.get("status")
    center_id = request.args.get("center_id")
    if week:
        w = parse_ts(week, "week_start_date")
        records = [p for p in records if p["week_start_date"] == w]
    if status:
        records = [p for p in records if p["status"] == status]
    if center_id:
        records = [p for p in records if p["center_id"] == center_id]
    return list_response(records, ser_plan)


def lock_plan(user_id, role, center_id, plan_id):
    plan = get_plan(center_id, plan_id)
    center = db.centers[center_id]
    expect_state(plan, ("OPEN",))
    d = body()
    if "expected_center_version" not in d:
        raise ApiError("ERR_INVALID_REQUEST", "expected_center_version is required", 400)
    expected = d["expected_center_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", "expected_center_version must be an integer", 400)
    if expected != center["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_center_version does not match current center version", 412)
    if plan["allocated_units"] > plan["baseline_units"] + plan["surge_units"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED",
                       "allocated_units exceeds baseline plus surge", 409)
    plan["status"] = "LOCKED"
    S.touch(plan)
    S.touch(center)
    return ok(ser_plan(plan))


# ---------------------------------------------------------------------------
# FoodCostVariance endpoints
# ---------------------------------------------------------------------------

def create_variance(user_id, role, center_id, store_id):
    store = get_store(center_id, store_id)
    d = body()
    week_start = req_ts(d, "week_start_date")
    week = week_of(week_start)
    settled = [o for o in db.orders.values()
               if o["store_id"] == store["id"] and o["status"] == "SETTLED"
               and week_of(o["week_start_date"]) == week]
    theo = sum(o["theoretical_usage_cents"] for o in settled)
    actual = sum(o["actual_usage_cents"] for o in settled)
    variance = actual - theo
    if theo == 0:
        pct = None
        severity = "GREEN"
    else:
        pct = S.round4(variance / theo)
        severity = "GREEN" if pct <= S.GREEN_THRESHOLD else ("YELLOW" if pct <= S.YELLOW_THRESHOLD else "RED")
    rec = S.new_record()
    rec.update({
        "id": new_id(),
        "store_id": store["id"],
        "week_start_date": week_start,
        "theoretical_cents": theo,
        "actual_cents": actual,
        "variance_cents": variance,
        "variance_pct": pct,
        "severity": severity,
        "status": "FLAGGED" if severity == "RED" else "PENDING",
    })
    db.variances[rec["id"]] = rec
    return ok(ser_variance(rec), 201)


def get_variance_ep(user_id, role, center_id, store_id, variance_id):
    return ok(ser_variance(get_scoped_variance(center_id, store_id, variance_id)))


def list_variances_scoped(user_id, role, center_id):
    get_center(center_id)
    store_ids = {s["id"] for s in db.stores.values() if s["center_id"] == center_id}
    records = [v for v in db.variances.values() if v["store_id"] in store_ids]
    return _filter_variances(records)


def _filter_variances(records):
    store_id = request.args.get("store_id")
    week = request.args.get("week_start_date")
    severity = request.args.get("severity")
    status = request.args.get("status")
    if store_id:
        records = [v for v in records if v["store_id"] == store_id]
    if week:
        w = parse_ts(week, "week_start_date")
        records = [v for v in records if v["week_start_date"] == w]
    if severity:
        records = [v for v in records if v["severity"] == severity]
    if status:
        records = [v for v in records if v["status"] == status]
    return list_response(records, ser_variance)


# ---------------------------------------------------------------------------
# Compliance report endpoint
# ---------------------------------------------------------------------------

def create_compliance_report(user_id, role, center_id, store_id):
    store = get_store(center_id, store_id)
    check_store_ownership(store_id, user_id)
    d = body()
    week_start = req_ts(d, "week_start_date")
    external = req_int(d, "external_purchases_cents", minimum=0)
    rec = S.new_record()
    rec.update({
        "id": new_id(),
        "store_id": store["id"],
        "center_id": center_id,
        "week_start_date": week_start,
        "external_purchases_cents": external,
    })
    db.compliance_reports[rec["id"]] = rec
    S.recompute_exclusive_pct(store)
    S.touch(store)
    return ok({"report_id": rec["id"], "exclusive_purchase_pct": store["exclusive_purchase_pct"]}, 201)


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------

def set_clock(user_id, role):
    d = body()
    target = req_ts(d, "to_iso8601")
    db.clock.set(target)
    for center in list(db.centers.values()):
        S.run_automatic_sweeps(center)
    return ok({"current_utc": format_ts(db.clock.now())})


# ---------------------------------------------------------------------------
# Flat FK reverse-reachability endpoints
# ---------------------------------------------------------------------------

def _flat_get(table, serializer, not_found_id, not_found_msg, record_id):
    rec = table.get(record_id)
    if rec is None:
        raise ApiError(not_found_id, not_found_msg, 404)
    return ok(serializer(rec))


def flat_get_store(user_id, role, store_id):
    return _flat_get(db.stores, ser_store, "ERR_STORE_NOT_FOUND",
                     "Store with given ID does not exist", store_id)


def flat_list_stores(user_id, role):
    return _filter_stores(list(db.stores.values()))


def flat_get_product(user_id, role, product_id):
    return _flat_get(db.products, ser_product, "ERR_PRODUCT_NOT_FOUND",
                     "Product with given ID does not exist", product_id)


def flat_list_products(user_id, role):
    return _filter_products(list(db.products.values()))


def flat_get_route(user_id, role, route_id):
    return _flat_get(db.routes, ser_route, "ERR_ROUTE_NOT_FOUND",
                     "DeliveryRoute with given ID does not exist", route_id)


def flat_list_routes(user_id, role):
    return _filter_routes(list(db.routes.values()))


def flat_get_stop(user_id, role, stop_id):
    return _flat_get(db.stops, ser_stop, "ERR_ROUTE_NOT_FOUND",
                     "DeliveryStop with given ID does not exist", stop_id)


def flat_list_stops(user_id, role):
    return _filter_stops(list(db.stops.values()))


def flat_get_order(user_id, role, order_id):
    return _flat_get(db.orders, ser_order, "ERR_ORDER_NOT_FOUND",
                     "PurchaseOrder with given ID does not exist", order_id)


def flat_list_orders(user_id, role):
    return _filter_orders(list(db.orders.values()))


def flat_get_line(user_id, role, line_id):
    return _flat_get(db.lines, ser_line, "ERR_ORDER_NOT_FOUND",
                     "OrderLine with given ID does not exist", line_id)


def flat_list_lines(user_id, role):
    return _filter_lines(list(db.lines.values()))


def flat_get_price_book(user_id, role, price_book_id):
    return _flat_get(db.price_books, ser_price_book, "ERR_PRODUCT_NOT_FOUND",
                     "PriceBook with given ID does not exist", price_book_id)


def flat_list_price_books(user_id, role):
    return _filter_price_books(list(db.price_books.values()))


def flat_get_pool(user_id, role, pool_id):
    return _flat_get(db.pools, ser_pool, "ERR_POOL_NOT_FOUND",
                     "RebatePool with given ID does not exist", pool_id)


def flat_list_pools(user_id, role):
    return _filter_pools(list(db.pools.values()))


def flat_get_ledger(user_id, role, ledger_id):
    return _flat_get(db.ledgers, ser_ledger, "ERR_LEDGER_NOT_FOUND",
                     "RebateLedger with given ID does not exist", ledger_id)


def flat_list_ledgers(user_id, role):
    return _filter_ledgers(list(db.ledgers.values()))


def flat_get_agreement(user_id, role, agreement_id):
    return _flat_get(db.agreements, ser_agreement, "ERR_AGREEMENT_NOT_FOUND",
                     "ComplianceAgreement with given ID does not exist", agreement_id)


def flat_list_agreements(user_id, role):
    return _filter_agreements(list(db.agreements.values()))


def flat_get_promotion(user_id, role, promotion_id):
    return _flat_get(db.promotions, ser_promotion, "ERR_PROMOTION_NOT_FOUND",
                     "PromotionEvent with given ID does not exist", promotion_id)


def flat_list_promotions(user_id, role):
    return _filter_promotions(list(db.promotions.values()))


def flat_get_plan(user_id, role, plan_id):
    return _flat_get(db.plans, ser_plan, "ERR_PLAN_NOT_FOUND",
                     "CapacityPlan with given ID does not exist", plan_id)


def flat_list_plans(user_id, role):
    return _filter_plans(list(db.plans.values()))


def flat_get_variance(user_id, role, variance_id):
    return _flat_get(db.variances, ser_variance, "ERR_VARIANCE_NOT_FOUND",
                     "FoodCostVariance with given ID does not exist", variance_id)


def flat_list_variances(user_id, role):
    return _filter_variances(list(db.variances.values()))
