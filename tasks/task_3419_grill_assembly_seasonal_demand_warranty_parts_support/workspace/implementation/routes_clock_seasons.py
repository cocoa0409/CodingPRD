"""Clock control, Season lifecycle + cascades, and season/model lot views."""

from flask import Blueprint, request

import clock
import derive
from auth import authenticate, require_role
from constants import SEASON_NEXT, SEASON_STATUSES
from errors import api_error, not_found, validation
from serialize import lot_out, season_out
from store import db, new_entity, touch
from util import (
    get_body,
    ok,
    ok_list,
    paginate,
    req_int,
    req_str,
    require,
)

bp = Blueprint("clock_seasons", __name__, url_prefix="/grillops")

PLANNER = ("PlannerAdmin",)


# ---------------------------------------------------------------------------
# POST /grillops/_clock/set_current_utc  (PRD §2.4 — set-anywhere semantics)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    require_role(role, PLANNER)
    data = get_body()
    raw = require(data, "to_iso8601")
    try:
        target = clock.parse_iso(raw)
    except (ValueError, TypeError):
        raise validation("to_iso8601 must be an ISO-8601 instant")
    clock.set_now(target)
    return ok({"current_utc": clock.iso_z(target)})


# ---------------------------------------------------------------------------
# Seasons (PRD §3.1)
# ---------------------------------------------------------------------------

def _season_or_404(season_id):
    season = db.seasons.get(season_id)
    if season is None:
        raise not_found("SEASON")
    return season


@bp.post("/seasons")
def create_season():
    _, role = authenticate()
    require_role(role, PLANNER)
    data = get_body()
    # rung 6: body well-formedness (required fields, parseable dates, ordering)
    name = req_str(data, "name")
    year = req_int(data, "year")
    demand = req_int(data, "demand_forecast_units")
    milestones = {}
    for field in ("build_start", "allocation_open", "in_season_start", "clearance_start", "season_end"):
        raw = require(data, field)
        try:
            milestones[field] = clock.parse_iso(raw)
        except (ValueError, TypeError):
            raise validation("%s must be an ISO-8601 datetime" % field)
    ordered = [milestones[f] for f in ("build_start", "allocation_open", "in_season_start", "clearance_start", "season_end")]
    if not all(ordered[i] < ordered[i + 1] for i in range(4)):
        raise validation("season milestones must satisfy build_start < allocation_open < in_season_start < clearance_start < season_end")
    # rung 8: closed-interval [in_season_start, season_end] disjointness;
    # touching endpoints count as a conflict
    for other in db.seasons.values():
        o_start = clock.parse_iso(other["in_season_start"])
        o_end = clock.parse_iso(other["season_end"])
        if milestones["in_season_start"] <= o_end and o_start <= milestones["season_end"]:
            raise api_error("ERR_SEASON_OVERLAP", "in-season interval overlaps an existing season")
    # rung 9: season name uniqueness (no dedicated code -> ERR_VALIDATION)
    for other in db.seasons.values():
        if other["name"] == name:
            raise validation("season name must be unique")
    season = new_entity({
        "name": name,
        "year": year,
        "build_start": clock.iso_z(milestones["build_start"]),
        "allocation_open": clock.iso_z(milestones["allocation_open"]),
        "in_season_start": clock.iso_z(milestones["in_season_start"]),
        "clearance_start": clock.iso_z(milestones["clearance_start"]),
        "season_end": clock.iso_z(milestones["season_end"]),
        "demand_forecast_units": demand,
        "status": "PLANNING",
    })
    db.seasons[season["id"]] = season
    return ok(season_out(season), status=201)


@bp.get("/seasons/<season_id>")
def get_season(season_id):
    _, role = authenticate()
    require_role(role, ("PlannerAdmin", "ChannelRep", "ServiceAgent"))
    return ok(season_out(_season_or_404(season_id)))


def _advance_to_allocation(season):
    for lot in db.lots.values():
        if lot["season_id"] == season["id"] and lot["status"] == "BUILDING":
            lot["status"] = "AVAILABLE"
            touch(lot)
    season["status"] = "ALLOCATION"


def _advance_to_clearance(season):
    # hop 1: expire every still-OFFERED offer; offered units return to the lot
    affected_models = set()
    for a in db.allocations.values():
        if a["season_id"] == season["id"] and a["status"] == "OFFERED":
            a["allocated_units"] = 0  # committed_units is 0 by construction
            a["status"] = "EXPIRED"
            touch(a)
            affected_models.add(a["model_id"])
    # hop 2: lot availability recompute (may flip DEPLETED -> AVAILABLE)
    for model_id in affected_models:
        derive.recompute_lots(season["id"], model_id)
    # hop 3: the clearance waterfall over {ACCEPTED, PARTIALLY_CONSUMED}
    derive.run_waterfall(season)
    season["status"] = "CLEARANCE"


