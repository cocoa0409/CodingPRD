"""Clock, Brand, Location and Item endpoints."""

from datetime import datetime

from flask import Blueprint, request

import calculations as calc
import db
import middleware as mw
import response as resp
import serializers as ser
from errors import ApiError

bp = Blueprint("catalog", __name__)

ALL_INTERNAL = ["PlatformAdmin", "AssortmentPlanner", "BoutiqueManager", "RetailLead"]

BRAND_INPUT_DEFAULTS = {
    "retail_recognition_policy": "FINAL_ONLY",
    "liquidation_trigger_rpg_cents": 700,
    "open_receipt_grace_hours": 24,
    "transfer_variance_tolerance_bps": 200,
    "waiting_area_retail_weight_bps": 6000,
    "tip_minimum_minutes": 240,
    "clearance_buffer_hours": 24,
    "food_storage_corridor_units": 40,
    "max_check_total_cents": 50000,
    "fiscal_period_status": "OPEN",
    "provisional_retail_revenue_cents": 0,
    "recognized_retail_revenue_cents": 0,
    "brand_retail_sales_per_guest_cents": 0,
}

BRAND_UPDATABLE = [
    "retail_recognition_policy", "liquidation_trigger_rpg_cents", "open_receipt_grace_hours",
    "transfer_variance_tolerance_bps", "waiting_area_retail_weight_bps", "tip_minimum_minutes",
    "clearance_buffer_hours", "food_storage_corridor_units", "max_check_total_cents",
    "fiscal_period", "fiscal_period_status",
]

BRAND_ENUMS = {
    "retail_recognition_policy": {"FINAL_ONLY", "PROVISIONAL_THEN_FINAL"},
    "fiscal_period_status": {"OPEN", "CLOSED"},
}

BRAND_BOUNDS = {
    "liquidation_trigger_rpg_cents": (0, None),
    "open_receipt_grace_hours": (0, None),
    "transfer_variance_tolerance_bps": (0, 10000),
    "waiting_area_retail_weight_bps": (0, 10000),
    "tip_minimum_minutes": (0, None),
    "clearance_buffer_hours": (0, None),
    "food_storage_corridor_units": (0, None),
    "max_check_total_cents": (1, None),
}


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_current_utc():
    ctx = mw.context()
    mw.require_role(ctx, ["PlatformAdmin"])
    data = mw.body()
    target = db.parse_ts(mw.required(data, "to_iso8601"), "to_iso8601")
    db.set_clock(target)
    return resp.ok({"current_utc": db.current_utc_str()})


# ---------------------------------------------------------------------------
# Brand
# ---------------------------------------------------------------------------

@bp.post("/retail-ops/brands")
def create_brand():
    ctx = mw.context()
    mw.require_role(ctx, ["PlatformAdmin"])
    data = mw.body()

    brand_code = mw.required(data, "brand_code")
    for rec in db.brands.values():
        if rec.get("brand_code") == brand_code:
            raise ApiError("ERR_INVALID_REQUEST", "brand_code already exists across the fleet.")

    payload = {
        "brand_code": brand_code,
        "legal_name": mw.required(data, "legal_name"),
        "fiscal_period": mw.required(data, "fiscal_period"),
    }
    for field, default in BRAND_INPUT_DEFAULTS.items():
        if field in ("fiscal_period_status", "provisional_retail_revenue_cents",
                     "recognized_retail_revenue_cents", "brand_retail_sales_per_guest_cents"):
            payload[field] = default
            continue
        if field in ("retail_recognition_policy", "fiscal_period"):
            continue
        payload[field] = mw.optional(data, field, default, int)
    payload["retail_recognition_policy"] = mw.optional(
        data, "retail_recognition_policy", BRAND_INPUT_DEFAULTS["retail_recognition_policy"])

    _validate_brand_fields(payload, strict=False)
    rec = db.new_record(payload)
    db.brands[rec["id"]] = rec
    return resp.ok(ser.brand(rec), 201)


@bp.get("/retail-ops/brands")
def list_brands():
    ctx = mw.context()
    mw.require_role(ctx, ALL_INTERNAL)
    records = resp.order_records([
        r for r in db.brands.values() if mw.matches(r, {"brand_code": mw.query_str("brand_code")})])
    limit, offset = resp.read_pagination(request.args)
    page, pagination = resp.paginate(records, limit, offset)
    return resp.ok([ser.brand(r) for r in page], pagination=pagination)


@bp.get("/retail-ops/brands/<brand_id>")
def get_brand(brand_id):
    ctx = mw.context()
    mw.require_role(ctx, ALL_INTERNAL)
    rec = db.get_or_404(db.brands, brand_id, "ERR_BRAND_NOT_FOUND")
    return resp.ok(ser.brand(rec))


