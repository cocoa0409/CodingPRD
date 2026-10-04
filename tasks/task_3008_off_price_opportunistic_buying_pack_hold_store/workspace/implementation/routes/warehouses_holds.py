"""Warehouses and packaway holds."""
from flask import Blueprint, request

import errors as err
from errors import ApiError
from db import db, now, today_date
from middleware import require
from response import success, success_list
from services.calc import (
    TRIGGER_REASONS, CASCADE_RECOVERY_RATE_PCT,
    get_body, validate_body, require_range, new_common, touch, get_or_404,
    find_by, check_unique, paginate, serialize, iso_z,
    age_bucket_for, holding_cost_accrual,
)

bp = Blueprint("warehouses_holds", __name__)

WAREHOUSE_ROLES = ("InventoryPlanner", "PlanningLead", "WarehouseClerk")


# ------------------------------------------------------------------- warehouses
@bp.post("/warehouses")
def create_warehouse():
    require(("InventoryPlanner",))
    vals = validate_body(get_body(required=True), {
        "warehouse_code": ("str", True),
        "pallet_capacity": ("int", True),
        "zone_code": ("str", True),
        "monthly_holding_rate_per_pallet_cents": ("int", True),
    })
    require_range(vals["pallet_capacity"], lo=0, lo_exclusive=True, field="pallet_capacity")
    require_range(vals["monthly_holding_rate_per_pallet_cents"], lo=0,
                  field="monthly_holding_rate_per_pallet_cents")
    check_unique("warehouses", "warehouse_code", vals["warehouse_code"],
                 "warehouse_code already exists")
    warehouse = new_common()
    warehouse.update(vals)
    db["warehouses"][warehouse["id"]] = warehouse
    return success(serialize("warehouse", warehouse), status=201)


@bp.get("/warehouses")
def list_warehouses():
    require(WAREHOUSE_ROLES)
    page, limit, offset, total = paginate(list(db["warehouses"].values()))
    return success_list([serialize("warehouse", w) for w in page], limit, offset, total)


@bp.get("/warehouses/<wid>")
def get_warehouse(wid):
    require(WAREHOUSE_ROLES)
    return success(serialize("warehouse", get_or_404("warehouses", wid)))


@bp.get("/warehouses/<wid>/packaway-holds")
def warehouse_holds(wid):
    require(WAREHOUSE_ROLES)
    get_or_404("warehouses", wid)
    holds = [h for h in db["holds"].values() if h["warehouse_id"] == wid]
    page, limit, offset, total = paginate(holds, {"status": request.args.get("status")})
    return success_list([serialize("hold", h) for h in page], limit, offset, total)


@bp.get("/warehouses/<wid>/receipts")
def warehouse_receipts(wid):
    require(WAREHOUSE_ROLES)
    get_or_404("warehouses", wid)
    page, limit, offset, total = paginate(find_by("receipts", "warehouse_id", wid))
    return success_list([serialize("receipt", r) for r in page], limit, offset, total)


