"""Retailer onboarding, parity policy and catalog items (PRD 3.1)."""
from flask import Blueprint

import calc
import lookup
import serializers
from auth import require_owner, require_roles
from db_helpers import touch_if
from errors import fail
from response import created, ok
from store import base_row, db, touch
from validation import (
    body_json,
    opt_bool,
    opt_enum,
    opt_int,
    opt_num,
    query_bool,
    query_str,
    req_enum,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("catalog", __name__)

RETAILER_STATUSES = ("ACTIVE", "PAUSED")
PRICING_UNITS = ("EACH", "PER_LB")
AVAILABILITIES = ("IN_STOCK", "OUT_OF_STOCK")


def derive_catalog_price(item, retailer):
    return calc.catalog_price_cents(item["in_store_price_cents"], retailer["catalog_markup_pct"])


@bp.post("/retailers")
def create_retailer():
    require_roles("DispatchAdmin")
    body = body_json()
    legal_name = req_str(body, "legal_name")
    store_code = req_str(body, "store_code", min_len=3, max_len=16)
    markup = opt_num(body, "catalog_markup_pct", default=None, minimum=0.00, maximum=0.60)
    if markup is None:
        markup = calc.dec("0.15")
    markup = calc.rhu(markup, 2)
    disclosure = opt_bool(body, "parity_disclosure_required", default=True)
    ebt_enabled = opt_bool(body, "ebt_snap_enabled", default=True)
    cap = opt_int(body, "concurrent_shopper_cap", default=2, minimum=1, maximum=10)
    status = opt_enum(body, "status", RETAILER_STATUSES, default="ACTIVE")
    for existing in db.retailers.values():
        if existing["store_code"] == store_code:
            fail("ERR_INVALID_REQUEST", "store_code must be unique across retailers.")
    row = base_row()
    row.update(
        {
            "legal_name": legal_name,
            "store_code": store_code,
            "catalog_markup_pct": markup,
            "parity_disclosure_required": disclosure,
            "ebt_snap_enabled": ebt_enabled,
            "concurrent_shopper_cap": cap,
            "status": status,
        }
    )
    db.retailers[row["id"]] = row
    return created(serializers.retailer(row))


@bp.get("/retailers/<rid>")
def get_retailer(rid):
    require_roles("DispatchAdmin", "RetailerManager", "CustomerSupport")
    row = lookup.retailer(rid)
    return ok(serializers.retailer(row))


@bp.patch("/retailers/<rid>/parity-policy")
def patch_parity_policy(rid):
    require_roles("RetailerManager")
    row = lookup.retailer(rid)
    require_owner(row["id"])
    body = body_json()
    markup = opt_num(body, "catalog_markup_pct", default=None, minimum=0.00, maximum=0.60)
    disclosure = opt_bool(body, "parity_disclosure_required", default=None)
    cap = opt_int(body, "concurrent_shopper_cap", default=None, minimum=1, maximum=10)
    if markup is not None:
        row["catalog_markup_pct"] = calc.rhu(markup, 2)
    if disclosure is not None:
        row["parity_disclosure_required"] = disclosure
    if cap is not None:
        row["concurrent_shopper_cap"] = cap
    touch(row)
    # Wide blast radius: re-derive every catalog item's in-app price, but never
    # rewrite the snapshots already frozen onto existing order lines.
    for item in db.catalog_items.values():
        if item["retailer_id"] != row["id"]:
            continue
        price = derive_catalog_price(item, row)
        changed = price != item["catalog_price_cents"]
        item["catalog_price_cents"] = price
        touch_if(item, changed)
    return ok(serializers.retailer(row))


def _weight_rules(pricing_unit, estimated_weight_lb, unit_weight_lb):
    if pricing_unit == "PER_LB":
        if estimated_weight_lb is None or estimated_weight_lb <= 0:
            fail("ERR_INVALID_REQUEST", "estimated_weight_lb must be > 0 for a PER_LB item.")
    else:
        if estimated_weight_lb is not None and estimated_weight_lb != 0:
            fail("ERR_INVALID_REQUEST", "estimated_weight_lb must be 0 for an EACH item.")
    if unit_weight_lb is not None and unit_weight_lb < 0:
        fail("ERR_INVALID_REQUEST", "unit_weight_lb may not be negative.")


@bp.post("/catalog-items")
def create_catalog_item():
    require_roles("RetailerManager")
    body = body_json()
    retailer_id = req_str(body, "retailer_id")
    sku = req_str(body, "sku")
    name = req_str(body, "name")
    pricing_unit = req_enum(body, "pricing_unit", PRICING_UNITS)
    in_store = req_int(body, "in_store_price_cents", minimum=1)
    is_ebt = opt_bool(body, "is_ebt_eligible", default=False)
    estimated_weight = opt_num(body, "estimated_weight_lb", default=None)
    unit_weight = opt_num(body, "unit_weight_lb", default=None, minimum=0)
    availability = opt_enum(body, "availability", AVAILABILITIES, default="IN_STOCK")
    _weight_rules(pricing_unit, estimated_weight, unit_weight)
    retailer = lookup.retailer(retailer_id)
    require_owner(retailer["id"])
    for existing in db.catalog_items.values():
        if existing["retailer_id"] == retailer["id"] and existing["sku"] == sku:
            fail("ERR_INVALID_REQUEST", "sku must be unique within the retailer.")
    row = base_row()
    row.update(
        {
            "retailer_id": retailer["id"],
            "sku": sku,
            "name": name,
            "pricing_unit": pricing_unit,
            "in_store_price_cents": in_store,
            "is_ebt_eligible": is_ebt,
            "is_weighted": pricing_unit == "PER_LB",
            "estimated_weight_lb": calc.one_dp(estimated_weight if estimated_weight is not None else 0),
            "unit_weight_lb": calc.one_dp(unit_weight if unit_weight is not None else 0),
            "availability": availability,
        }
    )
    row["catalog_price_cents"] = derive_catalog_price(row, retailer)
    db.catalog_items[row["id"]] = row
    return created(serializers.catalog_item(row))


@bp.get("/catalog-items/<iid>")
def get_catalog_item(iid):
    require_roles("RetailerManager", "DispatchAdmin", "Customer", "Shopper", "CustomerSupport")
    row = lookup.catalog_item(iid)
    return ok(serializers.catalog_item(row))


@bp.get("/catalog-items")
def list_catalog_items():
    require_roles("RetailerManager", "DispatchAdmin", "Customer", "Shopper", "CustomerSupport")
    retailer_id = query_str("retailer_id")
    availability = query_str("availability")
    is_ebt = query_bool("is_ebt_eligible")

    def keep(row):
        if retailer_id is not None and row["retailer_id"] != retailer_id:
            return False
        if availability is not None and row["availability"] != availability:
            return False
        if is_ebt is not None and bool(row["is_ebt_eligible"]) != is_ebt:
            return False
        return True

    return lookup.paged(db.catalog_items, serializers.catalog_item, keep)


@bp.patch("/catalog-items/<iid>")
def patch_catalog_item(iid):
    require_roles("RetailerManager")
    row = lookup.catalog_item(iid)
    require_owner(row["retailer_id"])
    body = body_json()
    in_store = opt_int(body, "in_store_price_cents", default=None, minimum=1)
    availability = opt_enum(body, "availability", AVAILABILITIES, default=None)
    is_ebt = opt_bool(body, "is_ebt_eligible", default=None)
    estimated_weight = opt_num(body, "estimated_weight_lb", default=None)
    unit_weight = opt_num(body, "unit_weight_lb", default=None, minimum=0)
    if estimated_weight is not None or unit_weight is not None:
        _weight_rules(
            row["pricing_unit"],
            estimated_weight if estimated_weight is not None else row["estimated_weight_lb"],
            unit_weight,
        )
    if in_store is not None:
        row["in_store_price_cents"] = in_store
    if availability is not None:
        row["availability"] = availability
    if is_ebt is not None:
        row["is_ebt_eligible"] = is_ebt
    if estimated_weight is not None:
        row["estimated_weight_lb"] = calc.one_dp(estimated_weight)
    if unit_weight is not None:
        row["unit_weight_lb"] = calc.one_dp(unit_weight)
    retailer = db.retailers.get(row["retailer_id"])
    if retailer is not None:
        row["catalog_price_cents"] = derive_catalog_price(row, retailer)
    row["is_weighted"] = row["pricing_unit"] == "PER_LB"
    touch(row)
    return ok(serializers.catalog_item(row))
