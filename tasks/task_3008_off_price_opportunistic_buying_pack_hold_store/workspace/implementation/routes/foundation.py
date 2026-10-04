"""Logical clock, merchandise seasons, vendors, price zones."""
from flask import Blueprint

import errors as err
from errors import ApiError
from db import db, set_clock, now
from middleware import require, actor, is_senior_buyer
from response import success, success_list
from services.calc import (
    SEASON_STATUSES, DISCRETION_LEVELS, VENDOR_TIERS, ZONE_CODES, LIVE_SKU_STATUSES,
    get_body, validate_body, require_range, new_common, touch, get_or_404,
    find_by, check_unique, paginate, serialize, parse_date, iso_z,
    recompute_weeks_on_floor, run_sweeps, season_view,
    otb_forward_available, otb_packaway_available, refresh_availability,
)

bp = Blueprint("foundation", __name__)

ALL_ROLES = ("PlanningLead", "Buyer", "AllocationManager", "InventoryPlanner",
             "PricingAnalyst", "WarehouseClerk", "StoreOpsLead", "ShrinkAuditor")


# ------------------------------------------------------------------- clock
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require(("PlanningLead",))
    body = get_body(required=True)
    vals = validate_body(body, {"to_iso8601": ("datetime", True)})
    set_clock(vals["to_iso8601"])
    run_sweeps()
    return success({"current_utc": iso_z(now())})


# -------------------------------------------------------------- seasons
@bp.post("/merchandise-seasons")
def create_season():
    require(("PlanningLead",))
    vals = validate_body(get_body(required=True), {
        "season_code": ("str", True),
        "start_date": ("datetime", True),
        "end_date": ("datetime", True),
        "department_otb_budget_cents": ("int", True),
        "packaway_reserve_ratio": ("float", True),
    })
    require_range(vals["department_otb_budget_cents"], lo=0, field="department_otb_budget_cents")
    require_range(vals["packaway_reserve_ratio"], lo=0, hi=1, field="packaway_reserve_ratio")
    if not vals["end_date"] > vals["start_date"]:
        raise err.invalid_request("end_date must be strictly after start_date")
    check_unique("seasons", "season_code", vals["season_code"], "season_code already exists")
    season = new_common()
    season.update(vals)
    season.update({
        "status": "DRAFT",
        "committed_forward_cents": 0,
        "committed_packaway_cents": 0,
        "spent_forward_cents": 0,
        "spent_packaway_cents": 0,
        # Read-model cache of the §3.1 availability figures; refreshed on every
        # mutation so that OTC admission and season reads share one source.
        "forward_available_cents": otb_forward_available({
            "department_otb_budget_cents": season["department_otb_budget_cents"],
            "packaway_reserve_ratio": season["packaway_reserve_ratio"],
            "committed_forward_cents": 0,
        }),
        "packaway_available_cents": otb_packaway_available({
            "department_otb_budget_cents": season["department_otb_budget_cents"],
            "packaway_reserve_ratio": season["packaway_reserve_ratio"],
            "committed_packaway_cents": 0,
        }),
    })
    db["seasons"][season["id"]] = season
    return success(season_view(season), status=201)


@bp.get("/merchandise-seasons")
def list_seasons():
    actor()
    from flask import request
    page, limit, offset, total = paginate(list(db["seasons"].values()),
                                          {"status": request.args.get("status")})
    return success_list([serialize("season", s) for s in page], limit, offset, total)


@bp.get("/merchandise-seasons/<sid>")
def get_season(sid):
    actor()
    season = get_or_404("seasons", sid)
    return success(season_view(season))


@bp.post("/merchandise-seasons/<sid>/open")
def open_season(sid):
    require(("PlanningLead",))
    season = get_or_404("seasons", sid)
    get_body()  # tolerate an empty/None body
    if season["status"] != "DRAFT":
        raise err.invalid_state("only a DRAFT season can be opened")
    if any(s["status"] == "OPEN" for s in db["seasons"].values()):
        raise ApiError("ERR_SEASON_ALREADY_OPEN", "another season is already OPEN")
    season["status"] = "OPEN"
    touch(season)
    return success(season_view(season))


@bp.post("/merchandise-seasons/<sid>/close")
def close_season(sid):
    require(("PlanningLead",))
    season = get_or_404("seasons", sid)
    get_body()
    if season["status"] != "OPEN":
        raise err.invalid_state("only an OPEN season can be closed")
    if any(l["season_id"] == sid and l["status"] in ("OFFERED", "EVALUATED")
           for l in db["lots"].values()):
        raise ApiError("ERR_OPEN_LOTS_REMAIN", "lots of the season are still OFFERED or EVALUATED")
    if any(h["season_id"] == sid and h["status"] in ("STORED", "AGING_REVIEW")
           for h in db["holds"].values()):
        raise ApiError("ERR_PACKAWAY_HOLDS_ACTIVE", "packaway holds of the season are still active")
    if any(p["season_id"] == sid and p["status"] in ("DRAFT", "APPROVED")
           for p in db["plans"].values()):
        raise ApiError("ERR_PLAN_NOT_EXECUTABLE", "allocation plans of the season are still DRAFT or APPROVED")
    recompute_weeks_on_floor(sid)
    season["status"] = "CLOSED"
    touch(season)
    return success(season_view(season))


# season-scoped reverse reachability -------------------------------------
@bp.get("/merchandise-seasons/<sid>/lots")
def season_lots(sid):
    user_id, role = require(("Buyer", "PlanningLead", "AllocationManager"))
    get_or_404("seasons", sid)
    from flask import request
    lots = [l for l in db["lots"].values() if l["season_id"] == sid]
    lots = _discretion_filter(lots, user_id, role)
    page, limit, offset, total = paginate(lots, {"status": request.args.get("status")})
    return success_list([serialize("lot", l) for l in page], limit, offset, total)