# ------------------------------------------------------------------- packaway holds
@bp.post("/packaway-holds")
def create_hold():
    require(("InventoryPlanner",))
    vals = validate_body(get_body(required=True), {
        "lot_id": ("str", True),
        "warehouse_id": ("str", True),
        "pallet_count": ("int", True),
        "release_window_start": ("datetime", True),
        "release_window_end": ("datetime", True),
    })
    lot = get_or_404("lots", vals["lot_id"], "lot not found")
    warehouse = get_or_404("warehouses", vals["warehouse_id"], "warehouse not found")
    require_range(vals["pallet_count"], lo=0, lo_exclusive=True, field="pallet_count")
    if not vals["release_window_end"] > vals["release_window_start"]:
        raise err.invalid_request("release_window_end must be strictly after release_window_start")
    if lot["status"] != "ACCEPTED":
        raise err.invalid_state("only an ACCEPTED lot can be placed into a packaway hold")
    if lot["disposition"] != "PACKAWAY":
        raise ApiError("ERR_TARGET_SEASON_NOT_DRAFT", "only PACKAWAY lots may be held")
    target = db["seasons"].get(lot["target_season_id"])
    if target is None or target["status"] != "DRAFT" or lot["target_season_id"] == lot["season_id"]:
        raise ApiError("ERR_TARGET_SEASON_NOT_DRAFT",
                       "target season must exist, be DRAFT, and differ from the buying season")
    if find_by("holds", "lot_id", lot["id"]):
        raise ApiError("ERR_DUPLICATE_CODE", "a packaway hold already exists for this lot")
    # The capacity check runs before the warehouse is updated with the hold.
    used = sum(h["pallet_count"] for h in db["holds"].values()
               if h["warehouse_id"] == warehouse["id"]
               and h["status"] in ("STORED", "AGING_REVIEW"))
    if used + vals["pallet_count"] > warehouse["pallet_capacity"]:
        raise ApiError("ERR_WAREHOUSE_OVER_CAPACITY", "warehouse pallet capacity exceeded")
    hold = new_common()
    hold.update({
        "lot_id": lot["id"],
        "warehouse_id": warehouse["id"],
        "season_id": lot["season_id"],
        "target_season_id": lot["target_season_id"],
        "pallet_count": vals["pallet_count"],
        "entry_date": now(),
        "release_window_start": vals["release_window_start"],
        "release_window_end": vals["release_window_end"],
        "release_date": None,
        "accrued_holding_cost_cents": 0,
        "review_count": 0,
        "age_bucket": "FRESH",
        "status": "STORED",
    })
    db["holds"][hold["id"]] = hold
    return success(serialize("hold", hold), status=201)


@bp.get("/packaway-holds")
def list_holds():
    require(WAREHOUSE_ROLES)
    filters = {k: request.args.get(k) for k in
               ("lot_id", "warehouse_id", "season_id", "target_season_id", "status", "age_bucket")}
    page, limit, offset, total = paginate(list(db["holds"].values()), filters)
    return success_list([serialize("hold", h) for h in page], limit, offset, total)


@bp.get("/packaway-holds/<hid>")
def get_hold(hid):
    require(WAREHOUSE_ROLES)
    return success(serialize("hold", get_or_404("holds", hid)))


def _create_cascade_liquidation(hold):
    """DRAFT LiquidationOrder (PACKAWAY_STALE, 0.25) at the nearest clearance store."""
    warehouse = db["warehouses"].get(hold["warehouse_id"])
    stores = [s for s in db["stores"].values()
              if s["clearance_outlet"] and warehouse and s["zone_code"] == warehouse["zone_code"]]
    stores.sort(key=lambda s: s["created_at"])
    store_id = stores[0]["id"] if stores else None
    skus = _affected_skus(store_id, hold["lot_id"])
    order = new_common()
    order.update({
        "store_id": store_id,
        "lot_id": hold["lot_id"],
        "reason": "PACKAWAY_STALE",
        "recovery_rate_pct": CASCADE_RECOVERY_RATE_PCT,
        "expected_units": sum(s["units_on_hand"] for s in skus),
        "actual_units": None,
        "recovery_value_cents": None,
        "status": "DRAFT",
    })
    db["liquidation_orders"][order["id"]] = order
    return order


def _affected_skus(store_id, lot_id):
    line_ids = {l["id"] for l in db["lot_lines"].values() if l["lot_id"] == lot_id}
    return [s for s in db["store_skus"].values()
            if s["store_id"] == store_id and s["lot_line_id"] in line_ids
            and s["status"] in ("ON_FLOOR", "MARKED_DOWN", "CLEARANCE")]


