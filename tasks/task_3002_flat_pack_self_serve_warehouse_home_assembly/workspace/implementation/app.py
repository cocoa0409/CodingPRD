"""Flat-Pack Warehouse Assembly API — Flask implementation.

Every behavior traces to a verbatim sentence in PRD.md / SCAFFOLD.yaml.
Storage is in-memory only (db.DB); the store starts empty on every boot.
"""

import math
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request

from db import DB, new_id, now, iso, touch
from errors import ApiError, raise_err
from response import success, error
from middleware import require_role, check_customer_ownership

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (calculation tables §1.3)
# ---------------------------------------------------------------------------
RESERVATION_TTL = timedelta(hours=24)
ZONE_BASE = {"ZONE_A": 4900, "ZONE_B": 7900, "ZONE_C": 12900}
WEIGHT_TIER1_KG = 50.0
WEIGHT_TIER2_KG = 150.0
TIER2_FLAT_CENTS = 2500
OVERAGE_CENTS_PER_KG = 15
WALKUP_HIGH_FEE_CENTS = 1200
WALKUP_HIGH_MAX_CARTON_KG = 40.0
MEMBER_FEE_DISCOUNT = Decimal("0.80")
FOOD_MEMBER_DISCOUNT = Decimal("0.10")
POINTS_REDEMPTION_CAP_DIV = 5  # floor((subtotal - discount) * 0.20)
CREW_BUFFER = timedelta(minutes=30)
BILLING_CAP_NUM, BILLING_CAP_DEN = 3, 2  # ceil(estimated * 1.5)
MAX_CLAIMS_365D = 3
MAX_CLAIM_VALUE_365D_CENTS = 3000
NO_RECEIPT_FACTOR = Decimal("0.9")
GRADE_FACTOR = {
    "LIKE_NEW": Decimal("1.00"),
    "OPEN_BOX": Decimal("0.85"),
    "DAMAGED": Decimal("0.50"),
    "SCRAP": Decimal("0.00"),
}
ARTICLE_CATEGORIES = {"FURNITURE", "FOOD", "ACCESSORY"}
PICK_POLICIES = {"SELF_SERVE", "FULL_SERVE"}
ZONES = {"ZONE_A", "ZONE_B", "ZONE_C"}
ACCESS_TYPES = {"ELEVATOR", "WALKUP_LOW", "WALKUP_HIGH"}
CONDITION_GRADES = {"LIKE_NEW", "OPEN_BOX", "DAMAGED", "SCRAP"}
ASSEMBLY_STATES = {"UNOPENED", "PARTIALLY_ASSEMBLED", "ASSEMBLED"}
FULFILLMENT_CHANNELS = {"CARRYOUT", "DELIVERY"}
JOB_ACTIVE_STATES = {"REQUESTED", "DISPATCHED", "IN_PROGRESS", "ON_HOLD"}


def rhu(value):
    """Round half-up to integer cents (away from zero at a half)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Request body / field validation (priority 1 -> ERR_VALIDATION 400)
# ---------------------------------------------------------------------------

def get_body(required=False):
    if not request.data:
        if required:
            raise_err("ERR_VALIDATION", "Request body is required")
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise_err("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise_err("ERR_VALIDATION", f"Field '{field}' is required and must be a string")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise_err("ERR_VALIDATION", f"Field '{field}' must be a string")
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if not _is_int(v):
        raise_err("ERR_VALIDATION", f"Field '{field}' is required and must be an integer")
    if minimum is not None and v < minimum:
        raise_err("ERR_VALIDATION", f"Field '{field}' must be >= {minimum}")
    return v


def opt_int(body, field, default=None, minimum=None, nullable=False):
    if field not in body:
        return default
    v = body[field]
    if v is None and nullable:
        return None
    if not _is_int(v):
        raise_err("ERR_VALIDATION", f"Field '{field}' must be an integer")
    if minimum is not None and v < minimum:
        raise_err("ERR_VALIDATION", f"Field '{field}' must be >= {minimum}")
    return v


def req_number(body, field, gt=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err("ERR_VALIDATION", f"Field '{field}' is required and must be a number")
    v = float(v)
    if gt is not None and not v > gt:
        raise_err("ERR_VALIDATION", f"Field '{field}' must be > {gt}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise_err("ERR_VALIDATION", f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, allowed)


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise_err("ERR_VALIDATION", f"Field '{field}' must be a boolean")
    return v


def parse_dt(value, field):
    if not isinstance(value, str):
        raise_err("ERR_VALIDATION", f"Field '{field}' must be an ISO 8601 string")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise_err("ERR_VALIDATION", f"Field '{field}' must be a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(body, field):
    if field not in body or body[field] is None:
        raise_err("ERR_VALIDATION", f"Field '{field}' is required")
    return parse_dt(body[field], field)


def parse_date(value, field):
    if not isinstance(value, str):
        raise_err("ERR_VALIDATION", f"Field '{field}' must be an ISO date string")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise_err("ERR_VALIDATION", f"Field '{field}' must be a valid YYYY-MM-DD date")


def get_pagination():
    """limit default 10 (min 1, max 100); offset default 0 (§2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise_err("ERR_VALIDATION", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise_err("ERR_VALIDATION", "offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items):
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, {"limit": limit, "offset": offset,
                  "total_count": total, "has_more": offset + limit < total}


def list_all(items):
    """List endpoints without declared pagination params return everything.

    §2.3 still applies to the meta block: limit defaults to 10 with minimum
    1 and maximum 100, so it is clamped even when everything is returned.
    """
    limit = max(1, min(100, len(items)))
    return items, {"limit": limit, "offset": 0,
                   "total_count": len(items), "has_more": False}


# ---------------------------------------------------------------------------
# Entity construction / lookup / serialization
# ---------------------------------------------------------------------------

def _base():
    ts = now()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = iso(v)
        else:
            out[k] = v
    return out


def get_or_404(collection, rid, error_id):
    ent = collection.get(rid)
    if ent is None:
        raise_err(error_id, f"Resource {rid} not found")
    return ent


def article_cartons(article_id):
    """All Carton rows of the article, ordered by carton_seq ASC."""
    rows = [c for c in DB.cartons.values() if c["article_id"] == article_id]
    rows.sort(key=lambda c: c["carton_seq"])
    return rows


def bin_stock_for(store_id, carton_id):
    for bs in DB.bin_stock.values():
        if bs["store_id"] == store_id and bs["carton_id"] == carton_id:
            return bs
    return None


def order_lines_of(order_id):
    return [l for l in DB.order_lines.values() if l["order_id"] == order_id]


def serialize_article(a):
    out = serialize(a)
    count = len(article_cartons(a["id"]))
    out["carton_count"] = count
    out["is_multi_carton"] = count > 1
    return out


def serialize_bin_stock(bs):
    out = serialize(bs)
    out["available"] = bs["on_hand"] - bs["reserved"]
    return out


def serialize_slot(s):
    out = serialize(s)
    free_w = s["capacity_weight_kg"] - s["used_weight_kg"]
    free_v = s["capacity_volume_m3"] - s["used_volume_m3"]
    out["posture"] = "FULL" if free_w == 0 or free_v == 0 else "OPEN"
    return out


def compute_available_units(store_id, article_id):
    """Signal rule: 0 if no cartons or any carton lacks a BinStock row;
    otherwise the smallest per-carton available (§3.1)."""
    cartons = article_cartons(article_id)
    if not cartons:
        return 0, None
    per_carton = []
    for c in cartons:
        bs = bin_stock_for(store_id, c["id"])
        if bs is None:
            return 0, None
        per_carton.append(bs)
    return min(bs["on_hand"] - bs["reserved"] for bs in per_carton), per_carton


def check_line_stock(store_id, article, qty):
    """Checkout / standalone-reservation stock gate (§3.3).

    Every carton short (or no cartons/stock rows) -> ERR_INSUFFICIENT_STOCK;
    some sufficient but at least one short -> ERR_MULTI_CARTON_SHORTAGE.
    Returns the per-carton BinStock rows on success."""
    cartons = article_cartons(article["id"])
    if not cartons:
        raise_err("ERR_INSUFFICIENT_STOCK", "Article has no cartons registered")
    rows = []
    for c in cartons:
        bs = bin_stock_for(store_id, c["id"])
        if bs is None:
            raise_err("ERR_INSUFFICIENT_STOCK",
                      "A carton has no bin-stock row in this store")
        rows.append(bs)
    short = [bs for bs in rows if bs["on_hand"] - bs["reserved"] < qty]
    if not short:
        return rows
    if len(short) == len(rows):
        raise_err("ERR_INSUFFICIENT_STOCK", "Every carton is short for the quantity")
    raise_err("ERR_MULTI_CARTON_SHORTAGE",
              "Some cartons have sufficient stock but at least one is short")


def bump_bin_stock(bs):
    touch(bs)


# ---------------------------------------------------------------------------
# Points accrual / auto-close (§3.3, §3.6)
# ---------------------------------------------------------------------------

def accrue_points(order):
    customer = DB.customers.get(order["customer_id"])
    if customer is not None and customer["member_status"] == "ACTIVE":
        earned = order["total_cents"] // 100
        order["points_earned"] = earned
        if earned:
            customer["points_balance"] += earned
            touch(customer)
    else:
        order["points_earned"] = 0


def close_order(order):
    order["status"] = "CLOSED"
    accrue_points(order)
    touch(order)


def auto_close_evaluation(order):
    """Auto-close the moment assembly finishes / delivery completes (§3.3)."""
    if order["status"] in {"FULFILLED", "DELIVERED"} and order["assembly_status"] == "COMPLETED":
        close_order(order)


# ---------------------------------------------------------------------------
# Waitlist promotion (§3.5)
# ---------------------------------------------------------------------------

def booking_fits(slot, weight, volume):
    """Inclusive fit test: a booking that exactly fills both dimensions FITS."""
    return (slot["used_weight_kg"] + weight <= slot["capacity_weight_kg"]
            and slot["used_volume_m3"] + volume <= slot["capacity_volume_m3"])


def confirm_booking(booking, slot):
    """CONFIRMED side effects: consume capacity, reserve stock, schedule order."""
    booking["status"] = "CONFIRMED"
    touch(booking)
    slot["used_weight_kg"] += booking["total_weight_kg"]
    slot["used_volume_m3"] += booking["total_volume_m3"]
    touch(slot)
    order = DB.orders[booking["order_id"]]
    for line in order_lines_of(order["id"]):
        for carton in article_cartons(line["article_id"]):
            bs = bin_stock_for(order["store_id"], carton["id"])
            bs["reserved"] += line["qty"]
            bump_bin_stock(bs)
    order["delivery_status"] = "SCHEDULED"
    touch(order)


def waitlist_promotion(slot):
    """Greedy waterfall over WAITLISTED bookings ranked created_at ASC, then
    lighter total_weight_kg, then smaller total_volume_m3 (§3.5)."""
    promoted = []
    candidates = [b for b in DB.delivery_bookings.values()
                  if b["slot_id"] == slot["id"] and b["status"] == "WAITLISTED"]
    candidates.sort(key=lambda b: (b["created_at"], b["total_weight_kg"],
                                   b["total_volume_m3"]))
    for cand in candidates:
        if booking_fits(slot, cand["total_weight_kg"], cand["total_volume_m3"]):
            confirm_booking(cand, slot)
            promoted.append(cand["id"])
    return promoted


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_not_found(_):
    return error("ERR_VALIDATION", 400, "Unknown route")


@app.errorhandler(405)
def handle_method_not_allowed(_):
    return error("ERR_VALIDATION", 400, "Method not allowed")


# ---------------------------------------------------------------------------
# Clock (test-driving capability, §2.6)
# ---------------------------------------------------------------------------

@app.post("/api/_clock/set_current_utc")
def set_clock():
    body = get_body(required=True)
    target = req_dt(body, "to_iso8601")
    require_role("PlatformAdmin")
    DB.clock = target
    return success({"current_utc": iso(DB.clock)}, 200)


# ---------------------------------------------------------------------------
# Stores (§3.1)
# ---------------------------------------------------------------------------

@app.post("/api/stores")
def create_store():
    body = get_body(required=True)
    name = req_str(body, "name")
    code = req_str(body, "code")
    threshold = opt_int(body, "low_stock_threshold", default=5, minimum=1)
    require_role("PlatformAdmin")
    if any(s["code"] == code for s in DB.stores.values()):
        raise_err("ERR_VALIDATION", "Store code must be unique across stores")
    store = _base()
    store.update({"name": name, "code": code, "low_stock_threshold": threshold})
    DB.stores[store["id"]] = store
    return success(serialize(store), 201)


@app.get("/api/stores/<sid>")
def get_store(sid):
    require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                 "AssemblyProvider", "Customer")
    store = get_or_404(DB.stores, sid, "ERR_STORE_NOT_FOUND")
    return success(serialize(store), 200)


@app.get("/api/stores/<sid>/stock")
def get_store_stock(sid):
    require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                 "AssemblyProvider", "Customer")
    store = get_or_404(DB.stores, sid, "ERR_STORE_NOT_FOUND")
    rows = [bs for bs in DB.bin_stock.values() if bs["store_id"] == store["id"]]
    rows.sort(key=lambda bs: bs["created_at"])
    page, meta = paginate(rows)
    return success([serialize_bin_stock(bs) for bs in page], 200, meta)


@app.get("/api/stores/<sid>/articles/<article_id>/signal")
def get_signal(sid, article_id):
    require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                 "AssemblyProvider", "Customer")
    store = get_or_404(DB.stores, sid, "ERR_STORE_NOT_FOUND")
    article = get_or_404(DB.articles, article_id, "ERR_ARTICLE_NOT_FOUND")
    available, _ = compute_available_units(store["id"], article["id"])
    threshold = store["low_stock_threshold"]
    if available == 0:
        signal = "OUT_OF_STOCK"
    elif available < threshold:
        signal = "LOW_STOCK"
    else:
        signal = "IN_STOCK"
    return success({
        "article_id": article["id"],
        "store_id": store["id"],
        "available_units": available,
        "threshold_used": threshold,
        "signal": signal,
    }, 200)


