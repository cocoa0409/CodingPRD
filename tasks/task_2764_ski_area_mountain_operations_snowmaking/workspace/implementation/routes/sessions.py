"""Snowmaking session scheduling and metering (PRD 3.4, 3.5)."""
from decimal import Decimal

from flask import Blueprint

import db
import response
import validate
from errors import ApiError
from middleware import auth, ALL_ROLES, SNOWMAKING_SUPERVISOR
from util import dec, floor_int, rhu
from services import calc, cascade, serialize

bp = Blueprint("sessions", __name__)

TARGET_STATES = ("RUNNING", "PAUSED", "COMPLETED")
BLOCKED_TERRAIN = ("PATROL_HOLD", "SEASON_CLOSED")


@bp.route("/snowmaking-sessions", methods=["POST"])
def create_session():
    auth(SNOWMAKING_SUPERVISOR)
    body = validate.body()
    # Priority 4: body references in declaration order, then cross-season.
    area = validate.fk(body, "terrain_area_id", db.store.areas,
                       "ERR_TERRAIN_AREA_NOT_FOUND")
    pump = validate.fk(body, "pump_house_id", db.store.pumps,
                       "ERR_PUMP_HOUSE_NOT_FOUND")
    if area is not None and pump is not None:
        if area["season_id"] != pump["season_id"]:
            raise ApiError("ERR_CROSS_SEASON_REFERENCE")
    # Priority 5: schema conformance.
    validate.get_str(body, "terrain_area_id")
    validate.get_str(body, "pump_house_id")
    window_start = validate.get_dt(body, "window_start")
    window_end = validate.get_dt(body, "window_end")
    gun_count = validate.get_int(body, "gun_count", minimum=1)
    gpm = validate.get_int(body, "gpm", minimum=1)
    expected_version = validate.get_int(body, "expected_terrain_area_version",
                                        minimum=0)
    # Priority 6: interval sanity.
    if window_start >= window_end:
        raise ApiError("ERR_WINDOW_INVALID")
    season = db.store.seasons.get(area["season_id"])
    # Priority 11.
    cascade.require_season_writable(season)
    # Priority 12.
    if area["opening_state"] in BLOCKED_TERRAIN:
        raise ApiError("ERR_TERRAIN_STATE_INVALID")
    # Priority 17: stale-read protection on the plan-bearing write.
    if expected_version != area["version"]:
        raise ApiError("ERR_STALE_TERRAIN_AREA_VERSION")
    # Priority 35.
    if pump["status"] != "ONLINE":
        raise ApiError("ERR_PUMP_HOUSE_OFFLINE")
    # Priority 42 then 43: pump house ceiling always before the plant ceiling.
    if calc.pump_capacity_would_exceed(pump, window_start, window_end, gpm):
        raise ApiError("ERR_PUMP_CAPACITY_EXCEEDED")
    if calc.plant_capacity_would_exceed(season, window_start, window_end, gpm):
        raise ApiError("ERR_PLANT_CAPACITY_EXCEEDED")
    # Priority 44: the whole ledger, not the remaining balance alone.
    planned_minutes = floor_int(
        dec((window_end - window_start).total_seconds()) / Decimal("60"))
    reserved = calc.water_af(gpm, planned_minutes)
    total = (dec(season["water_used_af"]) + dec(season["water_reserved_af"])
             + dec(reserved))
    if total > dec(season["water_right_seasonal_af"]):
        raise ApiError("ERR_WATER_RIGHT_EXCEEDED")

    row = db.new_row({
        "terrain_area_id": area["id"],
        "pump_house_id": pump["id"],
        "window_start": window_start,
        "window_end": window_end,
        "planned_minutes": planned_minutes,
        "gun_count": gun_count,
        "gpm": gpm,
        "state": "SCHEDULED",
        "wet_bulb_f": None,
        "started_at": None,
        "last_running_since": None,
        "ended_at": None,
        "accumulated_run_minutes": 0,
        "water_af_reserved": reserved,
        "water_af_actual": 0.0,
        "snow_yield_factor": None,
        "snow_swe_af": 0.0,
        "energy_kwh": 0.0,
        "energy_cost_usd": 0.0,
        "demand_surcharge_applied": False,
        "abort_reason": None,
    })
    db.store.sessions[row["id"]] = row
    cascade.add_reserved(season, reserved)
    # Supersede every overlapping SCHEDULED peer on the same terrain area.
    for peer in db.area_sessions(area["id"]):
        if peer["id"] == row["id"] or peer["state"] != "SCHEDULED":
            continue
        if peer["window_start"] < window_end and peer["window_end"] > window_start:
            cascade.abort_session(peer, "SUPERSEDED")
    cascade.recompute_pump_peak(pump)
    if area["opening_state"] == "CLOSED":
        area["opening_state"] = "PREP"
        db.mark(area)
    return response.object_response(serialize.session(row), 201)