@bp.post("/packaway-holds/<hid>/aging-review")
def aging_review(hid):
    require(("InventoryPlanner",))
    hold = get_or_404("holds", hid)
    vals = validate_body(get_body(required=True),
                         {"trigger_reason": ("enum", True, TRIGGER_REASONS)})
    reason = vals["trigger_reason"]
    today = today_date()
    if reason == "AGING_THRESHOLD":
        if hold["status"] != "STORED":
            raise err.invalid_state("only a STORED hold can enter AGING_REVIEW")
        hold["age_bucket"] = age_bucket_for(hold)
        if hold["age_bucket"] == "FRESH":
            raise ApiError("ERR_AGING_REVIEW_PREMATURE", "hold has not reached the aging threshold")
        hold["status"] = "AGING_REVIEW"
    elif reason == "DECISION_KEEP":
        if hold["status"] != "AGING_REVIEW":
            raise err.invalid_state("only a hold in AGING_REVIEW can be kept")
        hold["status"] = "STORED"
    elif reason == "DECISION_RELEASE":
        if hold["status"] != "AGING_REVIEW":
            raise err.invalid_state("only a hold in AGING_REVIEW can be released by review")
        if not (hold["release_window_start"].date() <= today <= hold["release_window_end"].date()):
            raise ApiError("ERR_HOLD_WINDOW_CLOSED", "today is outside the release window")
        target = db["seasons"].get(hold["target_season_id"])
        if target is None or today < target["start_date"].date() or target["status"] != "OPEN":
            raise ApiError("ERR_TARGET_SEASON_NOT_OPEN", "the target season is not OPEN")
        hold["status"] = "RELEASED"
        hold["release_date"] = now()
    else:  # DECISION_LIQUIDATE
        if hold["status"] != "AGING_REVIEW":
            raise err.invalid_state("only a hold in AGING_REVIEW can be liquidated by review")
        hold["status"] = "LIQUIDATED"
    hold["accrued_holding_cost_cents"] = holding_cost_accrual(hold)
    hold["review_count"] += 1
    hold["age_bucket"] = age_bucket_for(hold)
    touch(hold)
    if hold["status"] == "LIQUIDATED":
        _create_cascade_liquidation(hold)
    return success(serialize("hold", hold))


@bp.post("/packaway-holds/<hid>/liquidate")
def liquidate_hold(hid):
    require(("InventoryPlanner",))
    hold = get_or_404("holds", hid)
    get_body()
    if hold["status"] != "STORED":
        raise err.invalid_state("only a STORED hold can be liquidated directly")
    hold["age_bucket"] = age_bucket_for(hold)
    if hold["age_bucket"] != "STALE":
        raise ApiError("ERR_AGING_REVIEW_PREMATURE", "direct liquidation requires a STALE hold")
    hold["accrued_holding_cost_cents"] = holding_cost_accrual(hold)
    hold["status"] = "LIQUIDATED"
    touch(hold)
    _create_cascade_liquidation(hold)
    return success(serialize("hold", hold))


@bp.post("/packaway-holds/<hid>/release")
def release_hold(hid):
    require(("InventoryPlanner",))
    hold = get_or_404("holds", hid)
    vals = validate_body(get_body(required=True),
                         {"expected_hold_version": ("int", True)})
    if hold["status"] != "STORED":
        raise err.invalid_state("only a STORED hold can be released")
    today = today_date()
    # The release-window rule is evaluated ahead of the OCC gate: a release
    # attempted outside its window is out of window regardless of the version
    # carried by the request.
    if not (hold["release_window_start"].date() <= today <= hold["release_window_end"].date()):
        raise ApiError("ERR_HOLD_WINDOW_CLOSED", "today is outside the release window")
    if vals["expected_hold_version"] != hold["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_hold_version does not match the hold version")
    target = db["seasons"].get(hold["target_season_id"])
    if target is None or today < target["start_date"].date() or target["status"] != "OPEN":
        raise ApiError("ERR_TARGET_SEASON_NOT_OPEN",
                       "the target season has not reached its start_date or is not OPEN")
    hold["accrued_holding_cost_cents"] = holding_cost_accrual(hold)
    hold["release_date"] = now()
    hold["status"] = "RELEASED"
    touch(hold)
    return success(serialize("hold", hold))