@app.post("/api/stores/<sid>/run_sweep")
def run_sweep(sid):
    require_role("StoreOps")
    store = get_or_404(DB.stores, sid, "ERR_STORE_NOT_FOUND")
    expired = []
    for res in list(DB.reservations.values()):
        if (res["store_id"] == store["id"] and res["status"] == "ACTIVE"
                and res["expires_at"] <= now()):
            res["status"] = "EXPIRED"
            touch(res)
            for carton in article_cartons(res["article_id"]):
                bs = bin_stock_for(store["id"], carton["id"])
                if bs is not None:
                    bs["reserved"] -= res["qty"]
                    bump_bin_stock(bs)
            expired.append(res["id"])
    promoted = []
    slots = [s for s in DB.delivery_slots.values() if s["store_id"] == store["id"]]
    slots.sort(key=lambda s: s["created_at"])
    for slot in slots:
        promoted.extend(waitlist_promotion(slot))
    return success({"expired_reservation_ids": expired,
                    "promoted_booking_ids": promoted}, 200)


# ---------------------------------------------------------------------------
# Articles & Cartons (§3.1)
# ---------------------------------------------------------------------------

@app.post("/api/articles")
def create_article():
    body = get_body(required=True)
    article_number = req_str(body, "article_number")
    name = req_str(body, "name")
    category = req_enum(body, "category", ARTICLE_CATEGORIES)
    pick_policy = req_enum(body, "pick_policy", PICK_POLICIES)
    price_cents = req_int(body, "price_cents", minimum=0)
    family_price = opt_int(body, "family_price_cents", default=None, minimum=0,
                           nullable=True)
    lowest_price = opt_int(body, "lowest_price_365d_cents", default=None, minimum=0,
                           nullable=True)
    requires_assembly = opt_bool(body, "requires_assembly", default=False)
    require_role("PlatformAdmin")
    if any(a["article_number"] == article_number for a in DB.articles.values()):
        raise_err("ERR_VALIDATION", "article_number must be unique across articles")
    article = _base()
    article.update({
        "article_number": article_number,
        "name": name,
        "category": category,
        "pick_policy": pick_policy,
        "price_cents": price_cents,
        "family_price_cents": family_price,
        "lowest_price_365d_cents": lowest_price,
        "requires_assembly": requires_assembly,
    })
    DB.articles[article["id"]] = article
    return success(serialize_article(article), 201)


@app.get("/api/articles/<aid>")
def get_article(aid):
    require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                 "AssemblyProvider", "Customer")
    article = get_or_404(DB.articles, aid, "ERR_ARTICLE_NOT_FOUND")
    return success(serialize_article(article), 200)


@app.patch("/api/articles/<aid>")
def update_article(aid):
    body = get_body(required=True)
    price = opt_int(body, "price_cents", default="__unset__", minimum=0)
    family = opt_int(body, "family_price_cents", default="__unset__", minimum=0,
                     nullable=True)
    lowest = opt_int(body, "lowest_price_365d_cents", default="__unset__", minimum=0,
                     nullable=True)
    require_role("PlatformAdmin")
    article = get_or_404(DB.articles, aid, "ERR_ARTICLE_NOT_FOUND")
    changed = False
    if price != "__unset__":
        article["price_cents"] = price
        changed = True
    if family != "__unset__":
        article["family_price_cents"] = family
        changed = True
    if lowest != "__unset__":
        article["lowest_price_365d_cents"] = lowest
        changed = True
    if changed:
        touch(article)
    return success(serialize_article(article), 200)


@app.post("/api/articles/<aid>/cartons")
def create_carton(aid):
    body = get_body(required=True)
    seq = req_int(body, "carton_seq", minimum=1)
    aisle = req_str(body, "aisle")
    bin_ = req_str(body, "bin")
    weight = req_number(body, "weight_kg", gt=0)
    volume = req_number(body, "volume_m3", gt=0)
    require_role("PlatformAdmin")
    article = get_or_404(DB.articles, aid, "ERR_ARTICLE_NOT_FOUND")
    if any(c["carton_seq"] == seq for c in article_cartons(article["id"])):
        raise_err("ERR_VALIDATION", "carton_seq must be unique within the article")
    carton = _base()
    carton.update({
        "article_id": article["id"],
        "carton_seq": seq,
        "aisle": aisle,
        "bin": bin_,
        "weight_kg": weight,
        "volume_m3": volume,
    })
    DB.cartons[carton["id"]] = carton
    # carton_count recomputed -> the article itself is mutated (§2.4).
    touch(article)
    return success(serialize(carton), 201)