def _advance_to_transitioned(season):
    now = clock.now()
    # hop 1: every model with >= 1 lot in this season -> DISCONTINUED
    model_ids = {lot["model_id"] for lot in db.lots.values() if lot["season_id"] == season["id"]}
    for model_id in model_ids:
        model = db.models.get(model_id)
        if model is not None and model["status"] in ("ACTIVE", "CLEARANCE_ELIGIBLE"):
            model["status"] = "DISCONTINUED"
            model["discontinued_at"] = clock.iso_z(now)
            model["support_obligation_until"] = clock.iso_z(
                clock.add_years(now, model["parts_support_years"])
            )
            touch(model)
    # hop 2: this season's lots of those models -> CLOSEOUT
    for lot in db.lots.values():
        if lot["season_id"] == season["id"] and lot["status"] in ("AVAILABLE", "DEPLETED"):
            lot["status"] = "CLOSEOUT"
            touch(lot)
    # hop 3: every remaining live allocation -> EXPIRED (collapse to committed)
    affected_models = set()
    affected_channels = set()
    for a in db.allocations.values():
        if a["season_id"] == season["id"] and a["status"] in ("OFFERED", "ACCEPTED", "PARTIALLY_CONSUMED"):
            a["allocated_units"] = a["committed_units"]
            a["status"] = "EXPIRED"
            touch(a)
            affected_models.add(a["model_id"])
            affected_channels.add(a["channel_account_id"])
    for model_id in affected_models:
        derive.recompute_lots(season["id"], model_id)
    for channel_id in affected_channels:
        channel = db.channels.get(channel_id)
        if channel is not None:
            derive.recompute_channel(channel)
    season["status"] = "TRANSITIONED"


@bp.post("/seasons/<season_id>/advance")
def advance_season(season_id):
    _, role = authenticate()
    require_role(role, PLANNER)
    season = _season_or_404(season_id)
    # rung 5: terminal lockdown / invalid-from is evaluated before the body
    if season["status"] == "CLOSED":
        raise api_error("ERR_INVALID_STATE", "a CLOSED season cannot advance")
    data = get_body()
    target = require(data, "target_status")
    if target not in SEASON_STATUSES:
        raise validation("target_status is not a valid season status")
    if target != SEASON_NEXT[season["status"]]:
        raise api_error("ERR_INVALID_STATE", "target_status must be the immediate next state")
    # per-transition guards (calendar guards read the logical clock)
    now = clock.now()
    if target == "ALLOCATION":
        has_lot = any(lot["season_id"] == season["id"] for lot in db.lots.values())
        if not has_lot:
            raise api_error("ERR_INVALID_STATE", "entering ALLOCATION requires at least one inventory lot")
    elif target == "IN_SEASON":
        if now < clock.parse_iso(season["in_season_start"]):
            raise api_error("ERR_INVALID_STATE", "logical clock has not reached in_season_start")
    elif target == "CLEARANCE":
        if now < clock.parse_iso(season["clearance_start"]):
            raise api_error("ERR_INVALID_STATE", "logical clock has not reached clearance_start")
    elif target == "TRANSITIONED":
        if now < clock.parse_iso(season["season_end"]):
            raise api_error("ERR_INVALID_STATE", "logical clock has not reached season_end")
    # effects
    if target == "ALLOCATION":
        _advance_to_allocation(season)
    elif target == "CLEARANCE":
        _advance_to_clearance(season)
    elif target == "TRANSITIONED":
        _advance_to_transitioned(season)
    else:
        season["status"] = target
    touch(season)
    return ok(season_out(season))


# ---------------------------------------------------------------------------
# Inventory lots (PRD §3.3)
# ---------------------------------------------------------------------------

@bp.post("/seasons/<season_id>/lots")
def create_lot(season_id):
    _, role = authenticate()
    require_role(role, PLANNER)
    season = _season_or_404(season_id)
    data = get_body()
    # rung 3 (body-carried reference): model must exist
    model_id = require(data, "model_id")
    model = db.models.get(model_id)
    if model is None:
        raise not_found("MODEL")
    # rung 5: posture gate
    if season["status"] not in ("PLANNING", "BUILD"):
        raise api_error("ERR_SEASON_POSTURE_FORBIDDEN", "lots can only be created while the season is PLANNING or BUILD")
    # rung 6: body
    build_week = req_str(data, "build_week")
    units_built = req_int(data, "units_built")
    if units_built < 0:
        raise validation("units_built must be >= 0")
    lot = new_entity({
        "season_id": season["id"],
        "model_id": model["id"],
        "build_week": build_week,
        "units_built": units_built,
        "units_available": units_built,
        "units_consumed": 0,
        "recommended_build_forward_units": derive.calc_forward_units(season, model),
        "recommended_build_actual_units": None,  # null until IN_SEASON
        "status": "BUILDING",
    })
    db.lots[lot["id"]] = lot
    return ok(lot_out(lot), status=201)


@bp.get("/seasons/<season_id>/lots")
def list_season_lots(season_id):
    _, role = authenticate()
    require_role(role, ("PlannerAdmin", "ChannelRep"))
    season = _season_or_404(season_id)
    items = [lot for lot in db.lots.values() if lot["season_id"] == season["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [lot for lot in items if lot["status"] == status]
    page, total, limit, offset = paginate(items)
    return ok_list([lot_out(lot) for lot in page], total, limit, offset)


@bp.get("/models/<model_id>/lots")
def list_model_lots(model_id):
    _, role = authenticate()
    require_role(role, ("PlannerAdmin", "ChannelRep"))
    model = db.models.get(model_id)
    if model is None:
        raise not_found("MODEL")
    items = [lot for lot in db.lots.values() if lot["model_id"] == model["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [lot for lot in items if lot["status"] == status]
    page, total, limit, offset = paginate(items)
    return ok_list([lot_out(lot) for lot in page], total, limit, offset)
