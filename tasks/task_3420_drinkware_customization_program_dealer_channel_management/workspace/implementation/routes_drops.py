"""Colorway drops: announce, read/list (lazy LIVE/CLOSED), open and lock the
dealer allocation window (lock runs the largest-remainder distribution)."""
from flask import Blueprint, request

from auth import context, require_roles
from calc import refresh_drop, run_launch_allocation_distribution
from envelope import (
    get_body, new_entity, req_dt, req_enum, req_int, req_str, sort_created,
    success, success_list, touch,
)
from errors import fail
from serialize import ser_drop
from store import DB, get_clock

bp = Blueprint("drops", __name__)

DROP_TYPES = ("STANDARD", "LIMITED_EDITION")
ALL_ROLES_READ = [
    "PlatformAdmin", "ChannelManager", "FieldInspector", "Dealer", "Buyer",
    "PrepressTech", "ProductionLead", "WarrantyAgent", "CustomerCare",
]


def load_drop(drop_id):
    d = DB.drops.get(drop_id)
    if d is None:
        fail("ERR_DROP_NOT_FOUND", "no colorway drop with id %s" % drop_id)
    refresh_drop(d)
    return d


@bp.post("/drinkware/colorway-drops")
def create_drop():
    _, role = context()
    require_roles(role, ["PlatformAdmin"])
    body = get_body()
    product_line_id = req_str(body, "product_line_id")
    color_name = req_str(body, "color_name")
    pantone_code = req_str(body, "pantone_code")
    drop_type = req_enum(body, "drop_type", DROP_TYPES)
    total_units = req_int(body, "total_units", minimum=1)
    dtc_reserved = req_int(body, "dtc_reserved_units", minimum=0)
    dealer_price = req_int(body, "dealer_unit_price_cents", minimum=1)
    opens = req_dt(body, "allocation_opens_at")
    closes = req_dt(body, "allocation_closes_at")
    go_live = req_dt(body, "go_live_at")
    sales_end = req_dt(body, "sales_end_at")
    line = DB.product_lines.get(product_line_id)
    if line is None:
        fail("ERR_PRODUCT_LINE_NOT_FOUND", "no product line with id %s" % product_line_id)
    if line["status"] != "ACTIVE":
        fail("ERR_PRODUCT_LINE_DISCONTINUED",
             "new colorway drops for a DISCONTINUED line are rejected")
    if not (opens < closes < go_live < sales_end):
        fail("ERR_INVALID_WINDOW_ORDER",
             "drop windows must be strictly ordered opens < closes < go_live < sales_end")
    if dtc_reserved > total_units:
        fail("ERR_DTC_RESERVE_EXCEEDS_TOTAL",
             "dtc_reserved_units may not exceed total_units")
    drop = new_entity({
        "product_line_id": product_line_id,
        "color_name": color_name,
        "pantone_code": pantone_code,
        "drop_type": drop_type,
        "total_units": total_units,
        "dtc_reserved_units": dtc_reserved,
        "dealer_unit_price_cents": dealer_price,
        "allocation_opens_at": opens,
        "allocation_closes_at": closes,
        "go_live_at": go_live,
        "sales_end_at": sales_end,
        "status": "ANNOUNCED",
    })
    DB.drops[drop["id"]] = drop
    return success(ser_drop(drop), 201)


@bp.get("/drinkware/colorway-drops/<drop_id>")
def get_drop(drop_id):
    _, role = context()
    require_roles(role, ALL_ROLES_READ)
    return success(ser_drop(load_drop(drop_id)))


@bp.get("/drinkware/colorway-drops")
def list_drops():
    _, role = context()
    require_roles(role, ALL_ROLES_READ)
    product_line_id = request.args.get("product_line_id")
    status = request.args.get("status")
    items = sort_created(list(DB.drops.values()))
    for d in items:
        refresh_drop(d)
    if product_line_id is not None:
        items = [d for d in items if d["product_line_id"] == product_line_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return success_list([ser_drop(d) for d in items])


@bp.post("/drinkware/colorway-drops/<drop_id>/open-allocation")
def open_allocation(drop_id):
    _, role = context()
    require_roles(role, ["PlatformAdmin"])
    drop = load_drop(drop_id)
    get_body()
    if drop["status"] != "ANNOUNCED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an ANNOUNCED drop can open its allocation window")
    clock = get_clock()
    if not (drop["allocation_opens_at"] <= clock < drop["allocation_closes_at"]):
        fail("ERR_ALLOCATION_WINDOW_NOT_OPEN",
             "the clock is outside [allocation_opens_at, allocation_closes_at)")
    drop["status"] = "ALLOCATION_OPEN"
    touch(drop)
    return success(ser_drop(drop))


@bp.post("/drinkware/colorway-drops/<drop_id>/lock-allocation")
def lock_allocation(drop_id):
    _, role = context()
    require_roles(role, ["PlatformAdmin"])
    drop = load_drop(drop_id)
    body = get_body()
    expected_version = req_int(body, "expected_drop_version")
    if drop["status"] != "ALLOCATION_OPEN":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an ALLOCATION_OPEN drop can be locked")
    if expected_version != drop["version"]:
        fail("ERR_STALE_DROP_VERSION",
             "expected_drop_version does not match the drop's current version")
    if get_clock() < drop["allocation_closes_at"]:
        fail("ERR_ALLOCATION_WINDOW_OPEN",
             "lock-allocation is permitted only at or after allocation_closes_at")
    run_launch_allocation_distribution(drop)
    drop["status"] = "ALLOCATION_LOCKED"
    touch(drop)
    return success(ser_drop(drop))