@app.get("/api/articles/<aid>/cartons")
def list_cartons(aid):
    require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                 "AssemblyProvider", "Customer")
    article = get_or_404(DB.articles, aid, "ERR_ARTICLE_NOT_FOUND")
    rows = article_cartons(article["id"])
    page, meta = list_all(rows)
    return success([serialize(c) for c in page], 200, meta)


# ---------------------------------------------------------------------------
# BinStock (§3.1)
# ---------------------------------------------------------------------------

@app.post("/api/bin-stock")
def create_bin_stock():
    body = get_body(required=True)
    store_id = req_str(body, "store_id")
    carton_id = req_str(body, "carton_id")
    on_hand = opt_int(body, "on_hand", default=0, minimum=0)
    require_role("StoreOps")
    store = get_or_404(DB.stores, store_id, "ERR_STORE_NOT_FOUND")
    carton = get_or_404(DB.cartons, carton_id, "ERR_CARTON_NOT_FOUND")
    if bin_stock_for(store["id"], carton["id"]) is not None:
        raise_err("ERR_DUPLICATE_BIN_STOCK",
                  "BinStock row already exists for (store_id, carton_id)")
    bs = _base()
    bs.update({"store_id": store["id"], "carton_id": carton["id"],
               "on_hand": on_hand, "reserved": 0})
    DB.bin_stock[bs["id"]] = bs
    return success(serialize_bin_stock(bs), 201)


@app.get("/api/bin-stock/<bid>")
def get_bin_stock(bid):
    require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                 "AssemblyProvider", "Customer")
    bs = get_or_404(DB.bin_stock, bid, "ERR_BIN_STOCK_NOT_FOUND")
    return success(serialize_bin_stock(bs), 200)


@app.get("/api/bin-stock")
def list_bin_stock():
    require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                 "AssemblyProvider", "Customer")
    rows = list(DB.bin_stock.values())
    store_id = request.args.get("store_id")
    carton_id = request.args.get("carton_id")
    if store_id is not None:
        rows = [bs for bs in rows if bs["store_id"] == store_id]
    if carton_id is not None:
        rows = [bs for bs in rows if bs["carton_id"] == carton_id]
    rows.sort(key=lambda bs: bs["created_at"])
    page, meta = paginate(rows)
    return success([serialize_bin_stock(bs) for bs in page], 200, meta)


@app.post("/api/bin-stock/<bid>/adjust")
def adjust_bin_stock(bid):
    body = get_body(required=True)
    delta = req_int(body, "delta_on_hand")
    expected = req_int(body, "expected_stock_version")
    require_role("StoreOps")
    bs = get_or_404(DB.bin_stock, bid, "ERR_BIN_STOCK_NOT_FOUND")
    # OCC: a stale row must be re-read before re-applying the delta (§2.7).
    if expected != bs["version"]:
        raise_err("ERR_STALE_VERSION", "BinStock version has advanced")
    new_on_hand = bs["on_hand"] + delta
    if new_on_hand < 0 or new_on_hand < bs["reserved"]:
        raise_err("ERR_VALIDATION",
                  "on_hand must stay non-negative and at least as large as reserved")
    bs["on_hand"] = new_on_hand
    bump_bin_stock(bs)
    return success(serialize_bin_stock(bs), 200)


# ---------------------------------------------------------------------------
# Customers (§3.2)
# ---------------------------------------------------------------------------

@app.post("/api/customers")
def create_customer():
    body = get_body(required=True)
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")
    require_role("PlatformAdmin", "StoreOps")
    if any(c["email"] == email for c in DB.customers.values()):
        raise_err("ERR_VALIDATION", "email must be unique across customers")
    customer = _base()
    customer.update({"email": email, "full_name": full_name,
                     "member_status": "NONE", "member_since": None,
                     "points_balance": 0})
    DB.customers[customer["id"]] = customer
    return success(serialize(customer), 201)


