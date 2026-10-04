"""Clock, stores, ingredients, marketplace channels routes."""

from flask import Blueprint, request

from db import db, fresh_timestamp
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_STORE_NOT_FOUND,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    new_resource, touch, parse_iso, iso_str, parse_pagination, paginate,
    require_fields, require_int, require_number, require_string,
    get_store_or_404, get_ingredient_or_404, get_channel_or_404,
    fire_clock_transitions,
)

bp = Blueprint("admin", __name__)

ALL_READ_ROLES = ("PlatformAdmin", "StoreManager", "GeneralManager", "LineWorker")


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["to_iso8601"])
    target = parse_iso(payload["to_iso8601"])
    db.clock = target
    fire_clock_transitions()
    return success_object({"current_utc": iso_str(db.clock)}, 200)


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------

@bp.post("/stores")
def create_store():
    require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, [
        "store_code", "name", "digital_line_capacity_per_interval",
        "instore_line_capacity_per_interval", "pacing_interval_minutes",
        "overage_threshold_pct", "marketplace_commission_pct",
    ])
    store_code = require_string(payload, "store_code")
    name = require_string(payload, "name")
    digital_cap = require_int(payload, "digital_line_capacity_per_interval", minimum=1)
    instore_cap = require_int(payload, "instore_line_capacity_per_interval", minimum=1)
    pacing = require_int(payload, "pacing_interval_minutes", minimum=1)
    overage = require_number(payload, "overage_threshold_pct")
    commission = require_number(payload, "marketplace_commission_pct")
    forecast = payload.get("forecast_day_cents", 0)
    if isinstance(forecast, bool) or not isinstance(forecast, int):
        raise_error(ERR_INVALID_REQUEST, "forecast_day_cents must be an integer")
    instore_promise = payload.get("instore_promise_minutes", 15)
    if isinstance(instore_promise, bool) or not isinstance(instore_promise, int) or instore_promise < 1:
        raise_error(ERR_INVALID_REQUEST, "instore_promise_minutes must be an integer >= 1")

    store = new_resource()
    store.update({
        "store_code": store_code,
        "name": name,
        "digital_line_capacity_per_interval": digital_cap,
        "instore_line_capacity_per_interval": instore_cap,
        "pacing_interval_minutes": pacing,
        "instore_promise_minutes": instore_promise,
        "overage_threshold_pct": overage,
        "marketplace_commission_pct": commission,
        "digital_interval_load": 0,
        "instore_interval_load": 0,
        "throttle_state": "OPEN",
        "forecast_day_cents": forecast,
        "theoretical_food_cost_cents": 0,
        "actual_food_cost_cents": 0,
        "food_cost_variance_bps": 0,
        "current_business_day": db.clock.strftime("%Y-%m-%d"),
    })
    db.stores[store["id"]] = store
    return success_object(store, 201)


@bp.get("/stores")
def list_stores():
    require_roles(*ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items, total = paginate(list(db.stores.values()), limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/stores/<store_id>")
def get_store(store_id):
    require_roles(*ALL_READ_ROLES)
    store = get_store_or_404(store_id)
    return success_object(store)


# ---------------------------------------------------------------------------
# Ingredients
# ---------------------------------------------------------------------------

@bp.post("/ingredients")
def create_ingredient():
    require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, [
        "ingredient_code", "display_name", "unit_cost_cents_per_gram",
        "par_level_grams", "hold_time_minutes", "batch_size_grams",
    ])
    ing = new_resource()
    ing.update({
        "ingredient_code": require_string(payload, "ingredient_code"),
        "display_name": require_string(payload, "display_name"),
        "unit_cost_cents_per_gram": require_number(payload, "unit_cost_cents_per_gram"),
        "par_level_grams": require_int(payload, "par_level_grams", minimum=0),
        "hold_time_minutes": require_int(payload, "hold_time_minutes", minimum=0),
        "batch_size_grams": require_int(payload, "batch_size_grams", minimum=0),
        "on_hand_grams": 0,
        "shortage_state": "STOCKED",
    })
    db.ingredients[ing["id"]] = ing
    return success_object(ing, 201)


@bp.get("/ingredients")
def list_ingredients():
    require_roles(*ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items, total = paginate(list(db.ingredients.values()), limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/ingredients/<ingredient_id>")
def get_ingredient(ingredient_id):
    require_roles(*ALL_READ_ROLES)
    ing = get_ingredient_or_404(ingredient_id)
    return success_object(ing)


# ---------------------------------------------------------------------------
# Marketplace channels
# ---------------------------------------------------------------------------

@bp.post("/marketplace-channels")
def create_channel():
    require_roles("PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["channel_code", "markup_pct", "commission_pct"])
    active = payload.get("active", True)
    if not isinstance(active, bool):
        raise_error(ERR_INVALID_REQUEST, "active must be a boolean")
    markup_pct = require_number(payload, "markup_pct")
    commission_pct = require_number(payload, "commission_pct")
    if markup_pct < 0:
        raise_error(ERR_INVALID_REQUEST, "markup_pct must not be negative")
    if commission_pct < 0:
        raise_error(ERR_INVALID_REQUEST, "commission_pct must not be negative")
    ch = new_resource()
    ch.update({
        "channel_code": require_string(payload, "channel_code"),
        "markup_pct": markup_pct,
        "commission_pct": commission_pct,
        "active": active,
    })
    db.marketplace_channels[ch["id"]] = ch
    return success_object(ch, 201)


@bp.get("/marketplace-channels")
def list_channels():
    require_roles("PlatformAdmin", "StoreManager", "GeneralManager")
    limit, offset = parse_pagination(request.args)
    items, total = paginate(list(db.marketplace_channels.values()), limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/marketplace-channels/<channel_id>")
def get_channel(channel_id):
    require_roles("PlatformAdmin", "StoreManager", "GeneralManager")
    ch = get_channel_or_404(channel_id)
    return success_object(ch)