@bp.route("/snowmaking-sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    auth(*ALL_ROLES)
    row = validate.path_row(db.store.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    return response.object_response(serialize.session(row), 200)


@bp.route("/snowmaking-sessions", methods=["GET"])
def list_sessions():
    auth(*ALL_ROLES)
    limit, offset = validate.pagination()
    rows = db.ordered(db.store.sessions)
    area_id = validate.query_value("terrain_area_id")
    pump_id = validate.query_value("pump_house_id")
    state = validate.query_value("state")
    abort_reason = validate.query_value("abort_reason")
    if area_id:
        rows = [r for r in rows if r["terrain_area_id"] == area_id]
    if pump_id:
        rows = [r for r in rows if r["pump_house_id"] == pump_id]
    if state:
        rows = [r for r in rows if r["state"] == state]
    if abort_reason:
        rows = [r for r in rows if r["abort_reason"] == abort_reason]
    return response.list_response(rows, serialize.session, limit, offset)


ALLOWED_MOVES = {
    "SCHEDULED": ("RUNNING",),
    "RUNNING": ("PAUSED", "COMPLETED"),
    "PAUSED": ("RUNNING", "COMPLETED"),
    "COMPLETED": (),
    "ABORTED": (),
}


@bp.route("/snowmaking-sessions/<session_id>/status", methods=["POST"])
def set_session_status(session_id):
    auth(SNOWMAKING_SUPERVISOR)
    session = validate.path_row(db.store.sessions, session_id,
                               "ERR_SESSION_NOT_FOUND")
    body = validate.body()
    target = validate.get_enum(body, "target_state", TARGET_STATES)
    area = db.area_of_session(session)
    pump = db.store.pumps.get(session["pump_house_id"])
    season = db.season_of_session(session)
    # Priority 11: starting demands OPERATING; every other move demands writability.
    cascade.require_season_writable(season, require_operating=(target == "RUNNING"))
    # Priority 13.
    current = session["state"]
    if target not in ALLOWED_MOVES.get(current, ()):
        raise ApiError("ERR_SESSION_STATE_INVALID")
    # Priority 16: an active plan (any active posture) must exist.
    plan = cascade.require_active_day_plan(season["id"])
    if target == "RUNNING":
        # Priority 34 before priority 35.
        factor = calc.wet_bulb_yield_factor(plan["wet_bulb_f"])
        if factor is None:
            raise ApiError("ERR_WET_BULB_TOO_WARM")
        if pump["status"] != "ONLINE":
            raise ApiError("ERR_PUMP_HOUSE_OFFLINE")
        if area is not None and area["opening_state"] in BLOCKED_TERRAIN:
            raise ApiError("ERR_TERRAIN_STATE_INVALID")
        session["wet_bulb_f"] = plan["wet_bulb_f"]
        session["snow_yield_factor"] = float(factor)
        session["last_running_since"] = db.now()
        if current == "SCHEDULED":
            session["started_at"] = db.now()
            pump["active_session_count"] += 1
            db.mark(pump)
        session["state"] = "RUNNING"
        db.mark(session)
    elif target == "PAUSED":
        _close_segment(session)
        session["state"] = "PAUSED"
        session["last_running_since"] = None
        db.mark(session)
    else:
        cascade.complete_session(session)
    return response.object_response(serialize.session(session), 200)


def _close_segment(session):
    since = session.get("last_running_since")
    if since is None:
        return
    elapsed = db.now() - since
    session["accumulated_run_minutes"] += floor_int(
        dec(elapsed.total_seconds()) / Decimal("60"))
