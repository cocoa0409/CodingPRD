"""Items: create, list, get, sell-down (OCC-guarded)."""

from flask import Blueprint, request

import storage
from calculations import new_record, bump
from envelope import success, paginate, sorted_by_created
from errors import fail
from rbac import guard, synchronized, authenticate, require_role, ALL_ROLES
from serializers import item_out
from validation import body_json, f_str, f_int, opt_bool

bp = Blueprint("items", __name__, url_prefix="/portfolio")


def guard_and_role():
    user_id, role = authenticate()
    require_role(role, ["PortfolioManager", "BrandManager"])
    return user_id, role


@bp.post("/items")
@synchronized
def create_item():
    user_id, role = guard_and_role()
    body = body_json(required=True)
    brand_id = f_str(body, "brand_id")
    primary_plant_id = f_str(body, "primary_plant_id")
    sku_code = f_str(body, "sku_code")
    annual_units = f_int(body, "annual_units", 0)
    unit_rev = f_int(body, "unit_net_revenue_cents", 0)
    unit_cost = f_int(body, "unit_cost_cents", 0)
    units_on_hand = f_int(body, "units_on_hand", 0)
    salvageable = opt_bool(body, "salvageable", False)
    # step 6: body FKs resolve
    brand = storage.brands.get(brand_id)
    if brand is None:
        fail("ERR_NOT_FOUND", f"brand {brand_id} not found")
    plant = storage.plants.get(primary_plant_id)
    if plant is None:
        fail("ERR_NOT_FOUND", f"plant {primary_plant_id} not found")
    # step 7: state guards on both parents
    if brand["brand_status"] not in ("ACTIVE", "UNDER_REVIEW"):
        fail("ERR_INVALID_STATE",
             "item create requires brand ACTIVE or UNDER_REVIEW")
    if plant["plant_status"] != "OPERATING":
        fail("ERR_INVALID_STATE", "item create requires primary plant OPERATING")
    # step 9: entity-backed ownership (BrandManager must own the brand)
    if role == "BrandManager" and user_id != brand_id:
        fail("ERR_OWNERSHIP_MISMATCH",
             "BrandManager may create items only for the owned brand")
    # step 11: sku_code unique across all items
    if any(i["sku_code"] == sku_code for i in storage.items.values()):
        fail("ERR_DUPLICATE", f"sku_code '{sku_code}' already exists")
    rec = new_record()
    rec.update({
        "brand_id": brand_id,
        "primary_plant_id": primary_plant_id,
        "sku_code": sku_code,
        "annual_units": annual_units,
        "unit_net_revenue_cents": unit_rev,
        "unit_cost_cents": unit_cost,
        "units_on_hand": units_on_hand,
        "salvageable": salvageable,
        "item_status": "LISTED",
        "sell_through_deadline": None,
        "units_sold_cumulative": 0,
        "units_written_off_cumulative": 0,
        "obsolescence_charge_cents": 0,
    })
    storage.items[rec["id"]] = rec
    return success(item_out(rec), status=201)


@bp.get("/items")
@synchronized
def list_items():
    guard(ALL_ROLES)
    records = list(storage.items.values())
    for param in ("brand_id", "primary_plant_id", "item_status"):
        value = request.args.get(param)
        if value is not None:
            records = [i for i in records if i[param] == value]
    page, meta = paginate(sorted_by_created(records))
    return success([item_out(i) for i in page], response_type="array",
                   pagination=meta)


@bp.get("/items/<iid>")
@synchronized
def get_item(iid):
    guard(ALL_ROLES)
    item = storage.items.get(iid)
    if item is None:
        fail("ERR_NOT_FOUND", f"item {iid} not found")
    return success(item_out(item))


@bp.post("/items/<iid>/sell-down")
@synchronized
def sell_down(iid):
    guard(["SupplyChainPlanner"])
    body = body_json(required=True)
    # step 4: both fields required, integer-typed (range checked at step 21)
    units_sold = f_int(body, "units_sold")
    expected_item_version = f_int(body, "expected_item_version")
    # step 5: path id resolves
    item = storage.items.get(iid)
    if item is None:
        fail("ERR_NOT_FOUND", f"item {iid} not found")
    # step 7: allowed only while LISTED or SELL_THROUGH
    if item["item_status"] not in ("LISTED", "SELL_THROUGH"):
        fail("ERR_INVALID_STATE",
             "sell-down requires item LISTED or SELL_THROUGH")
    # step 21: quantity bounds
    if units_sold < 1 or units_sold > item["units_on_hand"]:
        fail("ERR_INSUFFICIENT_UNITS",
             "units_sold must be >= 1 and <= units_on_hand")
    # step 23: optimistic concurrency, evaluated last
    if expected_item_version != item["version"]:
        fail("ERR_STALE_VERSION",
             "expected_item_version does not match the item's current version")
    item["units_on_hand"] -= units_sold
    item["units_sold_cumulative"] += units_sold
    bump(item)
    return success(item_out(item))
