#!/usr/bin/env python3
"""Subscribe & Save API — in-memory Flask implementation of PRD.md (task 3010)."""

import os
import re
import uuid
import calendar
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return CLOCK


def today():
    return CLOCK.date()


def ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if not isinstance(s, str):
        return None
    try:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        d = datetime.fromisoformat(txt)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def parse_date(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def iso_dt_str(dt):
    return ts(dt)


def add_months_clamped(d, n):
    total = d.year * 12 + (d.month - 1) + n
    y, m0 = divmod(total, 12)
    m = m0 + 1
    dim = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, dim))


def month_bounds(month_str):
    y, m = int(month_str[:4]), int(month_str[5:7])
    dim = calendar.monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, dim)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
DB = {
    "customers": {},
    "products": {},
    "price_events": {},
    "placements": {},
    "subscriptions": {},
    "plans": {},
    "lines": {},
    "coupons": {},
    "promotions": {},
    "offers": {},
    "claims": {},
    "reshipments": {},
    "forecasts": {},
    "notifications": {},
}
SEQ = [0]


def new_id():
    return str(uuid.uuid4())


def next_seq():
    SEQ[0] += 1
    return SEQ[0]


def make_record(fields):
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = ts(now())
    rec["updated_at"] = ts(now())
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    rec["updated_at"] = ts(now())
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Errors & envelope (PRD §2.2)
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


def meta_block():
    return {"api_request_id": "req_" + uuid.uuid4().hex[:20],
            "api_request_timestamp": ts(now())}


def ok(data, code=200, response_type="object", pagination=None):
    body = {"meta": meta_block(), "response_type": response_type, "data": data}
    if pagination:
        body["meta"].update(pagination)
    return jsonify(body), code


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed."},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Auth (PRD §2.1, validations priority 2-4)
# ---------------------------------------------------------------------------
ROLES = ("Customer", "SupportAgent", "PlatformAdmin")


def auth_context():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized authentication headers.")
    return role, uid


def require_roles(*allowed):
    role, uid = auth_context()
    if role not in allowed:
        err("ERR_FORBIDDEN", 403, "Role not permitted for this endpoint.")
    return role, uid


def check_ownership(owner_customer_id, uid):
    if owner_customer_id != uid:
        err("ERR_OWNERSHIP_MISMATCH", 403, "Resource belongs to a different customer.")


# ---------------------------------------------------------------------------
# Body validation (validations priority 1)
# ---------------------------------------------------------------------------
def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


TYPE_CHECKS = {
    "str": lambda v: isinstance(v, str),
    "int": is_int,
    "bool": lambda v: isinstance(v, bool),
    "num": is_num,
    "int_null": lambda v: v is None or is_int(v),
    "str_null": lambda v: v is None or isinstance(v, str),
    "list_str": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
    "date": lambda v: parse_date(v) is not None,
    "datetime": lambda v: parse_dt(v) is not None,
    "any": lambda v: True,
}