@bp.put("/retail-ops/brands/<brand_id>")
def update_brand(brand_id):
    ctx = mw.context()
    mw.require_role(ctx, ["PlatformAdmin"])
    rec = db.get_or_404(db.brands, brand_id, "ERR_BRAND_NOT_FOUND")
    data = mw.body()

    updates = {}
    for field in BRAND_UPDATABLE:
        if field not in data or data[field] is None:
            continue
        # `fiscal_period` and `fiscal_period_status` are enums; the rest are ints.
        kind = str if field in BRAND_ENUMS or field == "fiscal_period" else int
        updates[field] = mw.coerce(data[field], field, kind)

    _validate_brand_fields(updates, strict=False)
    rec.update(updates)
    db.touch(rec)

    if "food_storage_corridor_units" in updates:
        for loc in db.locations.values():
            if loc.get("brand_id") == rec["id"]:
                calc.recompute_location_posture(loc)

    return resp.ok(ser.brand(rec))


def _validate_brand_fields(fields, strict=True):
    for field, allowed in BRAND_ENUMS.items():
        if field in fields and fields[field] not in allowed:
            raise ApiError("ERR_INVALID_REQUEST", "%s must be one of %s." % (field, sorted(allowed)))
    for field, (low, high) in BRAND_BOUNDS.items():
        if field not in fields:
            continue
        value = fields[field]
        if not isinstance(value, int):
            raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % field)
        if low is not None and value < low:
            raise ApiError("ERR_INVALID_REQUEST", "%s must be at least %s." % (field, low))
        if high is not None and value > high:
            raise ApiError("ERR_INVALID_REQUEST", "%s must be at most %s." % (field, high))


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

REGION_CODES = {"NORTHEAST", "SOUTHEAST", "MIDWEST", "SOUTHWEST", "WEST"}
ASSORTMENT_TIERS = {"FULL", "REGIONAL_TWEAK", "MINIMAL"}


@bp.post("/retail-ops/locations")
def create_location():
    ctx = mw.context()
    mw.require_role(ctx, ["PlatformAdmin"])
    data = mw.body()

    brand_id = mw.required(data, "brand_id")
    brand_rec = db.get_or_404(db.brands, brand_id, "ERR_BRAND_NOT_FOUND")

    store_number = mw.required(data, "store_number")
    for rec in db.locations.values():
        if rec.get("brand_id") == brand_rec["id"] and rec.get("store_number") == store_number:
            raise ApiError("ERR_INVALID_REQUEST", "store_number already exists within this brand.")

    region_code = mw.required(data, "region_code")
    if region_code not in REGION_CODES:
        raise ApiError("ERR_INVALID_REQUEST", "region_code is not a declared region.")
    assortment_tier = mw.required(data, "assortment_tier")
    if assortment_tier not in ASSORTMENT_TIERS:
        raise ApiError("ERR_INVALID_REQUEST", "assortment_tier is not a declared tier.")

    capacity = mw.required(data, "backroom_capacity_units", int)
    if capacity <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "backroom_capacity_units must be greater than zero.")

    clearance_max = mw.optional(data, "clearance_max_active", 3, int)
    if clearance_max < 1:
        raise ApiError("ERR_INVALID_REQUEST", "clearance_max_active must be at least 1.")
    local_events = mw.optional(data, "local_event_codes", [], list)

    payload = {
        "brand_id": brand_rec["id"],
        "store_number": store_number,
        "region_code": region_code,
        "assortment_tier": assortment_tier,
        "backroom_capacity_units": capacity,
        "clearance_max_active": clearance_max,
        "local_event_codes": local_events,
        "backroom_occupancy_units": 0,
        "backroom_committed_units": 0,
        "food_storage_units": 0,
        "active_clearance_count": 0,
        "active_planogram_version_id": None,
        "staging_free_units": capacity - brand_rec.get("food_storage_corridor_units", 40),
    }
    rec = db.new_record(payload)
    db.locations[rec["id"]] = rec
    return resp.ok(ser.location(rec), 201)


@bp.get("/retail-ops/locations")
def list_locations():
    ctx = mw.context()
    mw.require_role(ctx, ALL_INTERNAL)
    records = resp.order_records([r for r in db.locations.values() if mw.matches(r, {
        "brand_id": mw.query_str("brand_id"),
        "region_code": mw.query_str("region_code"),
        "assortment_tier": mw.query_str("assortment_tier"),
    })])
    limit, offset = resp.read_pagination(request.args)
    page, pagination = resp.paginate(records, limit, offset)
    return resp.ok([ser.location(r) for r in page], pagination=pagination)


