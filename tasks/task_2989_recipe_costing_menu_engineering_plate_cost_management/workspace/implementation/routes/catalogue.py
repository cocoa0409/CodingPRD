"""Logical clock, stores and the ingredient catalogue (PRD 2.4, 3.1)."""
from flask import Blueprint

import serial
from core import REGIONS, UOMS, db, order_key, stamp_new, touch
from envelope import created, listing, ok
from errors import fail
from graph import net_yield
from guards import (
    ANY_ROLE, authenticate, find_ingredient, find_unit, get_body, pagination,
    paginate, query_enum, req_enum, req_instant, req_int, req_str,
)

bp = Blueprint("catalogue", __name__)

UNIT_CODE = r"^[A-Z0-9-]{3,12}$"
SKU = r"^[A-Z0-9-]{3,20}$"


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/culinary/_clock/set_current_utc")
def set_clock():
    authenticate(("PlatformAdmin",))
    body = get_body()
    target = req_instant(body, "to_iso8601")
    if target < db.now():
        fail("ERR_CLOCK_NOT_MONOTONIC",
             "The logical clock never moves backwards.")
    db.clock = target
    return ok({})


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------
@bp.post("/culinary/units")
def create_unit():
    authenticate(("PlatformAdmin",))
    body = get_body()
    code = req_str(body, "code", pattern=UNIT_CODE, min_len=None)
    name = req_str(body, "name", min_len=1, max_len=80)
    region_code = req_enum(body, "region_code", REGIONS)
    for existing in db.units.values():
        if existing["code"] == code:
            fail("ERR_DUPLICATE_CODE", "Store code %s is already registered." % code)
    row = stamp_new({"code": code, "name": name, "region_code": region_code})
    db.units[row["id"]] = row
    return created(serial.unit(row))


@bp.get("/culinary/units/<unit_id>")
def get_unit(unit_id):
    authenticate(ANY_ROLE)
    return ok(serial.unit(find_unit(unit_id)))


# ---------------------------------------------------------------------------
# Ingredients
# ---------------------------------------------------------------------------
@bp.post("/culinary/ingredients")
def create_ingredient():
    authenticate(("RecipeDeveloper", "PlatformAdmin"))
    body = get_body()
    sku = req_str(body, "sku", pattern=SKU, min_len=None)
    name = req_str(body, "name", min_len=1, max_len=80)
    base_uom = req_enum(body, "base_uom", UOMS)
    pack_base_units = req_int(body, "pack_base_units", minimum=1)
    trim_yield_bps = req_int(body, "trim_yield_bps", minimum=1, maximum=10000)
    cook_shrink_bps = req_int(body, "cook_shrink_bps", minimum=0, maximum=9999)
    allergen_mask = req_int(body, "allergen_mask", minimum=0, maximum=255)
    kcal = req_int(body, "kcal_per_base_unit_micros", minimum=0)
    sodium = req_int(body, "sodium_mcg_per_base_unit", minimum=0)
    for existing in db.ingredients.values():
        if existing["sku"] == sku:
            fail("ERR_DUPLICATE_SKU", "SKU %s is already registered." % sku)
    row = stamp_new({
        "sku": sku,
        "name": name,
        "base_uom": base_uom,
        "pack_base_units": pack_base_units,
        "trim_yield_bps": trim_yield_bps,
        "cook_shrink_bps": cook_shrink_bps,
        "net_yield_bps": net_yield(trim_yield_bps, cook_shrink_bps),
        "allergen_mask": allergen_mask,
        "kcal_per_base_unit_micros": kcal,
        "sodium_mcg_per_base_unit": sodium,
        "status": "ACTIVE",
        "retired_at": None,
    })
    db.ingredients[row["id"]] = row
    return created(serial.ingredient(row))


@bp.get("/culinary/ingredients/<ingredient_id>")
def get_ingredient(ingredient_id):
    authenticate(ANY_ROLE)
    return ok(serial.ingredient(find_ingredient(ingredient_id)))


@bp.post("/culinary/ingredients/<ingredient_id>/retire")
def retire_ingredient(ingredient_id):
    authenticate(("CulinaryDirector",))
    ingredient = find_ingredient(ingredient_id)
    if ingredient["status"] != "ACTIVE":
        fail("ERR_INGREDIENT_RETIRED", "The ingredient is already RETIRED.")
    ingredient["status"] = "RETIRED"
    ingredient["retired_at"] = db.now()
    touch(ingredient)
    return ok(serial.ingredient(ingredient))


@bp.get("/culinary/ingredients/<ingredient_id>/prices")
def list_ingredient_prices(ingredient_id):
    authenticate(ANY_ROLE)
    limit, offset = pagination()
    status = query_enum("status", ("PENDING", "PUBLISHED", "SUPERSEDED"))
    region_code = query_enum("region_code", REGIONS)
    find_ingredient(ingredient_id)
    rows = [p for p in db.ingredient_prices.values()
            if p["ingredient_id"] == ingredient_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    if region_code is not None:
        rows = [p for p in rows if p["region_code"] == region_code]
    rows.sort(key=order_key)
    rows.sort(key=lambda p: p["effective_from"])
    page, limit, offset, total = paginate(rows, limit, offset, serial.ingredient_price)
    return listing(page, limit, offset, total)


@bp.get("/culinary/ingredients/<ingredient_id>/count-lines")
def list_ingredient_count_lines(ingredient_id):
    authenticate(ANY_ROLE)
    limit, offset = pagination()
    sync_state = query_enum("sync_state", ("CURRENT", "OUT_OF_DATE"))
    find_ingredient(ingredient_id)
    rows = [c for c in db.count_lines.values()
            if c["ingredient_id"] == ingredient_id]
    if sync_state is not None:
        rows = [c for c in rows if c["sync_state"] == sync_state]
    rows.sort(key=order_key)
    page, limit, offset, total = paginate(rows, limit, offset, serial.count_line)
    return listing(page, limit, offset, total)