def get_body(schema):
    """schema: {field: (type_name, required)}. Returns validated dict."""
    raw = request.get_json(silent=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object.")
    for key in raw:
        if key not in schema:
            err("ERR_INVALID_REQUEST", 400, f"Unknown field: {key}")
    out = {}
    for field, (tname, required) in schema.items():
        if field not in raw or raw[field] is None:
            if required:
                err("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
            out[field] = None
            continue
        val = raw[field]
        if not TYPE_CHECKS[tname](val):
            err("ERR_INVALID_REQUEST", 400, f"Malformed value for field: {field}")
        out[field] = val
    return out


def ignore_body():
    request.get_json(silent=True)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def paginate(items):
    total = len(items)
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", 400, "Invalid limit parameter.")
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", 400, "Invalid offset parameter.")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }


def sorted_items(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Derived fields & helpers
# ---------------------------------------------------------------------------
def product_current_price(product_id):
    """Latest PriceEvent with effective_from <= logical now; None if none."""
    best = None
    for pe in DB["price_events"].values():
        if pe["product_id"] != product_id:
            continue
        eff = pe["_effective_dt"]
        if eff <= now() and (best is None or eff > best["_effective_dt"]):
            best = pe
    return best["price_cents"] if best else None


def product_availability(p):
    if p["discontinued"]:
        return "DISCONTINUED"
    on_hand = sum(
        pl["on_hand_units"]
        for pl in DB["placements"].values()
        if pl["product_id"] == p["id"] and pl["region"] == p["region"]
    )
    return "IN_STOCK" if on_hand > 0 else "OUT_OF_STOCK"


def placement_for(product_id, region):
    for pl in DB["placements"].values():
        if pl["product_id"] == product_id and pl["region"] == region:
            return pl
    return None


def round_half_up_cents(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tier_for_count(n):
    if n >= 5:
        return 0.10
    if n >= 3:
        return 0.05
    return 0.00


def round_half_up_float(x):
    return round_half_up_cents(Decimal(str(x)))


def apply_coupons(gross, codes):
    total = gross
    for code in codes:
        c = coupon_by_code(code)
        if c is None:
            continue
        if c["discount_type"] == "PERCENT":
            total = round_half_up_cents(Decimal(total) * (Decimal(1) - Decimal(str(c["percent_off"]))))
        else:
            total = max(0, total - c["flat_off_cents"])
    return total


def coupon_by_code(code):
    for c in DB["coupons"].values():
        if c["code"] == code:
            return c
    return None


def plan_lines(plan_id):
    return sorted_items([l for l in DB["lines"].values() if l["plan_id"] == plan_id])


def active_line_count(plan_id):
    return sum(
        1
        for l in DB["lines"].values()
        if l["plan_id"] == plan_id
        and l["line_status"] == "SCHEDULED"
        and not l["is_bonus"]
        and l["quantity"] >= 1
    )


def estimate_plan(plan):
    """Recompute active_line_count, tier_discount_pct, estimated_total_cents."""
    lines = [
        l for l in plan_lines(plan["id"])
        if l["line_status"] == "SCHEDULED" and not l["is_bonus"] and l["quantity"] >= 1
    ]
    n = len(lines)
    tier = tier_for_count(n)
    gross = 0
    for l in lines:
        price = product_current_price(l["product_id"]) or 0
        gross += round_half_up_cents(Decimal(price) * Decimal(l["quantity"]) * (Decimal(1) - Decimal(str(tier))))
    plan["active_line_count"] = n
    plan["tier_discount_pct"] = tier
    plan["estimated_total_cents"] = apply_coupons(gross, plan["applied_coupon_codes"])


def create_notification(customer_id, ntype, message, related_plan_id=None):
    rec = {
        "id": new_id(),
        "customer_id": customer_id,
        "notification_type": ntype,
        "message": message,
        "related_plan_id": related_plan_id,
        "created_at": ts(now()),
        "_seq": next_seq(),
    }
    DB["notifications"][rec["id"]] = rec
    return rec


def lazy_offer_expiry(subscription):
    """Expire OFFERED offers whose expires_on < logical today (PRD §3.4)."""
    for offer in sorted_items(DB["offers"].values()):
        if offer["subscription_id"] != subscription["id"]:
            continue
        if offer["offer_status"] != "OFFERED":
            continue
        exp = parse_date(offer["expires_on"])
        if exp is not None and today() > exp:
            offer["offer_status"] = "EXPIRED"
            touch(offer)
            if subscription["status"] == "PENDING_CANCEL":
                subscription["status"] = "CANCELLED"
                touch(subscription)
            create_notification(
                subscription["customer_id"],
                "OFFER_EXPIRED",
                "Your retention offer has expired and the subscription has been cancelled.",
            )


def lazy_expiry_for_customer(customer_id):
    for sub in DB["subscriptions"].values():
        if sub["customer_id"] == customer_id:
            lazy_offer_expiry(sub)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_customer(c):
    return {
        "id": c["id"], "email": c["email"], "full_name": c["full_name"],
        "region": c["region"], "preferred_delivery_day": c["preferred_delivery_day"],
        "account_status": c["account_status"], "credit_balance_cents": c["credit_balance_cents"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def ser_product(p):
    return {
        "id": p["id"], "sku": p["sku"], "name": p["name"], "region": p["region"],
        "subscription_eligible": p["subscription_eligible"], "discontinued": p["discontinued"],
        "substitute_product_id": p["substitute_product_id"],
        "availability_status": product_availability(p),
        "current_price_cents": product_current_price(p["id"]),
        "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
    }


def ser_price_event(pe):
    return {
        "id": pe["id"], "product_id": pe["product_id"], "price_cents": pe["price_cents"],
        "effective_from": pe["effective_from"], "created_at": pe["created_at"],
    }


def ser_placement(pl):
    return {
        "id": pl["id"], "product_id": pl["product_id"], "region": pl["region"],
        "received_total_units": pl["received_total_units"], "on_hand_units": pl["on_hand_units"],
        "reserved_units": pl["reserved_units"], "shipped_units": pl["shipped_units"],
        "created_at": pl["created_at"], "updated_at": pl["updated_at"], "version": pl["version"],
    }


def ser_subscription(s):
    return {
        "id": s["id"], "customer_id": s["customer_id"], "product_id": s["product_id"],
        "cadence_months": s["cadence_months"], "quantity": s["quantity"],
        "start_date": s["start_date"], "next_delivery_date": s["next_delivery_date"],
        "status": s["status"], "price_cap_cents": s["price_cap_cents"],
        "subscribe_price_cents": s["subscribe_price_cents"],
        "created_at": s["created_at"], "updated_at": s["updated_at"], "version": s["version"],
    }


def ser_plan(p):
    return {
        "id": p["id"], "customer_id": p["customer_id"], "delivery_month": p["delivery_month"],
        "delivery_date": p["delivery_date"], "plan_status": p["plan_status"],
        "active_line_count": p["active_line_count"], "tier_discount_pct": p["tier_discount_pct"],
        "estimated_total_cents": p["estimated_total_cents"],
        "charged_total_cents": p["charged_total_cents"],
        "gross_line_total_cents": p["gross_line_total_cents"],
        "refunded_total_cents": p["refunded_total_cents"],
        "applied_coupon_codes": list(p["applied_coupon_codes"]),
        "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
    }


def ser_line(l):
    return {
        "id": l["id"], "plan_id": l["plan_id"], "subscription_id": l["subscription_id"],
        "product_id": l["product_id"], "quantity": l["quantity"], "is_bonus": l["is_bonus"],
        "was_substituted": l["was_substituted"], "line_status": l["line_status"],
        "skip_reason": l["skip_reason"], "unit_price_cents": l["unit_price_cents"],
        "line_charged_cents": l["line_charged_cents"],
        "created_at": l["created_at"], "updated_at": l["updated_at"], "version": l["version"],
    }


def ser_coupon(c):
    return {
        "id": c["id"], "code": c["code"], "discount_type": c["discount_type"],
        "percent_off": c["percent_off"], "flat_off_cents": c["flat_off_cents"],
        "stackable": c["stackable"], "min_subtotal_cents": c["min_subtotal_cents"],
        "valid_from": c["valid_from"], "valid_to": c["valid_to"],
        "coupon_status": c["coupon_status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def ser_promotion(p):
    return {
        "id": p["id"], "bonus_product_id": p["bonus_product_id"],
        "min_line_count": p["min_line_count"], "starts_on": p["starts_on"],
        "ends_on": p["ends_on"], "promotion_status": p["promotion_status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
    }


def ser_offer(o):
    return {
        "id": o["id"], "subscription_id": o["subscription_id"], "offer_type": o["offer_type"],
        "credit_amount_cents": o["credit_amount_cents"], "offer_status": o["offer_status"],
        "expires_on": o["expires_on"],
        "created_at": o["created_at"], "updated_at": o["updated_at"], "version": o["version"],
    }


def ser_claim(c):
    return {
        "id": c["id"], "plan_id": c["plan_id"], "customer_id": c["customer_id"],
        "damaged_line_ids": list(c["damaged_line_ids"]), "claim_status": c["claim_status"],
        "claim_refund_cents": c["claim_refund_cents"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def ser_reshipment(r):
    return {
        "id": r["id"], "claim_id": r["claim_id"],
        "reshipped_line_ids": list(r["reshipped_line_ids"]),
        "reshipment_status": r["reshipment_status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_forecast(f):
    return {
        "id": f["id"], "product_id": f["product_id"], "region": f["region"],
        "forecast_month": f["forecast_month"], "committed_units": f["committed_units"],
        "provisional_units": f["provisional_units"],
        "created_at": f["created_at"], "updated_at": f["updated_at"], "version": f["version"],
    }


def ser_notification(n):
    return {
        "id": n["id"], "customer_id": n["customer_id"],
        "notification_type": n["notification_type"], "message": n["message"],
        "related_plan_id": n["related_plan_id"], "created_at": n["created_at"],
    }


# ---------------------------------------------------------------------------
# Resource fetchers (existence, left-to-right)
# ---------------------------------------------------------------------------
def get_customer_or_404(cid):
    c = DB["customers"].get(cid)
    if c is None:
        err("ERR_CUSTOMER_NOT_FOUND", 404, "Customer id does not exist.")
    return c


def get_product_or_404(pid):
    p = DB["products"].get(pid)
    if p is None:
        err("ERR_PRODUCT_NOT_FOUND", 404, "Product id does not exist.")
    return p


def get_subscription_or_404(sid):
    s = DB["subscriptions"].get(sid)
    if s is None:
        err("ERR_SUBSCRIPTION_NOT_FOUND", 404, "Subscription id does not exist.")
    return s


def get_plan_or_404(pid):
    p = DB["plans"].get(pid)
    if p is None:
        err("ERR_PLAN_NOT_FOUND", 404, "DeliveryPlan id does not exist.")
    return p


def get_line_or_404(lid):
    l = DB["lines"].get(lid)
    if l is None:
        err("ERR_LINE_NOT_FOUND", 404, "PlanLine id does not exist.")
    return l


def get_coupon_or_404(cid):
    c = DB["coupons"].get(cid)
    if c is None:
        err("ERR_COUPON_NOT_FOUND", 404, "Coupon does not exist.")
    return c


def get_promotion_or_404(pid):
    p = DB["promotions"].get(pid)
    if p is None:
        err("ERR_PROMOTION_NOT_FOUND", 404, "Promotion id does not exist.")
    return p


def get_offer_or_404(oid):
    o = DB["offers"].get(oid)
    if o is None:
        err("ERR_OFFER_NOT_FOUND", 404, "RetentionOffer id does not exist.")
    return o


def get_claim_or_404(cid):
    c = DB["claims"].get(cid)
    if c is None:
        err("ERR_CLAIM_NOT_FOUND", 404, "DamageClaim id does not exist.")
    return c


def get_reshipment_or_404(rid):
    r = DB["reshipments"].get(rid)
    if r is None:
        err("ERR_RESHIPMENT_NOT_FOUND", 404, "Reshipment id does not exist.")
    return r


def get_forecast_or_404(fid):
    f = DB["forecasts"].get(fid)
    if f is None:
        err("ERR_FORECAST_NOT_FOUND", 404, "DemandForecast id does not exist.")
    return f


# ===========================================================================
# CUSTOMERS
# ===========================================================================
@app.route("/sns/customers", methods=["POST"])
def create_customer():
    body = get_body({
        "email": ("str", True), "full_name": ("str", True), "region": ("str", True),
        "preferred_delivery_day": ("int", False),
    })
    require_roles("PlatformAdmin")
    pdd = body["preferred_delivery_day"] if body["preferred_delivery_day"] is not None else 15
    if pdd < 1 or pdd > 28:
        err("ERR_INVALID_DELIVERY_DAY", 422, "preferred_delivery_day outside 1..28.")
    for c in DB["customers"].values():
        if c["email"] == body["email"]:
            err("ERR_INVALID_REQUEST", 400, "email must be unique across customers.")
    rec = make_record({
        "email": body["email"], "full_name": body["full_name"], "region": body["region"],
        "preferred_delivery_day": pdd, "account_status": "ACTIVE", "credit_balance_cents": 0,
    })
    DB["customers"][rec["id"]] = rec
    return ok(ser_customer(rec), 201)


@app.route("/sns/customers/<cid>", methods=["GET"])
def get_customer(cid):
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    if role == "Customer":
        check_ownership(cid, uid)
    c = get_customer_or_404(cid)
    return ok(ser_customer(c))


@app.route("/sns/customers/<cid>", methods=["PATCH"])
def patch_customer(cid):
    body = get_body({"preferred_delivery_day": ("int", False)})
    role, uid = require_roles("PlatformAdmin", "Customer")
    if role == "Customer":
        check_ownership(cid, uid)
    c = get_customer_or_404(cid)
    if body["preferred_delivery_day"] is not None:
        pdd = body["preferred_delivery_day"]
        if pdd < 1 or pdd > 28:
            err("ERR_INVALID_DELIVERY_DAY", 422, "preferred_delivery_day outside 1..28.")
        c["preferred_delivery_day"] = pdd
        touch(c)
    return ok(ser_customer(c))


@app.route("/sns/customers/<cid>/suspend", methods=["POST"])
def suspend_customer(cid):
    ignore_body()
    require_roles("PlatformAdmin")
    c = get_customer_or_404(cid)
    if c["account_status"] != "ACTIVE":
        err("ERR_CUSTOMER_SUSPENDED", 409, "Customer account is not ACTIVE.")
    c["account_status"] = "SUSPENDED"
    touch(c)
    return ok(ser_customer(c))


@app.route("/sns/customers/<cid>/unsuspend", methods=["POST"])
def unsuspend_customer(cid):
    ignore_body()
    require_roles("PlatformAdmin")
    c = get_customer_or_404(cid)
    if c["account_status"] != "SUSPENDED":
        err("ERR_CUSTOMER_SUSPENDED", 409, "Customer account is not SUSPENDED.")
    c["account_status"] = "ACTIVE"
    touch(c)
    return ok(ser_customer(c))


@app.route("/sns/customers/<cid>/subscriptions", methods=["GET"])
def list_customer_subscriptions(cid):
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    if role == "Customer":
        check_ownership(cid, uid)
    get_customer_or_404(cid)
    items = [ser_subscription(s) for s in sorted_items(DB["subscriptions"].values()) if s["customer_id"] == cid]
    page, pag = paginate(items)
    return ok(page, 200, "array", pag)


@app.route("/sns/customers/<cid>/delivery-plans", methods=["GET"])
def list_customer_plans(cid):
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    if role == "Customer":
        check_ownership(cid, uid)
    get_customer_or_404(cid)
    items = [ser_plan(p) for p in sorted_items(DB["plans"].values()) if p["customer_id"] == cid]
    page, pag = paginate(items)
    return ok(page, 200, "array", pag)


@app.route("/sns/customers/<cid>/notifications", methods=["GET"])
def list_customer_notifications(cid):
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    if role == "Customer":
        check_ownership(cid, uid)
    get_customer_or_404(cid)
    lazy_expiry_for_customer(cid)
    ntype = request.args.get("notification_type")
    items = [
        ser_notification(n) for n in sorted_items(DB["notifications"].values())
        if n["customer_id"] == cid and (ntype is None or n["notification_type"] == ntype)
    ]
    page, pag = paginate(items)
    return ok(page, 200, "array", pag)


@app.route("/sns/customers/<cid>/damage-claims", methods=["GET"])
def list_customer_claims(cid):
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    if role == "Customer":
        check_ownership(cid, uid)
    get_customer_or_404(cid)
    items = [ser_claim(c) for c in sorted_items(DB["claims"].values()) if c["customer_id"] == cid]
    page, pag = paginate(items)
    return ok(page, 200, "array", pag)


# ===========================================================================
# PRODUCTS
# ===========================================================================
@app.route("/sns/products", methods=["POST"])
def create_product():
    body = get_body({
        "sku": ("str", True), "name": ("str", True), "region": ("str", True),
        "subscription_eligible": ("bool", False), "discontinued": ("bool", False),
        "substitute_product_id": ("str_null", False),
    })
    require_roles("PlatformAdmin")
    if body["substitute_product_id"] is not None:
        get_product_or_404(body["substitute_product_id"])
    for p in DB["products"].values():
        if p["sku"] == body["sku"]:
            err("ERR_INVALID_REQUEST", 400, "sku must be unique across the catalog.")
    rec = make_record({
        "sku": body["sku"], "name": body["name"], "region": body["region"],
        "subscription_eligible": True if body["subscription_eligible"] is None else body["subscription_eligible"],
        "discontinued": False if body["discontinued"] is None else body["discontinued"],
        "substitute_product_id": body["substitute_product_id"],
    })
    DB["products"][rec["id"]] = rec
    return ok(ser_product(rec), 201)


@app.route("/sns/products/<pid>", methods=["GET"])
def get_product(pid):
    require_roles("PlatformAdmin", "SupportAgent", "Customer")
    p = get_product_or_404(pid)
    return ok(ser_product(p))


@app.route("/sns/products", methods=["GET"])
def list_products():
    require_roles("PlatformAdmin", "SupportAgent", "Customer")
    region = request.args.get("region")
    sub_id = request.args.get("substitute_product_id")
    items = []
    for p in sorted_items(DB["products"].values()):
        if region is not None and p["region"] != region:
            continue
        if sub_id is not None and p["substitute_product_id"] != sub_id:
            continue
        items.append(ser_product(p))
    page, pag = paginate(items)
    return ok(page, 200, "array", pag)


@app.route("/sns/products/<pid>", methods=["PATCH"])
def patch_product(pid):
    body = get_body({
        "discontinued": ("bool", False), "substitute_product_id": ("str_null", False),
        "subscription_eligible": ("bool", False),
    })
    require_roles("PlatformAdmin")
    p = get_product_or_404(pid)
    if body["substitute_product_id"] is not None:
        get_product_or_404(body["substitute_product_id"])
    changed = False
    if body["discontinued"] is not None:
        p["discontinued"] = body["discontinued"]
        changed = True
    if "substitute_product_id" in (request.get_json(silent=True) or {}):
        p["substitute_product_id"] = body["substitute_product_id"]
        changed = True
    if body["subscription_eligible"] is not None:
        p["subscription_eligible"] = body["subscription_eligible"]
        changed = True
    if changed:
        touch(p)
    return ok(ser_product(p))


@app.route("/sns/products/<pid>/price-events", methods=["POST"])
def create_price_event(pid):
    body = get_body({"price_cents": ("int", True), "effective_from": ("datetime", True)})
    require_roles("PlatformAdmin")
    p = get_product_or_404(pid)
    if body["price_cents"] <= 0:
        err("ERR_INVALID_REQUEST", 400, "price_cents must be positive.")
    eff_dt = parse_dt(body["effective_from"])
    for pe in DB["price_events"].values():
        if pe["product_id"] == pid and eff_dt <= pe["_effective_dt"]:
            err("ERR_PRICE_EVENT_NOT_MONOTONIC", 409,
                "effective_from must be strictly greater than every existing event for the product.")
    rec = {
        "id": new_id(), "product_id": pid, "price_cents": body["price_cents"],
        "effective_from": iso_dt_str(eff_dt), "created_at": ts(now()),
        "_effective_dt": eff_dt, "_seq": next_seq(),
    }
    DB["price_events"][rec["id"]] = rec
    touch(p)  # current_price_cents recomputed (derived live)
    return ok(ser_price_event(rec), 201)


@app.route("/sns/products/<pid>/price-events", methods=["GET"])
def list_price_events(pid):
    require_roles("PlatformAdmin", "SupportAgent", "Customer")
    get_product_or_404(pid)
    items = [ser_price_event(pe) for pe in sorted_items(DB["price_events"].values()) if pe["product_id"] == pid]
    page, pag = paginate(items)
    return ok(page, 200, "array", pag)


@app.route("/sns/products/<pid>/subscriptions", methods=["GET"])
def list_product_subscriptions(pid):
    require_roles("PlatformAdmin", "SupportAgent")
    get_product_or_404(pid)
    items = [ser_subscription(s) for s in sorted_items(DB["subscriptions"].values()) if s["product_id"] == pid]
    page, pag = paginate(items)
    return ok(page, 200, "array", pag)


# ===========================================================================
# INVENTORY PLACEMENTS
# ===========================================================================
@app.route("/sns/inventory-placements", methods=["POST"])
def create_placement():
    body = get_body({"product_id": ("str", True), "region": ("str", True)})
    require_roles("PlatformAdmin")
    get_product_or_404(body["product_id"])
    if placement_for(body["product_id"], body["region"]) is not None:
        err("ERR_INVALID_REQUEST", 400, "A placement already exists for this product and region.")
    rec = make_record({
        "product_id": body["product_id"], "region": body["region"],
        "received_total_units": 0, "on_hand_units": 0, "reserved_units": 0, "shipped_units": 0,
    })
    DB["placements"][rec["id"]] = rec
    return ok(ser_placement(rec), 201)


@app.route("/sns/inventory-placements/<pid>", methods=["GET"])
def get_placement(pid):
    require_roles("PlatformAdmin", "SupportAgent")
    pl = DB["placements"].get(pid)
    if pl is None:
        err("ERR_PRODUCT_NOT_FOUND", 404, "InventoryPlacement id does not exist.")
    return ok(ser_placement(pl))


@app.route("/sns/inventory-placements", methods=["GET"])
def list_placements():
    require_roles("PlatformAdmin", "SupportAgent")
    product_id = request.args.get("product_id")
    region = request.args.get("region")
    items = []
    for pl in sorted_items(DB["placements"].values()):
        if product_id is not None and pl["product_id"] != product_id:
            continue
        if region is not None and pl["region"] != region:
            continue
        items.append(ser_placement(pl))
    page, pag = paginate(items)
    return ok(page, 200, "array", pag)


@app.route("/sns/inventory-placements/<pid>/receive", methods=["POST"])
def receive_placement(pid):
    body = get_body({"units": ("int", True)})
    require_roles("PlatformAdmin")
    pl = DB["placements"].get(pid)
    if pl is None:
        err("ERR_PRODUCT_NOT_FOUND", 404, "InventoryPlacement id does not exist.")
    if body["units"] <= 0:
        err("ERR_QUANTITY_OUT_OF_RANGE", 422, "receive units must be > 0.")
    pl["received_total_units"] += body["units"]
    pl["on_hand_units"] += body["units"]
    touch(pl)
    return ok(ser_placement(pl))


# ===========================================================================
# SUBSCRIPTIONS
# ===========================================================================
@app.route("/sns/subscriptions", methods=["POST"])
def create_subscription():
    body = get_body({
        "customer_id": ("str", True), "product_id": ("str", True),
        "cadence_months": ("int", True), "quantity": ("int", True),
        "start_date": ("date", True), "price_cap_cents": ("int_null", False),
    })
    role, uid = require_roles("Customer")
    if body["price_cap_cents"] is not None and body["price_cap_cents"] <= 0:
        err("ERR_INVALID_REQUEST", 400, "price_cap_cents must be a positive integer.")
    # ownership (priority 4) before existence (priority 5)
    if body["customer_id"] != uid:
        err("ERR_OWNERSHIP_MISMATCH", 403, "customer_id must equal the caller's X-User-ID.")
    cust = get_customer_or_404(body["customer_id"])
    prod = get_product_or_404(body["product_id"])
    if cust["account_status"] == "SUSPENDED":
        err("ERR_CUSTOMER_SUSPENDED", 409, "Customer account SUSPENDED: subscription create is blocked.")
    if body["cadence_months"] < 1 or body["cadence_months"] > 6:
        err("ERR_INVALID_CADENCE", 422, "cadence_months outside 1..6.")
    if body["quantity"] < 1 or body["quantity"] > 30:
        err("ERR_QUANTITY_OUT_OF_RANGE", 422, "quantity outside 1..30.")
    if prod["discontinued"] or not prod["subscription_eligible"]:
        err("ERR_PRODUCT_NOT_SUBSCRIBABLE", 422, "Product discontinued or not subscription_eligible.")
    price = product_current_price(prod["id"])
    if price is None:
        err("ERR_PRODUCT_WITHOUT_PRICE", 422, "Product has no PriceEvent effective at the logical present.")
    start = parse_date(body["start_date"])
    if start < today() + timedelta(days=2):
        err("ERR_START_DATE_TOO_SOON", 422, "start_date earlier than logical today + 2 days.")
    rec = make_record({
        "customer_id": cust["id"], "product_id": prod["id"],
        "cadence_months": body["cadence_months"], "quantity": body["quantity"],
        "start_date": start.isoformat(), "next_delivery_date": start.isoformat(),
        "status": "ACTIVE", "price_cap_cents": body["price_cap_cents"],
        "subscribe_price_cents": price,
    })
    DB["subscriptions"][rec["id"]] = rec
    return ok(ser_subscription(rec), 201)


@app.route("/sns/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    s = get_subscription_or_404(sid)
    if role == "Customer":
        check_ownership(s["customer_id"], uid)
    lazy_offer_expiry(s)
    return ok(ser_subscription(s))


@app.route("/sns/subscriptions/<sid>", methods=["PATCH"])
def patch_subscription(sid):
    body = get_body({
        "cadence_months": ("int", False), "quantity": ("int", False),
        "price_cap_cents": ("int_null", False),
    })
    role, uid = require_roles("Customer")
    s = get_subscription_or_404(sid)
    check_ownership(s["customer_id"], uid)
    lazy_offer_expiry(s)
    if s["status"] != "ACTIVE":
        err("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Subscription must be ACTIVE to patch.")
    if body["cadence_months"] is not None and not (1 <= body["cadence_months"] <= 6):
        err("ERR_INVALID_CADENCE", 422, "cadence_months outside 1..6.")
    if body["quantity"] is not None and not (1 <= body["quantity"] <= 30):
        err("ERR_QUANTITY_OUT_OF_RANGE", 422, "quantity outside 1..30.")
    if body["price_cap_cents"] is not None and body["price_cap_cents"] <= 0:
        err("ERR_INVALID_REQUEST", 400, "price_cap_cents must be a positive integer.")
    raw = request.get_json(silent=True) or {}
    changed = False
    if body["cadence_months"] is not None and body["cadence_months"] != s["cadence_months"]:
        old_cad = s["cadence_months"]
        new_cad = body["cadence_months"]
        anchor = add_months_clamped(parse_date(s["next_delivery_date"]), -old_cad)
        ndd = add_months_clamped(anchor, new_cad)
        min_date = today() + timedelta(days=2)
        while ndd < min_date:
            ndd = add_months_clamped(ndd, new_cad)
        s["next_delivery_date"] = ndd.isoformat()
        s["cadence_months"] = new_cad
        changed = True
    if body["quantity"] is not None:
        s["quantity"] = body["quantity"]
        changed = True
    if "price_cap_cents" in raw:
        s["price_cap_cents"] = body["price_cap_cents"]
        changed = True
    if changed:
        touch(s)
    return ok(ser_subscription(s))


@app.route("/sns/subscriptions/<sid>/pause", methods=["POST"])
def pause_subscription(sid):
    ignore_body()
    role, uid = require_roles("Customer")
    s = get_subscription_or_404(sid)
    check_ownership(s["customer_id"], uid)
    lazy_offer_expiry(s)
    if s["status"] != "ACTIVE":
        err("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Pause requires an ACTIVE subscription.")
    s["status"] = "PAUSED"
    touch(s)
    return ok(ser_subscription(s))


@app.route("/sns/subscriptions/<sid>/resume", methods=["POST"])
def resume_subscription(sid):
    ignore_body()
    role, uid = require_roles("Customer")
    s = get_subscription_or_404(sid)
    check_ownership(s["customer_id"], uid)
    lazy_offer_expiry(s)
    if s["status"] != "PAUSED":
        err("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Resume requires a PAUSED subscription.")
    cust = get_customer_or_404(s["customer_id"])
    if cust["account_status"] == "SUSPENDED":
        err("ERR_CUSTOMER_SUSPENDED", 409, "Customer account SUSPENDED: resume is blocked.")
    s["status"] = "ACTIVE"
    ndd = parse_date(s["next_delivery_date"])
    min_date = today() + timedelta(days=2)
    while ndd < min_date:
        ndd = add_months_clamped(ndd, s["cadence_months"])
    s["next_delivery_date"] = ndd.isoformat()
    touch(s)
    return ok(ser_subscription(s))


@app.route("/sns/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    ignore_body()
    role, uid = require_roles("Customer")
    s = get_subscription_or_404(sid)
    check_ownership(s["customer_id"], uid)
    lazy_offer_expiry(s)
    if s["status"] not in ("ACTIVE", "PAUSED"):
        err("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Cancel requires an ACTIVE or PAUSED subscription.")
    s["status"] = "PENDING_CANCEL"
    touch(s)
    offer = make_record({
        "subscription_id": s["id"], "offer_type": "CREDIT", "credit_amount_cents": 500,
        "offer_status": "OFFERED", "expires_on": (today() + timedelta(days=7)).isoformat(),
    })
    DB["offers"][offer["id"]] = offer
    create_notification(s["customer_id"], "OFFER_CREATED",
                        "A retention offer of 500 cents goodwill credit is available if you keep your subscription.")
    return ok(ser_subscription(s))


@app.route("/sns/subscriptions/<sid>/retention-offers", methods=["GET"])
def list_subscription_offers(sid):
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    s = get_subscription_or_404(sid)
    if role == "Customer":
        check_ownership(s["customer_id"], uid)
    lazy_offer_expiry(s)
    items = [ser_offer(o) for o in sorted_items(DB["offers"].values()) if o["subscription_id"] == sid]
    page, pag = paginate(items)
    return ok(page, 200, "array", pag)


# ===========================================================================
# RETENTION OFFERS
# ===========================================================================
@app.route("/sns/retention-offers/<oid>", methods=["GET"])
def get_offer(oid):
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    o = get_offer_or_404(oid)
    s = get_subscription_or_404(o["subscription_id"])
    if role == "Customer":
        check_ownership(s["customer_id"], uid)
    lazy_offer_expiry(s)
    return ok(ser_offer(o))


@app.route("/sns/retention-offers/<oid>/accept", methods=["POST"])
def accept_offer(oid):
    ignore_body()
    role, uid = require_roles("Customer")
    o = get_offer_or_404(oid)
    s = get_subscription_or_404(o["subscription_id"])
    check_ownership(s["customer_id"], uid)
    lazy_offer_expiry(s)
    if o["offer_status"] != "OFFERED":
        err("ERR_OFFER_NOT_OPEN", 409, "RetentionOffer not in OFFERED status.")
    o["offer_status"] = "ACCEPTED"
    touch(o)
    s["status"] = "ACTIVE"
    touch(s)
    cust = get_customer_or_404(s["customer_id"])
    cust["credit_balance_cents"] += 500
    touch(cust)
    return ok(ser_offer(o))


@app.route("/sns/retention-offers/<oid>/decline", methods=["POST"])
def decline_offer(oid):
    ignore_body()
    role, uid = require_roles("Customer")
    o = get_offer_or_404(oid)
    s = get_subscription_or_404(o["subscription_id"])
    check_ownership(s["customer_id"], uid)
    lazy_offer_expiry(s)
    if o["offer_status"] != "OFFERED":
        err("ERR_OFFER_NOT_OPEN", 409, "RetentionOffer not in OFFERED status.")
    o["offer_status"] = "DECLINED"
    touch(o)
    s["status"] = "CANCELLED"
    touch(s)
    return ok(ser_offer(o))


# ===========================================================================
# COUPONS
# ===========================================================================
@app.route("/sns/coupons", methods=["POST"])
def create_coupon():
    body = get_body({
        "code": ("str", True), "discount_type": ("str", True),
        "valid_from": ("date", True), "valid_to": ("date", True),
        "percent_off": ("num", False), "flat_off_cents": ("int", False),
        "stackable": ("bool", False), "min_subtotal_cents": ("int", False),
    })
    require_roles("PlatformAdmin")
    if body["discount_type"] not in ("PERCENT", "FLAT"):
        err("ERR_INVALID_REQUEST", 400, "discount_type must be PERCENT or FLAT.")
    if body["discount_type"] == "PERCENT":
        if body["percent_off"] is None or body["flat_off_cents"] is not None:
            err("ERR_INVALID_REQUEST", 400, "PERCENT coupons require percent_off only.")
        if not (0 < body["percent_off"] <= 1):
            err("ERR_INVALID_REQUEST", 400, "percent_off must be a fraction in (0, 1].")
    else:
        if body["flat_off_cents"] is None or body["percent_off"] is not None:
            err("ERR_INVALID_REQUEST", 400, "FLAT coupons require flat_off_cents only.")
        if body["flat_off_cents"] <= 0:
            err("ERR_INVALID_REQUEST", 400, "flat_off_cents must be positive.")
    if body["min_subtotal_cents"] is not None and body["min_subtotal_cents"] < 0:
        err("ERR_INVALID_REQUEST", 400, "min_subtotal_cents must be >= 0.")
    if coupon_by_code(body["code"]) is not None:
        err("ERR_INVALID_REQUEST", 400, "code must be unique.")
    rec = make_record({
        "code": body["code"], "discount_type": body["discount_type"],
        "percent_off": body["percent_off"], "flat_off_cents": body["flat_off_cents"],
        "stackable": False if body["stackable"] is None else body["stackable"],
        "min_subtotal_cents": 0 if body["min_subtotal_cents"] is None else body["min_subtotal_cents"],
        "valid_from": parse_date(body["valid_from"]).isoformat(),
        "valid_to": parse_date(body["valid_to"]).isoformat(),
        "coupon_status": "ACTIVE",
    })
    DB["coupons"][rec["id"]] = rec
    return ok(ser_coupon(rec), 201)


@app.route("/sns/coupons/<cid>", methods=["GET"])
def get_coupon(cid):
    require_roles("PlatformAdmin", "SupportAgent", "Customer")
    c = get_coupon_or_404(cid)
    return ok(ser_coupon(c))


@app.route("/sns/coupons/<cid>/disable", methods=["POST"])
def disable_coupon(cid):
    ignore_body()
    require_roles("PlatformAdmin")
    c = get_coupon_or_404(cid)
    if c["coupon_status"] != "ACTIVE":
        err("ERR_INVALID_REQUEST", 400, "Coupon is not ACTIVE.")
    c["coupon_status"] = "DISABLED"
    touch(c)
    return ok(ser_coupon(c))


# ===========================================================================
# PROMOTIONS
# ===========================================================================
@app.route("/sns/promotions", methods=["POST"])
def create_promotion():
    body = get_body({
        "bonus_product_id": ("str", True), "min_line_count": ("int", True),
        "starts_on": ("date", True), "ends_on": ("date", True),
    })
    require_roles("PlatformAdmin")
    get_product_or_404(body["bonus_product_id"])
    if body["min_line_count"] < 1:
        err("ERR_INVALID_REQUEST", 400, "min_line_count must be >= 1.")
    starts = parse_date(body["starts_on"])
    ends = parse_date(body["ends_on"])
    if not (starts < ends):
        err("ERR_INVALID_REQUEST", 400, "starts_on must be before ends_on.")
    for p in DB["promotions"].values():
        if p["bonus_product_id"] != body["bonus_product_id"]:
            continue
        if p["promotion_status"] != "ACTIVE":
            continue
        ps, pe = parse_date(p["starts_on"]), parse_date(p["ends_on"])
        if starts < pe and ps < ends:
            err("ERR_PROMOTION_WINDOW_OVERLAP", 409,
                "An ACTIVE promotion for the same bonus product has an overlapping window.")
    rec = make_record({
        "bonus_product_id": body["bonus_product_id"], "min_line_count": body["min_line_count"],
        "starts_on": starts.isoformat(), "ends_on": ends.isoformat(),
        "promotion_status": "ACTIVE",
    })
    DB["promotions"][rec["id"]] = rec
    return ok(ser_promotion(rec), 201)


@app.route("/sns/promotions/<pid>", methods=["GET"])
def get_promotion(pid):
    require_roles("PlatformAdmin", "SupportAgent")
    p = get_promotion_or_404(pid)
    return ok(ser_promotion(p))


@app.route("/sns/promotions", methods=["GET"])
def list_promotions():
    require_roles("PlatformAdmin", "SupportAgent")
    bp = request.args.get("bonus_product_id")
    items = [ser_promotion(p) for p in sorted_items(DB["promotions"].values())
             if bp is None or p["bonus_product_id"] == bp]
    page, pag = paginate(items)
    return ok(page, 200, "array", pag)


@app.route("/sns/promotions/<pid>/disable", methods=["POST"])
def disable_promotion(pid):
    ignore_body()
    require_roles("PlatformAdmin")
    p = get_promotion_or_404(pid)
    if p["promotion_status"] != "ACTIVE":
        err("ERR_INVALID_REQUEST", 400, "Promotion is not ACTIVE.")
    p["promotion_status"] = "DISABLED"
    touch(p)
    return ok(ser_promotion(p))


# ===========================================================================
# OPS: generate plans / forecasts
# ===========================================================================
@app.route("/sns/ops/generate-plans", methods=["POST"])
def generate_plans():
    body = get_body({"delivery_month": ("str", True)})
    require_roles("PlatformAdmin")
    if not re.fullmatch(r"\d{4}-\d{2}", body["delivery_month"] or ""):
        err("ERR_INVALID_REQUEST", 400, "delivery_month must be a YYYY-MM string.")
    try:
        m_start, m_end = month_bounds(body["delivery_month"])
    except (ValueError, TypeError):
        err("ERR_INVALID_REQUEST", 400, "delivery_month must be a valid YYYY-MM month.")
    created = []
    for cust in sorted_items(DB["customers"].values()):
        if cust["account_status"] != "ACTIVE":
            continue
        has_plan = any(
            p["customer_id"] == cust["id"] and p["delivery_month"] == body["delivery_month"]
            for p in DB["plans"].values()
        )
        if has_plan:
            continue
        eligible = []
        for s in sorted_items(DB["subscriptions"].values()):
            if s["customer_id"] != cust["id"] or s["status"] != "ACTIVE":
                continue
            ndd = parse_date(s["next_delivery_date"])
            if m_start <= ndd <= m_end:
                eligible.append(s)
        if not eligible:
            continue
        delivery_date = date(m_start.year, m_start.month, cust["preferred_delivery_day"])
        plan = make_record({
            "customer_id": cust["id"], "delivery_month": body["delivery_month"],
            "delivery_date": delivery_date.isoformat(), "plan_status": "OPEN",
            "active_line_count": 0, "tier_discount_pct": 0.00,
            "estimated_total_cents": 0, "charged_total_cents": None,
            "gross_line_total_cents": 0, "refunded_total_cents": 0,
            "applied_coupon_codes": [],
        })
        DB["plans"][plan["id"]] = plan
        for s in eligible:
            line = make_record({
                "plan_id": plan["id"], "subscription_id": s["id"], "product_id": s["product_id"],
                "quantity": s["quantity"], "is_bonus": False, "was_substituted": False,
                "line_status": "SCHEDULED", "skip_reason": None,
                "unit_price_cents": None, "line_charged_cents": None,
            })
            DB["lines"][line["id"]] = line
            s["next_delivery_date"] = add_months_clamped(
                parse_date(s["next_delivery_date"]), s["cadence_months"]).isoformat()
            touch(s)
        estimate_plan(plan)
        touch(plan)
        created.append(plan)
    return ok([ser_plan(p) for p in created], 201, "array")


@app.route("/sns/ops/recompute-forecasts", methods=["POST"])
def recompute_forecasts():
    body = get_body({"region": ("str", True), "forecast_month": ("str", True)})
    require_roles("PlatformAdmin")
    if not re.fullmatch(r"\d{4}-\d{2}", body["forecast_month"] or ""):
        err("ERR_INVALID_REQUEST", 400, "forecast_month must be a YYYY-MM string.")
    try:
        m_start, m_end = month_bounds(body["forecast_month"])
    except (ValueError, TypeError):
        err("ERR_INVALID_REQUEST", 400, "forecast_month must be a valid YYYY-MM month.")
    results = []
    for prod in sorted_items(DB["products"].values()):
        if prod["region"] != body["region"]:
            continue
        committed = 0
        paused_qty = 0
        for s in DB["subscriptions"].values():
            if s["product_id"] != prod["id"]:
                continue
            ndd = parse_date(s["next_delivery_date"])
            if not (m_start <= ndd <= m_end):
                continue
            if s["status"] == "ACTIVE":
                committed += s["quantity"]
            elif s["status"] == "PAUSED":
                paused_qty += s["quantity"]
        provisional = committed + (Decimal(paused_qty) * Decimal("0.5")).to_integral_value(rounding="ROUND_FLOOR")
        provisional = int(provisional)
        key = (prod["id"], body["region"], body["forecast_month"])
        existing = None
        for f in DB["forecasts"].values():
            if (f["product_id"], f["region"], f["forecast_month"]) == key:
                existing = f
                break
        if existing is None:
            existing = make_record({
                "product_id": prod["id"], "region": body["region"],
                "forecast_month": body["forecast_month"],
                "committed_units": committed, "provisional_units": provisional,
            })
            DB["forecasts"][existing["id"]] = existing
        else:
            existing["committed_units"] = committed
            existing["provisional_units"] = provisional
            touch(existing)
        results.append(existing)
    return ok([ser_forecast(f) for f in results], 200, "array")


@app.route("/sns/demand-forecasts", methods=["GET"])
def list_forecasts():
    require_roles("PlatformAdmin", "SupportAgent")
    product_id = request.args.get("product_id")
    region = request.args.get("region")
    fm = request.args.get("forecast_month")
    items = []
    for f in sorted_items(DB["forecasts"].values()):
        if product_id is not None and f["product_id"] != product_id:
            continue
        if region is not None and f["region"] != region:
            continue
        if fm is not None and f["forecast_month"] != fm:
            continue
        items.append(ser_forecast(f))
    page, pag = paginate(items)
    return ok(page, 200, "array", pag)


@app.route("/sns/demand-forecasts/<fid>", methods=["GET"])
def get_forecast(fid):
    require_roles("PlatformAdmin", "SupportAgent")
    f = get_forecast_or_404(fid)
    return ok(ser_forecast(f))


# ===========================================================================
# DELIVERY PLANS
# ===========================================================================
def plan_for_customer_scoped(pid, role, uid):
    plan = get_plan_or_404(pid)
    if role == "Customer":
        check_ownership(plan["customer_id"], uid)
    return plan


@app.route("/sns/delivery-plans/<pid>", methods=["GET"])
def get_plan(pid):
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    plan = plan_for_customer_scoped(pid, role, uid)
    return ok(ser_plan(plan))


@app.route("/sns/delivery-plans/<pid>/lines", methods=["GET"])
def list_plan_lines(pid):
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    plan = plan_for_customer_scoped(pid, role, uid)
    items = [ser_line(l) for l in plan_lines(plan["id"])]
    page, pag = paginate(items)
    return ok(page, 200, "array", pag)


def evaluate_line_availability(plan, line, customer, notify_cap):
    """Lock/refresh steps 1-3 for one SCHEDULED non-bonus line. Returns True if still SCHEDULED."""
    prod = DB["products"].get(line["product_id"])
    sub = DB["subscriptions"].get(line["subscription_id"])
    cap = sub["price_cap_cents"] if sub else None
    placement = placement_for(prod["id"], customer["region"]) if prod else None
    on_hand = placement["on_hand_units"] if placement else 0
    if on_hand < line["quantity"]:
        substituted = False
        if prod and prod["substitute_product_id"]:
            sp = DB["products"].get(prod["substitute_product_id"])
            if sp is not None:
                sp_placement = placement_for(sp["id"], customer["region"])
                sp_on_hand = sp_placement["on_hand_units"] if sp_placement else 0
                sp_price = product_current_price(sp["id"])
                sp_avail = product_availability(sp) == "IN_STOCK"
                cap_ok = sp_price is not None and (cap is None or sp_price <= cap)
                if sp_avail and sp_on_hand >= line["quantity"] and cap_ok:
                    line["product_id"] = sp["id"]
                    line["was_substituted"] = True
                    touch(line)
                    prod = sp
                    substituted = True
        if not substituted:
            line["line_status"] = "AUTO_SKIPPED"
            line["skip_reason"] = "UNAVAILABLE"
            touch(line)
            return False
    # step 2: price-at-ship on (possibly substituted) product
    price = product_current_price(line["product_id"])
    if price is not None:
        line["unit_price_cents"] = price
    # step 3: cap check (pre-tier, equality passes)
    if cap is not None and price is not None and price > cap:
        line["line_status"] = "AUTO_SKIPPED"
        line["skip_reason"] = "PRICE_CAP"
        touch(line)
        if notify_cap:
            create_notification(
                customer["id"], "PRICE_CAP_SKIP",
                "A subscription line was skipped because its price exceeded your price cap.",
                related_plan_id=plan["id"],
            )
        return False
    touch(line)
    return True


def heal_auto_skipped(plan, customer):
    """Refresh only: restore AUTO_SKIPPED lines whose conditions healed (PRD §3.10)."""
    for line in plan_lines(plan["id"]):
        if line["line_status"] != "AUTO_SKIPPED" or line["is_bonus"]:
            continue
        sub = DB["subscriptions"].get(line["subscription_id"])
        cap = sub["price_cap_cents"] if sub else None
        prod = DB["products"].get(line["product_id"])
        if prod is None:
            continue
        price = product_current_price(prod["id"])
        placement = placement_for(prod["id"], customer["region"])
        on_hand = placement["on_hand_units"] if placement else 0
        cap_ok = cap is None or (price is not None and price <= cap)
        stock_ok = product_availability(prod) == "IN_STOCK" and on_hand >= line["quantity"]
        if cap_ok and stock_ok and price is not None:
            line["line_status"] = "SCHEDULED"
            line["skip_reason"] = None
            touch(line)


@app.route("/sns/delivery-plans/<pid>/refresh", methods=["POST"])
def refresh_plan(pid):
    body = get_body({"expected_plan_version": ("int", True)})
    role, uid = require_roles("Customer")
    plan = get_plan_or_404(pid)
    check_ownership(plan["customer_id"], uid)
    if plan["plan_status"] != "OPEN":
        err("ERR_PLAN_NOT_OPEN", 409, "Plan must be OPEN to refresh.")
    if body["expected_plan_version"] != plan["version"]:
        err("ERR_STALE_PLAN_VERSION", 412, "expected_plan_version does not match the plan's current version.")
    customer = get_customer_or_404(plan["customer_id"])
    heal_auto_skipped(plan, customer)
    for line in plan_lines(plan["id"]):
        if line["line_status"] == "SCHEDULED" and not line["is_bonus"]:
            evaluate_line_availability(plan, line, customer, notify_cap=True)
    estimate_plan(plan)
    touch(plan)
    return ok(ser_plan(plan))


@app.route("/sns/delivery-plans/<pid>/lock", methods=["POST"])
def lock_plan(pid):
    ignore_body()
    role, uid = require_roles("Customer")
    plan = get_plan_or_404(pid)
    check_ownership(plan["customer_id"], uid)
    if plan["plan_status"] != "OPEN":
        err("ERR_PLAN_NOT_OPEN", 409, "Plan must be OPEN to lock.")
    customer = get_customer_or_404(plan["customer_id"])
    # steps 1-3: availability/substitution, price-at-ship, caps
    for line in plan_lines(plan["id"]):
        if line["line_status"] == "SCHEDULED" and not line["is_bonus"]:
            evaluate_line_availability(plan, line, customer, notify_cap=True)
    # step 4: tier over survivors
    survivors = [
        l for l in plan_lines(plan["id"])
        if l["line_status"] == "SCHEDULED" and not l["is_bonus"] and l["quantity"] >= 1
    ]
    tier = tier_for_count(len(survivors))
    # step 5: per-line charges (round per line, then sum)
    gross = 0
    for line in survivors:
        price = line["unit_price_cents"] or 0
        line["line_charged_cents"] = round_half_up_cents(
            Decimal(price) * Decimal(line["quantity"]) * (Decimal(1) - Decimal(str(tier))))
        touch(line)
        gross += line["line_charged_cents"]
    # step 6: coupons
    charged = apply_coupons(gross, plan["applied_coupon_codes"])
    # step 7: promotions (bonus lines after tier fixed; never feed back)
    n_active = len(survivors)
    delivery_date = parse_date(plan["delivery_date"])
    for promo in sorted_items(DB["promotions"].values()):
        if promo["promotion_status"] != "ACTIVE":
            continue
        if not (parse_date(promo["starts_on"]) <= delivery_date < parse_date(promo["ends_on"])):
            continue
        if n_active >= promo["min_line_count"]:
            bonus = make_record({
                "plan_id": plan["id"], "subscription_id": None,
                "product_id": promo["bonus_product_id"], "quantity": 1,
                "is_bonus": True, "was_substituted": False,
                "line_status": "SCHEDULED", "skip_reason": None,
                "unit_price_cents": 0, "line_charged_cents": 0,
            })
            DB["lines"][bonus["id"]] = bonus
    # inventory reservation
    for line in survivors:
        placement = placement_for(line["product_id"], customer["region"])
        placement["on_hand_units"] -= line["quantity"]
        placement["reserved_units"] += line["quantity"]
        touch(placement)
    # price-increase notices
    for line in survivors:
        sub = DB["subscriptions"].get(line["subscription_id"])
        if sub is None or sub["subscribe_price_cents"] is None:
            continue
        threshold = round_half_up_cents(Decimal(sub["subscribe_price_cents"]) * Decimal("1.10"))
        if (line["unit_price_cents"] or 0) > threshold:
            create_notification(
                customer["id"], "PRICE_INCREASE",
                "The price of a subscribed item increased by more than 10% since you subscribed.",
                related_plan_id=plan["id"],
            )
    plan["tier_discount_pct"] = tier
    plan["active_line_count"] = n_active
    plan["gross_line_total_cents"] = gross
    plan["charged_total_cents"] = charged
    plan["plan_status"] = "LOCKED"
    touch(plan)
    return ok(ser_plan(plan))


@app.route("/sns/delivery-plans/<pid>/ship", methods=["POST"])
def ship_plan(pid):
    ignore_body()
    require_roles("PlatformAdmin")
    plan = get_plan_or_404(pid)
    if plan["plan_status"] != "LOCKED":
        err("ERR_PLAN_NOT_LOCKED", 409, "Plan must be LOCKED to ship.")
    customer = get_customer_or_404(plan["customer_id"])
    for line in plan_lines(plan["id"]):
        if line["line_status"] != "SCHEDULED":
            continue
        line["line_status"] = "SHIPPED"
        touch(line)
        if not line["is_bonus"]:
            placement = placement_for(line["product_id"], customer["region"])
            placement["reserved_units"] -= line["quantity"]
            placement["shipped_units"] += line["quantity"]
            touch(placement)
    plan["plan_status"] = "SHIPPED"
    touch(plan)
    create_notification(customer["id"], "PLAN_SHIPPED",
                        "Your consolidated subscription delivery has shipped.",
                        related_plan_id=plan["id"])
    return ok(ser_plan(plan))


@app.route("/sns/delivery-plans/<pid>/mark-delivered", methods=["POST"])
def mark_delivered_plan(pid):
    ignore_body()
    require_roles("PlatformAdmin")
    plan = get_plan_or_404(pid)
    if plan["plan_status"] != "SHIPPED":
        err("ERR_PLAN_NOT_LOCKED", 409, "Plan must be SHIPPED to mark delivered.")
    plan["plan_status"] = "DELIVERED"
    touch(plan)
    return ok(ser_plan(plan))


@app.route("/sns/delivery-plans/<pid>/resolve", methods=["POST"])
def resolve_plan(pid):
    ignore_body()
    require_roles("SupportAgent")
    plan = get_plan_or_404(pid)
    if plan["plan_status"] != "DELIVERED":
        err("ERR_PLAN_NOT_DELIVERED", 409, "Plan must be DELIVERED to resolve.")
    for c in DB["claims"].values():
        if c["plan_id"] == plan["id"] and c["claim_status"] in ("REPORTED", "APPROVED_RESHIP"):
            err("ERR_PLAN_NOT_DELIVERED", 409, "Plan has an open damage claim.")
    plan["plan_status"] = "RESOLVED"
    touch(plan)
    return ok(ser_plan(plan))


@app.route("/sns/delivery-plans/<pid>/cancel", methods=["POST"])
def cancel_plan(pid):
    ignore_body()
    require_roles("SupportAgent")
    plan = get_plan_or_404(pid)
    if plan["plan_status"] != "OPEN":
        err("ERR_PLAN_NOT_OPEN", 409, "Plan must be OPEN to cancel.")
    for line in plan_lines(plan["id"]):
        if line["line_status"] == "SCHEDULED":
            line["line_status"] = "SKIPPED"
            line["skip_reason"] = "CUSTOMER"
            touch(line)
    estimate_plan(plan)
    plan["plan_status"] = "CANCELLED"
    touch(plan)
    return ok(ser_plan(plan))


# ---------------------------------------------------------------------------
# Plan line skip / unskip
# ---------------------------------------------------------------------------
@app.route("/sns/delivery-plans/<pid>/lines/<lid>/skip", methods=["POST"])
def skip_line(pid, lid):
    ignore_body()
    role, uid = require_roles("Customer")
    plan = get_plan_or_404(pid)
    check_ownership(plan["customer_id"], uid)
    line = DB["lines"].get(lid)
    if line is None or line["plan_id"] != plan["id"]:
        err("ERR_LINE_NOT_FOUND", 404, "PlanLine id does not exist (or does not belong to the plan).")
    if plan["plan_status"] != "OPEN":
        err("ERR_PLAN_NOT_OPEN", 409, "Plan must be OPEN for line skip.")
    if line["is_bonus"] or line["line_status"] != "SCHEDULED":
        err("ERR_LINE_NOT_SKIPPABLE", 409, "Line is not in a status that permits skip.")
    line["line_status"] = "SKIPPED"
    line["skip_reason"] = "CUSTOMER"
    touch(line)
    estimate_plan(plan)
    touch(plan)
    return ok(ser_line(line))


@app.route("/sns/delivery-plans/<pid>/lines/<lid>/unskip", methods=["POST"])
def unskip_line(pid, lid):
    ignore_body()
    role, uid = require_roles("Customer")
    plan = get_plan_or_404(pid)
    check_ownership(plan["customer_id"], uid)
    line = DB["lines"].get(lid)
    if line is None or line["plan_id"] != plan["id"]:
        err("ERR_LINE_NOT_FOUND", 404, "PlanLine id does not exist (or does not belong to the plan).")
    if plan["plan_status"] != "OPEN":
        err("ERR_PLAN_NOT_OPEN", 409, "Plan must be OPEN for line unskip.")
    if line["line_status"] != "SKIPPED" or line["skip_reason"] != "CUSTOMER":
        err("ERR_LINE_NOT_SKIPPABLE", 409, "Line is not in a status that permits unskip.")
    sub = DB["subscriptions"].get(line["subscription_id"])
    if sub is not None:
        lazy_offer_expiry(sub)
    if sub is None or sub["status"] != "ACTIVE":
        err("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "The line's subscription is no longer ACTIVE.")
    line["line_status"] = "SCHEDULED"
    line["skip_reason"] = None
    touch(line)
    estimate_plan(plan)
    touch(plan)
    return ok(ser_line(line))


# ---------------------------------------------------------------------------
# Plan coupon attach
# ---------------------------------------------------------------------------
@app.route("/sns/delivery-plans/<pid>/coupons", methods=["POST"])
def attach_coupon(pid):
    body = get_body({"coupon_code": ("str", True)})
    role, uid = require_roles("Customer")
    plan = get_plan_or_404(pid)
    check_ownership(plan["customer_id"], uid)
    coupon = coupon_by_code(body["coupon_code"])
    if coupon is None or coupon["coupon_status"] != "ACTIVE":
        err("ERR_COUPON_NOT_FOUND", 404, "Coupon code does not exist or is disabled.")
    if plan["plan_status"] != "OPEN":
        err("ERR_PLAN_NOT_OPEN", 409, "Plan must be OPEN to attach a coupon.")
    delivery_date = parse_date(plan["delivery_date"])
    if delivery_date < parse_date(coupon["valid_from"]):
        err("ERR_COUPON_NOT_YET_VALID", 422, "Plan delivery_date is before the coupon's valid_from.")
    if delivery_date > parse_date(coupon["valid_to"]):
        err("ERR_COUPON_EXPIRED", 422, "Plan delivery_date is after the coupon's valid_to.")
    if plan["estimated_total_cents"] < coupon["min_subtotal_cents"]:
        err("ERR_SUBTOTAL_BELOW_COUPON_MIN", 422, "Plan estimated subtotal below coupon minimum.")
    if len(plan["applied_coupon_codes"]) >= 2:
        err("ERR_COUPON_STACK_LIMIT", 422, "Plan already has 2 coupons attached.")
    attached_non_stackable = False
    for code in plan["applied_coupon_codes"]:
        c = coupon_by_code(code)
        if c is not None and not c["stackable"]:
            attached_non_stackable = True
    if (not coupon["stackable"] and len(plan["applied_coupon_codes"]) >= 1) or attached_non_stackable:
        err("ERR_COUPON_NOT_STACKABLE", 422, "A non-stackable coupon may not be combined with another coupon.")
    plan["applied_coupon_codes"].append(coupon["code"])
    estimate_plan(plan)
    touch(plan)
    return ok(ser_plan(plan))


# ---------------------------------------------------------------------------
# Damage claims on plans
# ---------------------------------------------------------------------------
@app.route("/sns/delivery-plans/<pid>/damage-claims", methods=["POST"])
def create_damage_claim(pid):
    body = get_body({"damaged_line_ids": ("list_str", True)})
    role, uid = require_roles("Customer")
    plan = get_plan_or_404(pid)
    check_ownership(plan["customer_id"], uid)
    if plan["plan_status"] != "DELIVERED":
        err("ERR_PLAN_NOT_DELIVERED", 409, "Plan must be DELIVERED to open a damage claim.")
    ids = body["damaged_line_ids"]
    if not ids:
        err("ERR_CLAIM_LINES_INVALID", 422, "damaged_line_ids must be a non-empty array.")
    for lid in ids:
        line = DB["lines"].get(lid)
        if line is None or line["plan_id"] != plan["id"] or line["line_status"] != "SHIPPED":
            err("ERR_CLAIM_LINES_INVALID", 422,
                "damaged_line_ids must name lines of this plan in SHIPPED status.")
    rec = make_record({
        "plan_id": plan["id"], "customer_id": plan["customer_id"],
        "damaged_line_ids": list(ids), "claim_status": "REPORTED",
        "claim_refund_cents": None,
    })
    DB["claims"][rec["id"]] = rec
    return ok(ser_claim(rec), 201)


@app.route("/sns/delivery-plans/<pid>/damage-claims", methods=["GET"])
def list_plan_claims(pid):
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    plan = plan_for_customer_scoped(pid, role, uid)
    items = [ser_claim(c) for c in sorted_items(DB["claims"].values()) if c["plan_id"] == plan["id"]]
    page, pag = paginate(items)
    return ok(page, 200, "array", pag)


# ===========================================================================
# PLAN LINES (top-level)
# ===========================================================================
@app.route("/sns/plan-lines/<lid>", methods=["GET"])
def get_plan_line(lid):
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    line = get_line_or_404(lid)
    if role == "Customer":
        plan = get_plan_or_404(line["plan_id"])
        check_ownership(plan["customer_id"], uid)
    return ok(ser_line(line))


@app.route("/sns/plan-lines", methods=["GET"])
def list_plan_lines_top():
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    plan_id = request.args.get("plan_id")
    subscription_id = request.args.get("subscription_id")
    product_id = request.args.get("product_id")
    items = []
    for l in sorted_items(DB["lines"].values()):
        if plan_id is not None and l["plan_id"] != plan_id:
            continue
        if subscription_id is not None and l["subscription_id"] != subscription_id:
            continue
        if product_id is not None and l["product_id"] != product_id:
            continue
        if role == "Customer":
            plan = DB["plans"].get(l["plan_id"])
            if plan is None or plan["customer_id"] != uid:
                continue
        items.append(ser_line(l))
    page, pag = paginate(items)
    return ok(page, 200, "array", pag)


# ===========================================================================
# DAMAGE CLAIMS
# ===========================================================================
@app.route("/sns/damage-claims/<cid>", methods=["GET"])
def get_claim(cid):
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    c = get_claim_or_404(cid)
    if role == "Customer":
        check_ownership(c["customer_id"], uid)
    return ok(ser_claim(c))


@app.route("/sns/damage-claims/<cid>/review", methods=["POST"])
def review_claim(cid):
    body = get_body({"decision": ("str", True)})
    require_roles("SupportAgent")
    if body["decision"] not in ("APPROVE_REFUND", "APPROVE_RESHIP", "REJECT"):
        err("ERR_INVALID_REQUEST", 400, "decision must be APPROVE_REFUND, APPROVE_RESHIP, or REJECT.")
    claim = get_claim_or_404(cid)
    if claim["claim_status"] != "REPORTED":
        err("ERR_CLAIM_NOT_REVIEWABLE", 409, "DamageClaim not in REPORTED status.")
    plan = get_plan_or_404(claim["plan_id"])
    customer = get_customer_or_404(claim["customer_id"])
    decision = body["decision"]
    if decision == "REJECT":
        claim["claim_status"] = "REJECTED"
        touch(claim)
        return ok(ser_claim(claim))
    if decision == "APPROVE_REFUND":
        total = 0
        for lid in claim["damaged_line_ids"]:
            line = DB["lines"][lid]
            total += line["line_charged_cents"] or 0
        claim["claim_refund_cents"] = total
        for lid in claim["damaged_line_ids"]:
            line = DB["lines"][lid]
            line["line_status"] = "REFUNDED"
            touch(line)
        plan["refunded_total_cents"] += total
        touch(plan)
        claim["claim_status"] = "COMPLETED"
        touch(claim)
        return ok(ser_claim(claim))
    # APPROVE_RESHIP
    for lid in claim["damaged_line_ids"]:
        line = DB["lines"][lid]
        placement = placement_for(line["product_id"], customer["region"])
        on_hand = placement["on_hand_units"] if placement else 0
        if on_hand < line["quantity"]:
            err("ERR_INSUFFICIENT_INVENTORY", 422,
                "Reship requires on_hand >= line quantity for every reshipped line.")
    reshipment = make_record({
        "claim_id": claim["id"], "reshipped_line_ids": list(claim["damaged_line_ids"]),
        "reshipment_status": "PENDING",
    })
    DB["reshipments"][reshipment["id"]] = reshipment
    for lid in claim["damaged_line_ids"]:
        line = DB["lines"][lid]
        line["line_status"] = "RESHIPPED"
        touch(line)
    claim["claim_status"] = "APPROVED_RESHIP"
    touch(claim)
    return ok(ser_claim(claim))


@app.route("/sns/damage-claims/<cid>/reshipments", methods=["GET"])
def list_claim_reshipments(cid):
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    c = get_claim_or_404(cid)
    if role == "Customer":
        check_ownership(c["customer_id"], uid)
    items = [ser_reshipment(r) for r in sorted_items(DB["reshipments"].values()) if r["claim_id"] == cid]
    page, pag = paginate(items)
    return ok(page, 200, "array", pag)


# ===========================================================================
# RESHIPMENTS
# ===========================================================================
@app.route("/sns/reshipments/<rid>", methods=["GET"])
def get_reshipment(rid):
    role, uid = require_roles("PlatformAdmin", "SupportAgent", "Customer")
    r = get_reshipment_or_404(rid)
    if role == "Customer":
        claim = get_claim_or_404(r["claim_id"])
        check_ownership(claim["customer_id"], uid)
    return ok(ser_reshipment(r))


@app.route("/sns/reshipments/<rid>/dispatch", methods=["POST"])
def dispatch_reshipment(rid):
    ignore_body()
    require_roles("PlatformAdmin")
    r = get_reshipment_or_404(rid)
    if r["reshipment_status"] != "PENDING":
        err("ERR_INVALID_REQUEST", 400, "Reshipment must be PENDING to dispatch.")
    claim = get_claim_or_404(r["claim_id"])
    customer = get_customer_or_404(claim["customer_id"])
    for lid in r["reshipped_line_ids"]:
        line = DB["lines"][lid]
        placement = placement_for(line["product_id"], customer["region"])
        on_hand = placement["on_hand_units"] if placement else 0
        if on_hand < line["quantity"]:
            err("ERR_INSUFFICIENT_INVENTORY", 422,
                "Dispatch requires on_hand >= line quantity for every reshipped line.")
    for lid in r["reshipped_line_ids"]:
        line = DB["lines"][lid]
        placement = placement_for(line["product_id"], customer["region"])
        placement["on_hand_units"] -= line["quantity"]
        placement["shipped_units"] += line["quantity"]
        touch(placement)
    r["reshipment_status"] = "DISPATCHED"
    touch(r)
    create_notification(customer["id"], "RESHIP_DISPATCHED",
                        "Replacement items for your damage claim have been dispatched.",
                        related_plan_id=claim["plan_id"])
    return ok(ser_reshipment(r))


@app.route("/sns/reshipments/<rid>/mark-delivered", methods=["POST"])
def mark_delivered_reshipment(rid):
    ignore_body()
    require_roles("PlatformAdmin")
    r = get_reshipment_or_404(rid)
    if r["reshipment_status"] != "DISPATCHED":
        err("ERR_INVALID_REQUEST", 400, "Reshipment must be DISPATCHED to mark delivered.")
    r["reshipment_status"] = "DELIVERED"
    touch(r)
    claim = get_claim_or_404(r["claim_id"])
    if claim["claim_status"] == "APPROVED_RESHIP":
        claim["claim_status"] = "COMPLETED"
        touch(claim)
    return ok(ser_reshipment(r))


# ===========================================================================
# CLOCK
# ===========================================================================
@app.route("/sns/_clock/set_current_utc", methods=["POST"])
def set_clock():
    global CLOCK
    body = get_body({"to_iso8601": ("datetime", True)})
    require_roles("PlatformAdmin")
    CLOCK = parse_dt(body["to_iso8601"])
    return ok({"current_utc": iso_dt_str(CLOCK)})


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