@bp.get("/retail-ops/locations/<location_id>")
def get_location(location_id):
    ctx = mw.context()
    mw.require_role(ctx, ALL_INTERNAL)
    rec = db.get_or_404(db.locations, location_id, "ERR_LOCATION_NOT_FOUND")
    return resp.ok(ser.location(rec))


# ---------------------------------------------------------------------------
# Item
# ---------------------------------------------------------------------------

THEMES = {"HARVEST", "WINTER_HOLIDAY", "SPRING", "SUMMER", "NOSTALGIA_CLASSIC"}


def _load_item(data):
    theme_code = mw.required(data, "theme_code")
    if theme_code not in THEMES:
        raise ApiError("ERR_INVALID_REQUEST", "theme_code is not a declared theme.")
    retail = mw.required(data, "unit_retail_cents", int)
    if retail <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "unit_retail_cents must be greater than zero.")
    cost = mw.required(data, "unit_cost_cents", int)
    if cost < 0:
        raise ApiError("ERR_INVALID_REQUEST", "unit_cost_cents must not be negative.")
    lead = mw.required(data, "import_lead_time_days", int)
    if lead < 0:
        raise ApiError("ERR_INVALID_REQUEST", "import_lead_time_days must not be negative.")
    return {
        "sku": mw.required(data, "sku"),
        "name": mw.required(data, "name"),
        "theme_code": theme_code,
        "nostalgia_flag": mw.optional(data, "nostalgia_flag", False, bool),
        "unit_retail_cents": retail,
        "unit_cost_cents": cost,
        "import_lead_time_days": lead,
    }


@bp.post("/retail-ops/items")
def create_item():
    ctx = mw.context()
    mw.require_role(ctx, ["AssortmentPlanner"])
    data = mw.body()
    payload = _load_item(data)

    for rec in db.items.values():
        if rec.get("sku") == payload["sku"]:
            raise ApiError("ERR_INVALID_REQUEST", "sku already exists across the brand.")

    payload.update({
        "status": "ACTIVE",
        "current_markdown_pct": 0.0,
        "effective_price_cents": payload["unit_retail_cents"],
        "compounded_price_cents": payload["unit_retail_cents"],
        "on_hand_units": 0,
        "order_deadline_reached": False,
        "clearance_week": 0,
    })
    rec = db.new_record(payload)
    db.items[rec["id"]] = rec
    return resp.ok(ser.item(rec), 201)


@bp.get("/retail-ops/items")
def list_items():
    ctx = mw.context()
    mw.require_role(ctx, ALL_INTERNAL)
    records = resp.order_records([r for r in db.items.values() if mw.matches(r, {
        "theme_code": mw.query_str("theme_code"),
        "status": mw.query_str("status"),
        "nostalgia_flag": mw.query_bool("nostalgia_flag"),
    })])
    limit, offset = resp.read_pagination(request.args)
    page, pagination = resp.paginate(records, limit, offset)
    return resp.ok([ser.item(r) for r in page], pagination=pagination)


@bp.get("/retail-ops/items/<item_id>")
def get_item(item_id):
    ctx = mw.context()
    mw.require_role(ctx, ALL_INTERNAL)
    rec = db.get_or_404(db.items, item_id, "ERR_ITEM_NOT_FOUND")
    return resp.ok(ser.item(rec))


@bp.post("/retail-ops/items/<item_id>/order-deadline-check")
def order_deadline_check(item_id):
    ctx = mw.context()
    mw.require_role(ctx, ["AssortmentPlanner", "RetailLead"])
    rec = db.get_or_404(db.items, item_id, "ERR_ITEM_NOT_FOUND")
    rec["order_deadline_reached"] = calc.derive_order_deadline(rec)
    rec["clearance_week"] = calc.item_clearance_week(rec)
    db.touch(rec)
    return resp.ok(ser.item(rec))


@bp.get("/retail-ops/items/<item_id>/import-plan")
def import_plan(item_id):
    ctx = mw.context()
    mw.require_role(ctx, ["AssortmentPlanner", "RetailLead"])
    rec = db.get_or_404(db.items, item_id, "ERR_ITEM_NOT_FOUND")
    deadline = calc.derive_order_deadline(rec)
    payload = {
        "projected_import_need_units": calc.projected_import_need(rec, deadline),
        "order_deadline_reached": deadline,
        "unit_margin_cents": calc.unit_margin_cents(rec),
        "margin_floor_cents": calc.margin_floor_cents(rec),
    }
    return resp.ok(payload)