@app.get("/api/customers/<cid>")
def get_customer(cid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    customer = get_or_404(DB.customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    check_customer_ownership(user_id, role, customer["id"])
    return success(serialize(customer), 200)


@app.post("/api/customers/<cid>/enroll")
def enroll_customer(cid):
    require_role("StoreOps")
    customer = get_or_404(DB.customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    if customer["member_status"] == "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Customer is already enrolled")
    customer["member_status"] = "ACTIVE"
    customer["member_since"] = now()
    touch(customer)
    return success(serialize(customer), 200)


@app.get("/api/customers/<cid>/orders")
def list_customer_orders(cid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    customer = get_or_404(DB.customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    check_customer_ownership(user_id, role, customer["id"])
    rows = [o for o in DB.orders.values() if o["customer_id"] == customer["id"]]
    rows.sort(key=lambda o: o["created_at"])
    page, meta = paginate(rows)
    return success([serialize(o) for o in page], 200, meta)


@app.get("/api/customers/<cid>/spare-part-claims")
def list_customer_claims(cid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    customer = get_or_404(DB.customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    check_customer_ownership(user_id, role, customer["id"])
    rows = [c for c in DB.spare_part_claims.values()
            if c["customer_id"] == customer["id"]]
    rows.sort(key=lambda c: c["created_at"])
    page, meta = paginate(rows)
    return success([serialize(c) for c in page], 200, meta)


# ---------------------------------------------------------------------------
# Orders & OrderLines (§3.3)
# ---------------------------------------------------------------------------

@app.post("/api/orders")
def create_order():
    body = get_body(required=True)
    store_id = req_str(body, "store_id")
    user_id, role = require_role("Customer")
    customer = get_or_404(DB.customers, user_id, "ERR_CUSTOMER_NOT_FOUND")
    store = get_or_404(DB.stores, store_id, "ERR_STORE_NOT_FOUND")
    order = _base()
    order.update({
        # customer_id is taken from X-User-ID, never from the request body.
        "customer_id": customer["id"],
        "store_id": store["id"],
        "status": "DRAFT",
        "delivery_status": "NONE",
        "assembly_status": "NONE",
        "fulfillment_channel": "CARRYOUT",
        "subtotal_cents": 0,
        "discount_cents": 0,
        "points_discount_cents": 0,
        "total_cents": 0,
        "points_earned": 0,
    })
    DB.orders[order["id"]] = order
    return success(serialize(order), 201)


def load_order_for_customer(order_id, user_id, role):
    order = get_or_404(DB.orders, order_id, "ERR_ORDER_NOT_FOUND")
    check_customer_ownership(user_id, role, order["customer_id"])
    return order


@app.get("/api/orders/<oid>")
def get_order(oid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    order = load_order_for_customer(oid, user_id, role)
    return success(serialize(order), 200)


@app.get("/api/orders")
def list_orders():
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    rows = list(DB.orders.values())
    customer_id = request.args.get("customer_id")
    store_id = request.args.get("store_id")
    status = request.args.get("status")
    if role == "Customer":
        if customer_id is not None and customer_id != user_id:
            raise_err("ERR_FORBIDDEN", "Customer may only list its own orders")
        rows = [o for o in rows if o["customer_id"] == user_id]
    elif customer_id is not None:
        rows = [o for o in rows if o["customer_id"] == customer_id]
    if store_id is not None:
        rows = [o for o in rows if o["store_id"] == store_id]
    if status is not None:
        rows = [o for o in rows if o["status"] == status]
    rows.sort(key=lambda o: o["created_at"])
    page, meta = paginate(rows)
    return success([serialize(o) for o in page], 200, meta)


@app.post("/api/orders/<oid>/lines")
def add_order_line(oid):
    body = get_body(required=True)
    article_id = req_str(body, "article_id")
    qty = req_int(body, "qty", minimum=1)
    user_id, role = require_role("Customer")
    order = load_order_for_customer(oid, user_id, role)
    article = get_or_404(DB.articles, article_id, "ERR_ARTICLE_NOT_FOUND")
    if order["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Lines may be added only to a DRAFT order")
    line = _base()
    line.update({
        "order_id": order["id"],
        "article_id": article["id"],
        "qty": qty,
        "unit_price_cents": 0,
        "line_gross_cents": 0,
        "line_discount_cents": 0,
        "line_total_cents": 0,
        "effective_unit_paid_cents": 0,
        "fulfillment_mode": ("SELF_PICK" if article["pick_policy"] == "SELF_SERVE"
                             else "PICKUP_COUNTER"),
        "returned_qty": 0,
    })
    DB.order_lines[line["id"]] = line
    touch(order)
    return success(serialize(line), 201)


@app.get("/api/orders/<oid>/lines")
def list_order_lines(oid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    order = load_order_for_customer(oid, user_id, role)
    rows = order_lines_of(order["id"])
    rows.sort(key=lambda l: l["created_at"])
    page, meta = list_all(rows)
    return success([serialize(l) for l in page], 200, meta)


@app.get("/api/orders/<oid>/delivery-bookings")
def list_order_bookings(oid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    order = load_order_for_customer(oid, user_id, role)
    rows = [b for b in DB.delivery_bookings.values() if b["order_id"] == order["id"]]
    rows.sort(key=lambda b: b["created_at"])
    page, meta = list_all(rows)
    return success([serialize(b) for b in page], 200, meta)


@app.get("/api/orders/<oid>/assembly-jobs")
def list_order_jobs(oid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    order = load_order_for_customer(oid, user_id, role)
    rows = [j for j in DB.assembly_jobs.values() if j["order_id"] == order["id"]]
    rows.sort(key=lambda j: j["created_at"])
    page, meta = list_all(rows)
    return success([serialize(j) for j in page], 200, meta)


@app.get("/api/orders/<oid>/returns")
def list_order_returns(oid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    order = load_order_for_customer(oid, user_id, role)
    rows = [r for r in DB.return_requests.values() if r["order_id"] == order["id"]]
    rows.sort(key=lambda r: r["created_at"])
    page, meta = list_all(rows)
    return success([serialize(r) for r in page], 200, meta)


@app.get("/api/order-lines/<lid>")
def get_order_line(lid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    line = get_or_404(DB.order_lines, lid, "ERR_ORDER_LINE_NOT_FOUND")
    if role == "Customer":
        order = DB.orders.get(line["order_id"])
        check_customer_ownership(user_id, role,
                                 order["customer_id"] if order else None)
    return success(serialize(line), 200)


@app.get("/api/order-lines")
def list_order_lines_global():
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    rows = list(DB.order_lines.values())
    order_id = request.args.get("order_id")
    article_id = request.args.get("article_id")
    if role == "Customer":
        own_orders = {o["id"] for o in DB.orders.values()
                      if o["customer_id"] == user_id}
        rows = [l for l in rows if l["order_id"] in own_orders]
    if order_id is not None:
        rows = [l for l in rows if l["order_id"] == order_id]
    if article_id is not None:
        rows = [l for l in rows if l["article_id"] == article_id]
    rows.sort(key=lambda l: l["created_at"])
    page, meta = paginate(rows)
    return success([serialize(l) for l in page], 200, meta)


@app.post("/api/orders/<oid>/checkout")
def checkout(oid):
    body = get_body()
    redeem_points = opt_int(body, "redeem_points", default=0, minimum=0)
    channel = opt_enum(body, "fulfillment_channel", FULFILLMENT_CHANNELS,
                       default="CARRYOUT")
    user_id, role = require_role("Customer")
    order = load_order_for_customer(oid, user_id, role)
    if order["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Only a DRAFT order can be checked out")
    lines = order_lines_of(order["id"])
    lines.sort(key=lambda l: l["created_at"])
    if not lines:
        raise_err("ERR_INVALID_STATE", "An order with no lines cannot be checked out")
    # Stock gate per line (priority 8) before fiscal checks (priority 9).
    stock_rows = {}
    for line in lines:
        article = DB.articles[line["article_id"]]
        stock_rows[line["id"]] = check_line_stock(order["store_id"], article,
                                                  line["qty"])
    customer = DB.customers[order["customer_id"]]
    if redeem_points > customer["points_balance"]:
        raise_err("ERR_INSUFFICIENT_POINTS",
                  "redeem_points exceeds the customer's points_balance")

    # Pricing evaluates in a pinned order, per line then across the order (§3.3).
    member = customer["member_status"] == "ACTIVE"
    subtotal = 0
    discount = 0
    for line in lines:
        article = DB.articles[line["article_id"]]
        family_price = article["family_price_cents"]
        unit = family_price if (member and family_price is not None) \
            else article["price_cents"]
        gross = unit * line["qty"]
        line_discount = rhu(Decimal(gross) * FOOD_MEMBER_DISCOUNT) \
            if (member and article["category"] == "FOOD") else 0
        line_total = gross - line_discount
        effective_unit = rhu(Decimal(line_total) / Decimal(line["qty"]))
        line["unit_price_cents"] = unit
        line["line_gross_cents"] = gross
        line["line_discount_cents"] = line_discount
        line["line_total_cents"] = line_total
        line["effective_unit_paid_cents"] = effective_unit
        touch(line)
        subtotal += gross
        discount += line_discount
    applied = min(redeem_points, customer["points_balance"],
                  (subtotal - discount) // POINTS_REDEMPTION_CAP_DIV)
    order["subtotal_cents"] = subtotal
    order["discount_cents"] = discount
    order["points_discount_cents"] = applied
    order["total_cents"] = subtotal - discount - applied
    order["fulfillment_channel"] = channel
    if applied:
        customer["points_balance"] -= applied
        touch(customer)

    # Stock movement depends on the pinned channel and each line's mode (§3.3).
    if channel == "CARRYOUT":
        for line in lines:
            article = DB.articles[line["article_id"]]
            if line["fulfillment_mode"] == "SELF_PICK":
                for bs in stock_rows[line["id"]]:
                    bs["on_hand"] -= line["qty"]
                    bump_bin_stock(bs)
            else:  # PICKUP_COUNTER -> auto-create an ACTIVE reservation
                res = _base()
                res.update({
                    "store_id": order["store_id"],
                    "article_id": article["id"],
                    "customer_id": order["customer_id"],
                    "order_line_id": line["id"],
                    "qty": line["qty"],
                    "status": "ACTIVE",
                    "reserved_at": now(),
                    "expires_at": now() + RESERVATION_TTL,
                })
                DB.reservations[res["id"]] = res
                for bs in stock_rows[line["id"]]:
                    bs["reserved"] += line["qty"]
                    bump_bin_stock(bs)
    # channel DELIVERY: checkout moves no stock at all.
    order["status"] = "PAID"
    touch(order)
    return success(serialize(order), 200)


@app.post("/api/orders/<oid>/cancel")
def cancel_order(oid):
    user_id, role = require_role("Customer")
    order = load_order_for_customer(oid, user_id, role)
    if order["status"] == "DRAFT":
        order["status"] = "CANCELLED"
        touch(order)
        return success(serialize(order), 200)
    if order["status"] != "PAID":
        raise_err("ERR_INVALID_STATE", "Only DRAFT or PAID orders can be cancelled")
    # PAID cancellation is allowed only when nothing downstream has started.
    if order["delivery_status"] != "NONE":
        raise_err("ERR_INVALID_STATE", "An active booking must be cancelled first")
    if order["assembly_status"] != "NONE":
        raise_err("ERR_INVALID_STATE", "Assembly has already started")
    lines = order_lines_of(order["id"])
    for line in lines:
        if line["fulfillment_mode"] == "PICKUP_COUNTER":
            for res in DB.reservations.values():
                if (res["order_line_id"] == line["id"]
                        and res["status"] == "FULFILLED"):
                    raise_err("ERR_INVALID_STATE",
                              "A pickup-counter reservation is already fulfilled")
    # Compensation in full (§3.3).
    for line in lines:
        cartons = article_cartons(line["article_id"])
        if line["fulfillment_mode"] == "SELF_PICK":
            for carton in cartons:
                bs = bin_stock_for(order["store_id"], carton["id"])
                if bs is not None:
                    bs["on_hand"] += line["qty"]
                    bump_bin_stock(bs)
        else:
            for res in DB.reservations.values():
                if (res["order_line_id"] == line["id"]
                        and res["status"] == "ACTIVE"):
                    res["status"] = "CANCELLED"
                    touch(res)
                    for carton in cartons:
                        bs = bin_stock_for(order["store_id"], carton["id"])
                        if bs is not None:
                            bs["reserved"] -= line["qty"]
                            bump_bin_stock(bs)
    if order["points_discount_cents"]:
        customer = DB.customers[order["customer_id"]]
        customer["points_balance"] += order["points_discount_cents"]
        touch(customer)
    order["status"] = "CANCELLED"
    touch(order)
    return success(serialize(order), 200)


@app.post("/api/orders/<oid>/pickup-complete")
def pickup_complete(oid):
    require_role("StoreOps")
    order = get_or_404(DB.orders, oid, "ERR_ORDER_NOT_FOUND")
    if order["status"] != "PAID":
        raise_err("ERR_INVALID_STATE", "Only a PAID order can be handed over")
    if order["fulfillment_channel"] != "CARRYOUT":
        raise_err("ERR_INVALID_STATE", "Order is not a carryout order")
    for line in order_lines_of(order["id"]):
        if line["fulfillment_mode"] == "PICKUP_COUNTER":
            fulfilled = any(
                res["order_line_id"] == line["id"] and res["status"] == "FULFILLED"
                for res in DB.reservations.values())
            if not fulfilled:
                raise_err("ERR_INVALID_STATE",
                          "Every pickup-counter reservation must be fulfilled first")
    order["status"] = "FULFILLED"
    touch(order)
    return success(serialize(order), 200)


@app.post("/api/orders/<oid>/close")
def close_order_endpoint(oid):
    user_id, role = require_role("Customer")
    order = load_order_for_customer(oid, user_id, role)
    if order["status"] not in {"FULFILLED", "DELIVERED"}:
        raise_err("ERR_INVALID_STATE",
                  "Only a FULFILLED or DELIVERED order can be closed")
    if order["assembly_status"] not in {"NONE", "COMPLETED"}:
        raise_err("ERR_INVALID_STATE", "Assembly is still in progress")
    close_order(order)
    return success(serialize(order), 200)


# ---------------------------------------------------------------------------
# Stock reservations (§3.4)
# ---------------------------------------------------------------------------

@app.post("/api/reservations")
def create_reservation():
    body = get_body(required=True)
    store_id = req_str(body, "store_id")
    article_id = req_str(body, "article_id")
    qty = req_int(body, "qty", minimum=1)
    user_id, role = require_role("Customer")
    customer = get_or_404(DB.customers, user_id, "ERR_CUSTOMER_NOT_FOUND")
    store = get_or_404(DB.stores, store_id, "ERR_STORE_NOT_FOUND")
    article = get_or_404(DB.articles, article_id, "ERR_ARTICLE_NOT_FOUND")
    if article["pick_policy"] != "FULL_SERVE":
        raise_err("ERR_VALIDATION",
                  "Only FULL_SERVE articles can be reserved at the pickup counter")
    rows = check_line_stock(store["id"], article, qty)
    res = _base()
    res.update({
        "store_id": store["id"],
        "article_id": article["id"],
        "customer_id": customer["id"],
        "order_line_id": None,
        "qty": qty,
        "status": "ACTIVE",
        "reserved_at": now(),
        "expires_at": now() + RESERVATION_TTL,
    })
    DB.reservations[res["id"]] = res
    for bs in rows:
        bs["reserved"] += qty
        bump_bin_stock(bs)
    return success(serialize(res), 201)


@app.get("/api/reservations/<rid>")
def get_reservation(rid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    res = get_or_404(DB.reservations, rid, "ERR_RESERVATION_NOT_FOUND")
    if role == "Customer":
        check_customer_ownership(user_id, role, res["customer_id"])
    return success(serialize(res), 200)


@app.get("/api/reservations")
def list_reservations():
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    rows = list(DB.reservations.values())
    store_id = request.args.get("store_id")
    customer_id = request.args.get("customer_id")
    article_id = request.args.get("article_id")
    order_line_id = request.args.get("order_line_id")
    status = request.args.get("status")
    if role == "Customer":
        if customer_id is not None and customer_id != user_id:
            raise_err("ERR_FORBIDDEN", "Customer may only list its own reservations")
        rows = [r for r in rows if r["customer_id"] == user_id]
    elif customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if store_id is not None:
        rows = [r for r in rows if r["store_id"] == store_id]
    if article_id is not None:
        rows = [r for r in rows if r["article_id"] == article_id]
    if order_line_id is not None:
        rows = [r for r in rows if r["order_line_id"] == order_line_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r) for r in page], 200, meta)


@app.post("/api/reservations/<rid>/fulfill")
def fulfill_reservation(rid):
    require_role("StoreOps")
    res = get_or_404(DB.reservations, rid, "ERR_RESERVATION_NOT_FOUND")
    if res["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Only an ACTIVE reservation can be fulfilled")
    # Lazy expiry: at or after expires_at the reservation is already expired.
    if now() >= res["expires_at"]:
        res["status"] = "EXPIRED"
        touch(res)
        for carton in article_cartons(res["article_id"]):
            bs = bin_stock_for(res["store_id"], carton["id"])
            if bs is not None:
                bs["reserved"] -= res["qty"]
                bump_bin_stock(bs)
        raise_err("ERR_RESERVATION_EXPIRED",
                  "Reservation expired at its expires_at instant")
    for carton in article_cartons(res["article_id"]):
        bs = bin_stock_for(res["store_id"], carton["id"])
        if bs is not None:
            bs["reserved"] -= res["qty"]
            bs["on_hand"] -= res["qty"]
            bump_bin_stock(bs)
    res["status"] = "FULFILLED"
    touch(res)
    return success(serialize(res), 200)


@app.post("/api/reservations/<rid>/cancel")
def cancel_reservation(rid):
    user_id, role = require_role("Customer", "StoreOps")
    res = get_or_404(DB.reservations, rid, "ERR_RESERVATION_NOT_FOUND")
    if role == "Customer":
        check_customer_ownership(user_id, role, res["customer_id"])
    if res["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Only an ACTIVE reservation can be cancelled")
    for carton in article_cartons(res["article_id"]):
        bs = bin_stock_for(res["store_id"], carton["id"])
        if bs is not None:
            bs["reserved"] -= res["qty"]
            bump_bin_stock(bs)
    res["status"] = "CANCELLED"
    touch(res)
    return success(serialize(res), 200)


# ---------------------------------------------------------------------------
# Delivery slots & bookings (§3.5)
# ---------------------------------------------------------------------------

@app.post("/api/delivery-slots")
def create_slot():
    body = get_body(required=True)
    store_id = req_str(body, "store_id")
    service_date = parse_date(body.get("service_date"), "service_date")
    vehicle_id = req_str(body, "vehicle_id")
    zone = req_enum(body, "zone", ZONES)
    cap_w = req_number(body, "capacity_weight_kg", gt=0)
    cap_v = req_number(body, "capacity_volume_m3", gt=0)
    require_role("DeliveryCoordinator")
    store = get_or_404(DB.stores, store_id, "ERR_STORE_NOT_FOUND")
    slot = _base()
    slot.update({
        "store_id": store["id"],
        "service_date": service_date.isoformat(),
        "vehicle_id": vehicle_id,
        "zone": zone,
        "capacity_weight_kg": cap_w,
        "capacity_volume_m3": cap_v,
        "used_weight_kg": 0,
        "used_volume_m3": 0,
    })
    DB.delivery_slots[slot["id"]] = slot
    return success(serialize_slot(slot), 201)


@app.get("/api/delivery-slots/<sid>")
def get_slot(sid):
    require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                 "AssemblyProvider", "Customer")
    slot = get_or_404(DB.delivery_slots, sid, "ERR_SLOT_NOT_FOUND")
    return success(serialize_slot(slot), 200)


@app.get("/api/delivery-slots")
def list_slots():
    require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                 "AssemblyProvider", "Customer")
    rows = list(DB.delivery_slots.values())
    store_id = request.args.get("store_id")
    service_date = request.args.get("service_date")
    if store_id is not None:
        rows = [s for s in rows if s["store_id"] == store_id]
    if service_date is not None:
        rows = [s for s in rows if s["service_date"] == service_date]
    rows.sort(key=lambda s: s["created_at"])
    page, meta = paginate(rows)
    return success([serialize_slot(s) for s in page], 200, meta)


@app.get("/api/delivery-slots/<sid>/bookings")
def list_slot_bookings(sid):
    require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                 "AssemblyProvider", "Customer")
    slot = get_or_404(DB.delivery_slots, sid, "ERR_SLOT_NOT_FOUND")
    rows = [b for b in DB.delivery_bookings.values() if b["slot_id"] == slot["id"]]
    rows.sort(key=lambda b: b["created_at"])
    page, meta = list_all(rows)
    return success([serialize(b) for b in page], 200, meta)


def booking_totals(order):
    """Weight/volume derived from the order's lines and cartons (§3.5)."""
    total_w = 0.0
    total_v = 0.0
    for line in order_lines_of(order["id"]):
        cartons = article_cartons(line["article_id"])
        w = sum(c["weight_kg"] for c in cartons)
        v = sum(c["volume_m3"] for c in cartons)
        total_w += line["qty"] * w
        total_v += line["qty"] * v
    return total_w, total_v


def quote_fee(order, slot, access_type, total_w):
    """delivery_fee_quote (§3.5): zone base + weight surcharge + access fee,
    member discount rounded half-up once at the end."""
    if access_type == "WALKUP_HIGH":
        for line in order_lines_of(order["id"]):
            for carton in article_cartons(line["article_id"]):
                if carton["weight_kg"] > WALKUP_HIGH_MAX_CARTON_KG:
                    raise_err("ERR_ACCESS_INFEASIBLE",
                              "WALKUP_HIGH cannot service cartons over 40 kg")
    base = ZONE_BASE[slot["zone"]]
    if total_w <= WEIGHT_TIER1_KG:
        surcharge = 0
    elif total_w <= WEIGHT_TIER2_KG:
        surcharge = TIER2_FLAT_CENTS
    else:
        surcharge = TIER2_FLAT_CENTS + math.ceil(total_w - WEIGHT_TIER2_KG) \
            * OVERAGE_CENTS_PER_KG
    access_fee = WALKUP_HIGH_FEE_CENTS if access_type == "WALKUP_HIGH" else 0
    gross = base + surcharge + access_fee
    customer = DB.customers[order["customer_id"]]
    if customer["member_status"] == "ACTIVE":
        return rhu(Decimal(gross) * MEMBER_FEE_DISCOUNT)
    return gross


@app.post("/api/orders/<oid>/delivery-bookings")
def create_booking(oid):
    body = get_body(required=True)
    slot_id = req_str(body, "slot_id")
    access_type = req_enum(body, "access_type", ACCESS_TYPES)
    floor = req_int(body, "floor", minimum=0)
    expected_slot_version = req_int(body, "expected_slot_version")
    user_id, role = require_role("Customer")
    order = load_order_for_customer(oid, user_id, role)
    slot = get_or_404(DB.delivery_slots, slot_id, "ERR_SLOT_NOT_FOUND")
    # OCC (priority 5) precedes state checks (priority 6), §2.9.
    if expected_slot_version != slot["version"]:
        raise_err("ERR_STALE_VERSION", "Delivery slot version has advanced")
    if order["status"] != "PAID":
        raise_err("ERR_INVALID_STATE", "Only a PAID order can be booked")
    if order["fulfillment_channel"] != "DELIVERY":
        raise_err("ERR_INVALID_STATE", "Order channel is not DELIVERY")
    if order["delivery_status"] != "NONE":
        raise_err("ERR_DUPLICATE_BOOKING", "Order already has a booking")
    # Temporal rule (priority 7).
    service_date = datetime.strptime(slot["service_date"], "%Y-%m-%d").date()
    if service_date < now().date():
        raise_err("ERR_SLOT_IN_PAST", "Slot service_date is in the past")
    # Business constraints (priority 8).
    total_w, total_v = booking_totals(order)
    if (total_w > slot["capacity_weight_kg"]
            or total_v > slot["capacity_volume_m3"]):
        raise_err("ERR_BOOKING_NEVER_FITS",
                  "Booking alone exceeds the slot's total capacity")
    fee = quote_fee(order, slot, access_type, total_w)
    booking = _base()
    booking.update({
        "slot_id": slot["id"],
        "order_id": order["id"],
        "access_type": access_type,
        "floor": floor,
        "total_weight_kg": total_w,
        "total_volume_m3": total_v,
        "fee_cents": fee,
    })
    DB.delivery_bookings[booking["id"]] = booking
    if booking_fits(slot, total_w, total_v):
        confirm_booking(booking, slot)
    else:
        # WAITLISTED: no capacity, no stock consumed.
        booking["status"] = "WAITLISTED"
        touch(booking)
        order["delivery_status"] = "WAITLISTED"
        touch(order)
    return success(serialize(booking), 201)


def load_booking_for_customer(bid, user_id, role):
    booking = get_or_404(DB.delivery_bookings, bid, "ERR_BOOKING_NOT_FOUND")
    if role == "Customer":
        order = DB.orders.get(booking["order_id"])
        check_customer_ownership(user_id, role,
                                 order["customer_id"] if order else None)
    return booking


@app.get("/api/delivery-bookings/<bid>")
def get_booking(bid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    booking = load_booking_for_customer(bid, user_id, role)
    return success(serialize(booking), 200)


@app.post("/api/delivery-bookings/<bid>/cancel")
def cancel_booking(bid):
    user_id, role = require_role("Customer", "DeliveryCoordinator")
    booking = load_booking_for_customer(bid, user_id, role)
    order = DB.orders[booking["order_id"]]
    if booking["status"] == "CONFIRMED":
        slot = DB.delivery_slots[booking["slot_id"]]
        slot["used_weight_kg"] -= booking["total_weight_kg"]
        slot["used_volume_m3"] -= booking["total_volume_m3"]
        touch(slot)
        for line in order_lines_of(order["id"]):
            for carton in article_cartons(line["article_id"]):
                bs = bin_stock_for(order["store_id"], carton["id"])
                if bs is not None:
                    bs["reserved"] -= line["qty"]
                    bump_bin_stock(bs)
        booking["status"] = "CANCELLED"
        touch(booking)
        order["delivery_status"] = "NONE"
        touch(order)
        # Freed capacity triggers the waitlist waterfall (§3.5).
        waitlist_promotion(slot)
    elif booking["status"] == "WAITLISTED":
        booking["status"] = "CANCELLED"
        touch(booking)
        order["delivery_status"] = "NONE"
        touch(order)
    else:
        raise_err("ERR_INVALID_STATE",
                  "Only CONFIRMED or WAITLISTED bookings can be cancelled")
    return success(serialize(booking), 200)


@app.post("/api/delivery-bookings/<bid>/start")
def start_booking(bid):
    require_role("DeliveryCoordinator")
    booking = get_or_404(DB.delivery_bookings, bid, "ERR_BOOKING_NOT_FOUND")
    if booking["status"] != "CONFIRMED":
        raise_err("ERR_INVALID_STATE", "Only a CONFIRMED booking can start")
    booking["status"] = "OUT_FOR_DELIVERY"
    touch(booking)
    order = DB.orders[booking["order_id"]]
    order["delivery_status"] = "OUT_FOR_DELIVERY"
    touch(order)
    return success(serialize(booking), 200)


@app.post("/api/delivery-bookings/<bid>/complete")
def complete_booking(bid):
    require_role("DeliveryCoordinator")
    booking = get_or_404(DB.delivery_bookings, bid, "ERR_BOOKING_NOT_FOUND")
    if booking["status"] != "OUT_FOR_DELIVERY":
        raise_err("ERR_INVALID_STATE",
                  "Only an OUT_FOR_DELIVERY booking can complete")
    booking["status"] = "DELIVERED"
    touch(booking)
    order = DB.orders[booking["order_id"]]
    for line in order_lines_of(order["id"]):
        for carton in article_cartons(line["article_id"]):
            bs = bin_stock_for(order["store_id"], carton["id"])
            if bs is not None:
                bs["on_hand"] -= line["qty"]
                bs["reserved"] -= line["qty"]
                bump_bin_stock(bs)
    order["delivery_status"] = "DELIVERED"
    order["status"] = "DELIVERED"
    touch(order)
    # Auto-close evaluation: if assembly already completed, close on the spot.
    auto_close_evaluation(order)
    return success(serialize(booking), 200)


# ---------------------------------------------------------------------------
# Assembly standards & jobs (§3.6)
# ---------------------------------------------------------------------------

@app.post("/api/assembly-standards")
def create_standard():
    body = get_body(required=True)
    article_id = req_str(body, "article_id")
    minutes = req_int(body, "minutes_per_unit", minimum=1)
    crew_size = opt_int(body, "crew_size", default=1, minimum=1)
    require_role("PlatformAdmin")
    article = get_or_404(DB.articles, article_id, "ERR_ARTICLE_NOT_FOUND")
    if any(s["article_id"] == article["id"]
           for s in DB.assembly_standards.values()):
        raise_err("ERR_VALIDATION", "At most one standard per article")
    std = _base()
    std.update({"article_id": article["id"], "minutes_per_unit": minutes,
                "crew_size": crew_size})
    DB.assembly_standards[std["id"]] = std
    return success(serialize(std), 201)


@app.get("/api/assembly-standards/<sid>")
def get_standard(sid):
    require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                 "AssemblyProvider", "Customer")
    std = get_or_404(DB.assembly_standards, sid, "ERR_STANDARD_NOT_FOUND")
    return success(serialize(std), 200)


@app.get("/api/assembly-standards")
def list_standards():
    require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                 "AssemblyProvider", "Customer")
    rows = list(DB.assembly_standards.values())
    article_id = request.args.get("article_id")
    if article_id is not None:
        rows = [s for s in rows if s["article_id"] == article_id]
    rows.sort(key=lambda s: s["created_at"])
    page, meta = paginate(rows)
    return success([serialize(s) for s in page], 200, meta)


@app.post("/api/orders/<oid>/assembly-jobs")
def create_assembly_job(oid):
    body = get_body(required=True)
    provider_id = req_str(body, "provider_id")
    window_start = req_dt(body, "window_start")
    window_end = req_dt(body, "window_end")
    user_id, role = require_role("Customer")
    order = load_order_for_customer(oid, user_id, role)
    if order["status"] not in {"FULFILLED", "DELIVERED"}:
        raise_err("ERR_INVALID_STATE",
                  "Assembly requires a FULFILLED or DELIVERED order")
    if order["assembly_status"] != "NONE":
        raise_err("ERR_INVALID_STATE", "Assembly is already scheduled")
    # Temporal rules (priority 7).
    if window_start < now() or window_end <= window_start:
        raise_err("ERR_WINDOW_IN_PAST",
                  "Assembly window must lie in the future")
    # Crew-window conflict before the standard check (priority 8 ordering).
    for job in DB.assembly_jobs.values():
        if job["provider_id"] != provider_id or job["status"] not in JOB_ACTIVE_STATES:
            continue
        if (window_start < job["window_end"] + CREW_BUFFER
                and job["window_start"] - CREW_BUFFER < window_end):
            raise_err("ERR_CREW_WINDOW_CONFLICT",
                      "Window collides with another job of this provider")
    estimated = 0
    for line in order_lines_of(order["id"]):
        article = DB.articles[line["article_id"]]
        if not article["requires_assembly"]:
            continue
        std = next((s for s in DB.assembly_standards.values()
                    if s["article_id"] == article["id"]), None)
        if std is None:
            raise_err("ERR_STANDARD_MISSING",
                      "A requires_assembly line has no AssemblyStandard row")
        estimated += line["qty"] * std["minutes_per_unit"]
    job = _base()
    job.update({
        "order_id": order["id"],
        "provider_id": provider_id,
        "status": "REQUESTED",
        "window_start": window_start,
        "window_end": window_end,
        "estimated_minutes": estimated,
        "actual_minutes": None,
        "billed_minutes": None,
        "hold_reason": None,
    })
    DB.assembly_jobs[job["id"]] = job
    order["assembly_status"] = "SCHEDULED"
    touch(order)
    return success(serialize(job), 201)


def load_job_for_customer(jid, user_id, role):
    job = get_or_404(DB.assembly_jobs, jid, "ERR_JOB_NOT_FOUND")
    if role == "Customer":
        order = DB.orders.get(job["order_id"])
        check_customer_ownership(user_id, role,
                                 order["customer_id"] if order else None)
    return job


@app.get("/api/assembly-jobs/<jid>")
def get_job(jid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    job = load_job_for_customer(jid, user_id, role)
    return success(serialize(job), 200)


def _job_transition(jid, from_states, to_state):
    job = get_or_404(DB.assembly_jobs, jid, "ERR_JOB_NOT_FOUND")
    if job["status"] not in from_states:
        raise_err("ERR_INVALID_STATE",
                  f"Job must be in {sorted(from_states)} for this transition")
    job["status"] = to_state
    touch(job)
    return job


@app.post("/api/assembly-jobs/<jid>/dispatch")
def dispatch_job(jid):
    require_role("AssemblyProvider")
    job = _job_transition(jid, {"REQUESTED"}, "DISPATCHED")
    return success(serialize(job), 200)


@app.post("/api/assembly-jobs/<jid>/start")
def start_job(jid):
    require_role("AssemblyProvider")
    job = _job_transition(jid, {"DISPATCHED"}, "IN_PROGRESS")
    order = DB.orders[job["order_id"]]
    order["assembly_status"] = "IN_PROGRESS"
    touch(order)
    return success(serialize(job), 200)


@app.post("/api/assembly-jobs/<jid>/hold")
def hold_job(jid):
    body = get_body()
    hold_reason = opt_str(body, "hold_reason", default=None)
    require_role("AssemblyProvider")
    job = _job_transition(jid, {"IN_PROGRESS"}, "ON_HOLD")
    if hold_reason is not None:
        job["hold_reason"] = hold_reason
    return success(serialize(job), 200)


@app.post("/api/assembly-jobs/<jid>/resume")
def resume_job(jid):
    require_role("AssemblyProvider")
    job = _job_transition(jid, {"ON_HOLD"}, "IN_PROGRESS")
    return success(serialize(job), 200)


@app.post("/api/assembly-jobs/<jid>/complete")
def complete_job(jid):
    body = get_body(required=True)
    actual = req_int(body, "actual_minutes", minimum=0)
    require_role("AssemblyProvider")
    job = _job_transition(jid, {"IN_PROGRESS"}, "COMPLETED")
    job["actual_minutes"] = actual
    # capped_actual_billing: min(actual, ceil(estimated * 1.5)) — never more.
    cap = (job["estimated_minutes"] * BILLING_CAP_NUM + BILLING_CAP_DEN - 1) \
        // BILLING_CAP_DEN
    job["billed_minutes"] = min(actual, cap)
    order = DB.orders[job["order_id"]]
    order["assembly_status"] = "COMPLETED"
    touch(order)
    # Auto-close: an order sitting in FULFILLED or DELIVERED closes on the spot.
    auto_close_evaluation(order)
    return success(serialize(job), 200)


@app.post("/api/assembly-jobs/<jid>/cancel")
def cancel_job(jid):
    user_id, role = require_role("Customer")
    job = load_job_for_customer(jid, user_id, role)
    if job["status"] not in {"REQUESTED", "DISPATCHED"}:
        raise_err("ERR_INVALID_STATE",
                  "Once work has started, cancellation is no longer offered")
    job["status"] = "CANCELLED"
    touch(job)
    order = DB.orders[job["order_id"]]
    order["assembly_status"] = "NONE"
    touch(order)
    return success(serialize(job), 200)


# ---------------------------------------------------------------------------
# Spare-part claims (§3.7)
# ---------------------------------------------------------------------------

@app.post("/api/spare-part-claims")
def create_claim():
    body = get_body(required=True)
    article_id = req_str(body, "article_id")
    part_number = req_str(body, "part_number")
    part_value = req_int(body, "part_value_cents", minimum=0)
    reason = req_str(body, "reason")
    user_id, role = require_role("Customer")
    customer = get_or_404(DB.customers, user_id, "ERR_CUSTOMER_NOT_FOUND")
    article = get_or_404(DB.articles, article_id, "ERR_ARTICLE_NOT_FOUND")
    claim = _base()
    claim.update({
        "customer_id": customer["id"],
        "article_id": article["id"],
        "part_number": part_number,
        "part_value_cents": part_value,
        "reason": reason,
        "status": "SUBMITTED",
        "review_note": None,
    })
    DB.spare_part_claims[claim["id"]] = claim
    return success(serialize(claim), 201)


@app.get("/api/spare-part-claims/<cid>")
def get_claim(cid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    claim = get_or_404(DB.spare_part_claims, cid, "ERR_CLAIM_NOT_FOUND")
    if role == "Customer":
        check_customer_ownership(user_id, role, claim["customer_id"])
    return success(serialize(claim), 200)


@app.get("/api/spare-part-claims")
def list_claims():
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    rows = list(DB.spare_part_claims.values())
    customer_id = request.args.get("customer_id")
    article_id = request.args.get("article_id")
    status = request.args.get("status")
    if role == "Customer":
        if customer_id is not None and customer_id != user_id:
            raise_err("ERR_FORBIDDEN", "Customer may only list its own claims")
        rows = [c for c in rows if c["customer_id"] == user_id]
    elif customer_id is not None:
        rows = [c for c in rows if c["customer_id"] == customer_id]
    if article_id is not None:
        rows = [c for c in rows if c["article_id"] == article_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows.sort(key=lambda c: c["created_at"])
    page, meta = paginate(rows)
    return success([serialize(c) for c in page], 200, meta)


@app.post("/api/spare-part-claims/<cid>/review")
def review_claim(cid):
    body = get_body(required=True)
    decision = req_enum(body, "decision", {"APPROVE", "DENY"})
    review_note = opt_str(body, "review_note", default=None)
    require_role("StoreOps")
    claim = get_or_404(DB.spare_part_claims, cid, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Only a SUBMITTED claim can be reviewed")
    if decision == "APPROVE":
        # Eligibility over the rolling 365-day window; count first, then value.
        window_start = now() - timedelta(days=365)
        prior = [c for c in DB.spare_part_claims.values()
                 if c["customer_id"] == claim["customer_id"]
                 and c["status"] in {"APPROVED", "SHIPPED"}
                 and window_start <= c["created_at"] <= now()]
        if len(prior) >= MAX_CLAIMS_365D:
            raise_err("ERR_CLAIM_LIMIT_EXCEEDED",
                      "3 approved/shipped claims already in the rolling window")
        if (sum(c["part_value_cents"] for c in prior)
                + claim["part_value_cents"] > MAX_CLAIM_VALUE_365D_CENTS):
            raise_err("ERR_CLAIM_VALUE_EXCEEDED",
                      "Rolling 365-day claim value would exceed 3000 cents")
        claim["status"] = "APPROVED"
    else:
        claim["status"] = "DENIED"
    if review_note is not None:
        claim["review_note"] = review_note
    touch(claim)
    return success(serialize(claim), 200)


@app.post("/api/spare-part-claims/<cid>/ship")
def ship_claim(cid):
    require_role("StoreOps")
    claim = get_or_404(DB.spare_part_claims, cid, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "Only an APPROVED claim can be shipped")
    claim["status"] = "SHIPPED"
    touch(claim)
    return success(serialize(claim), 200)


# ---------------------------------------------------------------------------
# Returns (§3.8)
# ---------------------------------------------------------------------------

GRADE_RANK = {"LIKE_NEW": 0, "OPEN_BOX": 1, "DAMAGED": 2, "SCRAP": 3}


def effective_grade(line):
    """condition_grade capped at OPEN_BOX when assembly_state != UNOPENED."""
    grade = line["condition_grade"]
    if grade is None:
        return None
    if line["assembly_state"] in {"PARTIALLY_ASSEMBLED", "ASSEMBLED"} \
            and GRADE_RANK[grade] < GRADE_RANK["OPEN_BOX"]:
        return "OPEN_BOX"
    return grade


def serialize_return_line(line):
    out = serialize(line)
    out["effective_condition_grade"] = effective_grade(line)
    return out


@app.post("/api/returns")
def create_return():
    body = get_body()
    order_id = body.get("order_id")
    if order_id is not None and not isinstance(order_id, str):
        raise_err("ERR_VALIDATION", "order_id must be a string or null")
    user_id, role = require_role("Customer")
    customer = get_or_404(DB.customers, user_id, "ERR_CUSTOMER_NOT_FOUND")
    order = None
    if order_id is not None:
        order = get_or_404(DB.orders, order_id, "ERR_ORDER_NOT_FOUND")
        check_customer_ownership(user_id, role, order["customer_id"])
        if order["status"] not in {"FULFILLED", "DELIVERED", "CLOSED"}:
            raise_err("ERR_ORDER_NOT_RETURNABLE",
                      "Order is not in FULFILLED, DELIVERED, or CLOSED")
    ret = _base()
    ret.update({
        "customer_id": customer["id"],
        "order_id": order["id"] if order else None,
        "receipted": order is not None,
        "status": "DRAFT",
        "refund_total_cents": 0,
        "writeoff_total_cents": 0,
    })
    DB.return_requests[ret["id"]] = ret
    return success(serialize(ret), 201)


def load_return_for_customer(rid, user_id, role):
    ret = get_or_404(DB.return_requests, rid, "ERR_RETURN_NOT_FOUND")
    if role == "Customer":
        check_customer_ownership(user_id, role, ret["customer_id"])
    return ret


@app.get("/api/returns/<rid>")
def get_return(rid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    ret = load_return_for_customer(rid, user_id, role)
    return success(serialize(ret), 200)


@app.get("/api/returns")
def list_returns():
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    rows = list(DB.return_requests.values())
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    if role == "Customer":
        if customer_id is not None and customer_id != user_id:
            raise_err("ERR_FORBIDDEN", "Customer may only list its own returns")
        rows = [r for r in rows if r["customer_id"] == user_id]
    elif customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    page, meta = paginate(rows)
    return success([serialize(r) for r in page], 200, meta)


@app.post("/api/returns/<rid>/lines")
def add_return_line(rid):
    body = get_body(required=True)
    article_id = req_str(body, "article_id")
    qty = req_int(body, "qty", minimum=1)
    assembly_state = req_enum(body, "assembly_state", ASSEMBLY_STATES)
    order_line_id = body.get("order_line_id")
    if order_line_id is not None and not isinstance(order_line_id, str):
        raise_err("ERR_VALIDATION", "order_line_id must be a string or null")
    user_id, role = require_role("Customer")
    ret = load_return_for_customer(rid, user_id, role)
    article = get_or_404(DB.articles, article_id, "ERR_ARTICLE_NOT_FOUND")
    if ret["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Lines may be added only to a DRAFT return")
    order_line = None
    if ret["receipted"]:
        # A receipted line must reference a line of the receipted order.
        if order_line_id is None:
            raise_err("ERR_VALIDATION",
                      "A receipted return line requires order_line_id")
        order_line = get_or_404(DB.order_lines, order_line_id,
                                "ERR_ORDER_LINE_NOT_FOUND")
        if order_line["order_id"] != ret["order_id"]:
            raise_err("ERR_VALIDATION",
                      "order_line_id must reference a line of the receipted order")
        if order_line["article_id"] != article["id"]:
            raise_err("ERR_VALIDATION",
                      "article_id must match the referenced order line")
        remaining = order_line["qty"] - order_line["returned_qty"]
        if qty > remaining:
            raise_err("ERR_RETURN_QTY_EXCEEDED",
                      "Return qty exceeds the purchased remainder")
    else:
        if order_line_id is not None:
            raise_err("ERR_VALIDATION",
                      "A no-receipt return line leaves order_line_id null")
        # No-receipt returns are a member privilege.
        customer = DB.customers[ret["customer_id"]]
        if customer["member_status"] != "ACTIVE":
            raise_err("ERR_RECEIPT_REQUIRED",
                      "No-receipt returns require ACTIVE family membership")
    line = _base()
    line.update({
        "return_id": ret["id"],
        "article_id": article["id"],
        "order_line_id": order_line["id"] if order_line else None,
        "qty": qty,
        "assembly_state": assembly_state,
        "condition_grade": None,
        "unit_basis_cents": None,
        "refund_cents": None,
        "writeoff_cents": None,
        "restocked_units": 0,
    })
    DB.return_lines[line["id"]] = line
    touch(ret)
    return success(serialize_return_line(line), 201)


@app.get("/api/returns/<rid>/lines")
def list_return_lines(rid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    ret = load_return_for_customer(rid, user_id, role)
    rows = [l for l in DB.return_lines.values() if l["return_id"] == ret["id"]]
    rows.sort(key=lambda l: l["created_at"])
    page, meta = list_all(rows)
    return success([serialize_return_line(l) for l in page], 200, meta)


@app.get("/api/return-lines/<lid>")
def get_return_line(lid):
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    line = get_or_404(DB.return_lines, lid, "ERR_RETURN_LINE_NOT_FOUND")
    if role == "Customer":
        ret = DB.return_requests.get(line["return_id"])
        check_customer_ownership(user_id, role,
                                 ret["customer_id"] if ret else None)
    return success(serialize_return_line(line), 200)


@app.get("/api/return-lines")
def list_return_lines_global():
    user_id, role = require_role("PlatformAdmin", "StoreOps", "DeliveryCoordinator",
                                 "AssemblyProvider", "Customer")
    rows = list(DB.return_lines.values())
    if role == "Customer":
        own_returns = {r["id"] for r in DB.return_requests.values()
                       if r["customer_id"] == user_id}
        rows = [l for l in rows if l["return_id"] in own_returns]
    return_id = request.args.get("return_id")
    article_id = request.args.get("article_id")
    order_line_id = request.args.get("order_line_id")
    if return_id is not None:
        rows = [l for l in rows if l["return_id"] == return_id]
    if article_id is not None:
        rows = [l for l in rows if l["article_id"] == article_id]
    if order_line_id is not None:
        rows = [l for l in rows if l["order_line_id"] == order_line_id]
    rows.sort(key=lambda l: l["created_at"])
    page, meta = paginate(rows)
    return success([serialize_return_line(l) for l in page], 200, meta)


@app.post("/api/returns/<rid>/submit")
def submit_return(rid):
    user_id, role = require_role("Customer")
    ret = load_return_for_customer(rid, user_id, role)
    if ret["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Only a DRAFT return can be submitted")
    lines = [l for l in DB.return_lines.values() if l["return_id"] == ret["id"]]
    if not lines:
        raise_err("ERR_INVALID_STATE", "Submitting requires at least one line")
    ret["status"] = "SUBMITTED"
    touch(ret)
    return success(serialize(ret), 200)


@app.post("/api/returns/<rid>/lines/<lid>/grade")
def grade_return_line(rid, lid):
    body = get_body(required=True)
    grade = req_enum(body, "condition_grade", CONDITION_GRADES)
    require_role("StoreOps")
    # Nested path resolution is left to right: return first, line second (§2.8).
    ret = get_or_404(DB.return_requests, rid, "ERR_RETURN_NOT_FOUND")
    line = get_or_404(DB.return_lines, lid, "ERR_RETURN_LINE_NOT_FOUND")
    if line["return_id"] != ret["id"]:
        raise_err("ERR_RETURN_LINE_NOT_FOUND",
                  "Line does not belong to this return")
    if ret["status"] not in {"SUBMITTED", "GRADING"}:
        raise_err("ERR_INVALID_STATE", "Return is not awaiting grading")
    line["condition_grade"] = grade
    touch(line)
    # The very first graded line moves the request SUBMITTED -> GRADING.
    if ret["status"] == "SUBMITTED":
        ret["status"] = "GRADING"
        touch(ret)
    return success(serialize_return_line(line), 200)


def settle_restock(ret, reverse=False):
    """Apply (or reverse) the settle-time restock and returned_qty rollups."""
    sign = -1 if reverse else 1
    lines = [l for l in DB.return_lines.values() if l["return_id"] == ret["id"]]
    for line in lines:
        if line["order_line_id"] is None:
            continue
        order_line = DB.order_lines[line["order_line_id"]]
        order = DB.orders[order_line["order_id"]]
        eff = effective_grade(line)
        if eff == "LIKE_NEW":
            for carton in article_cartons(line["article_id"]):
                bs = bin_stock_for(order["store_id"], carton["id"])
                if bs is not None:
                    bs["on_hand"] += sign * line["qty"]
                    bump_bin_stock(bs)
            if reverse:
                line["restocked_units"] = 0
            else:
                line["restocked_units"] = line["qty"]
        order_line["returned_qty"] += sign * line["qty"]
        touch(order_line)
        if reverse:
            touch(line)


@app.post("/api/returns/<rid>/settle")
def settle_return(rid):
    require_role("StoreOps")
    ret = get_or_404(DB.return_requests, rid, "ERR_RETURN_NOT_FOUND")
    lines = [l for l in DB.return_lines.values() if l["return_id"] == ret["id"]]
    if ret["status"] == "SUBMITTED":
        raise_err("ERR_UNGRADED_LINES", "Return lines have not been graded")
    if ret["status"] != "GRADING":
        raise_err("ERR_INVALID_STATE", "Only a GRADING return can be settled")
    if any(l["condition_grade"] is None for l in lines):
        raise_err("ERR_UNGRADED_LINES",
                  "Every line must be graded before settlement")
    # return_refund: per-line rounding half-up, then summed (§3.8).
    refund_total = 0
    writeoff_total = 0
    for line in lines:
        eff = effective_grade(line)
        factor = GRADE_FACTOR[eff]
        if line["order_line_id"] is not None:
            order_line = DB.order_lines[line["order_line_id"]]
            basis = order_line["effective_unit_paid_cents"]
            line["unit_basis_cents"] = basis
        else:
            article = DB.articles[line["article_id"]]
            lowest = article["lowest_price_365d_cents"]
            if lowest is None:
                lowest = article["price_cents"]
            basis = rhu(Decimal(lowest) * NO_RECEIPT_FACTOR)
            line["unit_basis_cents"] = basis
        refund = rhu(Decimal(basis) * Decimal(line["qty"]) * factor)
        line["refund_cents"] = refund
        if line["order_line_id"] is not None:
            line["writeoff_cents"] = basis * line["qty"] - refund
        else:
            line["writeoff_cents"] = 0
        refund_total += refund
        writeoff_total += line["writeoff_cents"]
        touch(line)
    ret["refund_total_cents"] = refund_total
    ret["writeoff_total_cents"] = writeoff_total
    ret["status"] = "SETTLED"
    touch(ret)
    settle_restock(ret, reverse=False)
    return success(serialize(ret), 200)


@app.post("/api/returns/<rid>/dispute")
def dispute_return(rid):
    user_id, role = require_role("Customer")
    ret = load_return_for_customer(rid, user_id, role)
    if ret["status"] != "SETTLED":
        raise_err("ERR_INVALID_STATE", "Only a SETTLED return can be disputed")
    # Reverse the previous settlement in kind: un-restock, roll returned_qty back.
    settle_restock(ret, reverse=True)
    ret["status"] = "DISPUTED"
    touch(ret)
    return success(serialize(ret), 200)


@app.post("/api/returns/<rid>/reopen")
def reopen_return(rid):
    require_role("StoreOps")
    ret = get_or_404(DB.return_requests, rid, "ERR_RETURN_NOT_FOUND")
    if ret["status"] != "DISPUTED":
        raise_err("ERR_INVALID_STATE", "Only a DISPUTED return can be reopened")
    ret["status"] = "GRADING"
    touch(ret)
    return success(serialize(ret), 200)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # threaded=True: under the 8-round parallel sweep, a keep-alive probe or
    # slow-close connection on the single-threaded Werkzeug server would block
    # subsequent requests on a fresh socket ("Connection reset by peer").
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