@bp.get("/merchandise-seasons/<sid>/packaway-holds")
def season_holds(sid):
    require(("InventoryPlanner", "PlanningLead"))
    get_or_404("seasons", sid)
    from flask import request
    holds = [h for h in db["holds"].values() if h["season_id"] == sid]
    page, limit, offset, total = paginate(
        holds, {"target_season_id": request.args.get("target_season_id")})
    return success_list([serialize("hold", h) for h in page], limit, offset, total)


@bp.get("/merchandise-seasons/<sid>/allocation-plans")
def season_plans(sid):
    require(("AllocationManager", "PlanningLead"))
    get_or_404("seasons", sid)
    from flask import request
    plans = [p for p in db["plans"].values() if p["season_id"] == sid]
    page, limit, offset, total = paginate(plans, {"status": request.args.get("status")})
    return success_list([serialize("plan", p) for p in page], limit, offset, total)


@bp.get("/merchandise-seasons/<sid>/store-skus")
def season_store_skus(sid):
    require(("StoreOpsLead", "PlanningLead", "AllocationManager"))
    get_or_404("seasons", sid)
    from flask import request
    skus = [s for s in db["store_skus"].values() if s["season_id"] == sid]
    page, limit, offset, total = paginate(skus, {"status": request.args.get("status")})
    return success_list([serialize("store_sku", s) for s in page], limit, offset, total)


def _discretion_filter(lots, user_id, role):
    if role == "Buyer" and not is_senior_buyer(user_id, role):
        return [l for l in lots
                if db["vendors"].get(l["vendor_id"], {}).get("discretion_level") == "STANDARD"]
    return lots


# -------------------------------------------------------------- vendors
@bp.post("/vendors")
def create_vendor():
    require(("PlanningLead",))
    vals = validate_body(get_body(required=True), {
        "legal_name": ("str", True),
        "vendor_code": ("str", True),
        "discretion_level": ("enum", True, DISCRETION_LEVELS),
        "ticket_discretion_required": ("bool", True),
        "default_zone_code": ("str", True),
        "vendor_tier": ("enum", True, VENDOR_TIERS),
    })
    check_unique("vendors", "vendor_code", vals["vendor_code"], "vendor_code already exists")
    vendor = new_common()
    vendor.update(vals)
    db["vendors"][vendor["id"]] = vendor
    return success(serialize("vendor", vendor), status=201)


@bp.get("/vendors")
def list_vendors():
    require(("PlanningLead", "Buyer", "AllocationManager", "InventoryPlanner", "PricingAnalyst"))
    from flask import request
    page, limit, offset, total = paginate(
        list(db["vendors"].values()),
        {"discretion_level": request.args.get("discretion_level")})
    return success_list([serialize("vendor", v) for v in page], limit, offset, total)


@bp.get("/vendors/<vid>")
def get_vendor(vid):
    require(("PlanningLead", "Buyer", "AllocationManager", "InventoryPlanner", "PricingAnalyst"))
    return success(serialize("vendor", get_or_404("vendors", vid)))


@bp.get("/vendors/<vid>/lots")
def vendor_lots(vid):
    user_id, role = require(("Buyer", "PlanningLead", "PricingAnalyst"))
    get_or_404("vendors", vid)
    from flask import request
    lots = [l for l in db["lots"].values() if l["vendor_id"] == vid]
    lots = _discretion_filter(lots, user_id, role)
    page, limit, offset, total = paginate(lots, {"status": request.args.get("status")})
    return success_list([serialize("lot", l) for l in page], limit, offset, total)


# -------------------------------------------------------------- price zones
@bp.post("/price-zones")
def create_zone():
    require(("PricingAnalyst",))
    vals = validate_body(get_body(required=True), {
        "zone_code": ("enum", True, ZONE_CODES),
        "compare_at_multiplier": ("float", True),
        "markdown_cadence_weeks": ("int", True),
        "clearance_weeks": ("int", True),
    })
    require_range(vals["compare_at_multiplier"], lo=1, lo_exclusive=True, field="compare_at_multiplier")
    require_range(vals["markdown_cadence_weeks"], lo=1, hi=8, field="markdown_cadence_weeks")
    if not (vals["clearance_weeks"] > vals["markdown_cadence_weeks"] and vals["clearance_weeks"] <= 52):
        raise err.invalid_request("clearance_weeks must be > markdown_cadence_weeks and <= 52")
    check_unique("zones", "zone_code", vals["zone_code"], "zone_code already exists")
    zone = new_common()
    zone.update(vals)
    db["zones"][zone["id"]] = zone
    return success(serialize("zone", zone), status=201)


@bp.get("/price-zones")
def list_zones():
    require(("PlanningLead", "Buyer", "AllocationManager", "InventoryPlanner",
             "PricingAnalyst", "StoreOpsLead"))
    page, limit, offset, total = paginate(list(db["zones"].values()))
    return success_list([serialize("zone", z) for z in page], limit, offset, total)


@bp.get("/price-zones/<zid>")
def get_zone(zid):
    require(("PlanningLead", "Buyer", "AllocationManager", "InventoryPlanner",
             "PricingAnalyst", "StoreOpsLead"))
    zone = db["zones"].get(zid)
    if zone is None:
        zone = next((z for z in db["zones"].values() if z["zone_code"] == zid), None)
    if zone is None:
        raise err.not_found("price zone not found")
    return success(serialize("zone", zone))
