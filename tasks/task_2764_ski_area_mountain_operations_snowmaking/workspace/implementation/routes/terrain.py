"""Terrain area, snow depth, terrain park and opening-decision endpoints."""
from flask import Blueprint

import db
import response
import validate
from errors import ApiError
from middleware import (auth, acting_patroller, ALL_ROLES, MOUNTAIN_OPS_DIRECTOR,
                        SNOWMAKING_SUPERVISOR, GROOMING_LEAD, PATROLLER)
from services import calc, cascade, serialize

bp = Blueprint("terrain", __name__)

TERRAIN_CLASSES = ("GREEN", "BLUE", "BLACK", "PARK")
OPENING_STATES = ("CLOSED", "PREP", "READY", "OPEN", "PATROL_HOLD", "SEASON_CLOSED")
FEATURE_TYPES = ("JUMP", "RAIL", "JIB", "HALFPIPE")
SIZE_CLASSES = ("S", "M", "L")
READING_SOURCES = ("MANUAL_STAKE", "AUTOMATED_SENSOR")
DECISIONS = ("OPEN", "CLOSE")


@bp.route("/terrain-areas", methods=["POST"])
def create_area():
    auth(MOUNTAIN_OPS_DIRECTOR)
    body = validate.body()
    season = validate.fk(body, "season_id", db.store.seasons, "ERR_SEASON_NOT_FOUND")
    lift = validate.fk(body, "serving_lift_id", db.store.lifts, "ERR_LIFT_NOT_FOUND")
    if season is not None and lift is not None and lift["season_id"] != season["id"]:
        raise ApiError("ERR_CROSS_SEASON_REFERENCE")
    validate.get_str(body, "season_id")
    validate.get_str(body, "serving_lift_id")
    trail_code = validate.get_str(body, "trail_code", max_len=32)
    terrain_class = validate.get_enum(body, "terrain_class", TERRAIN_CLASSES)
    acres = validate.get_num(body, "acres", exclusive_minimum=0)
    min_depth = validate.get_int(body, "min_open_base_depth_in", minimum=0)
    name = validate.get_str(body, "name", required=False, max_len=120)
    avalanche = validate.get_bool(body, "avalanche_terrain", required=False, default=False)
    for existing in db.season_areas(season["id"]):
        if existing["trail_code"] == trail_code:
            raise ApiError("ERR_DUPLICATE_CODE")
    cascade.require_season_writable(season)
    row = db.new_row({
        "season_id": season["id"],
        "serving_lift_id": lift["id"],
        "trail_code": trail_code,
        "name": name,
        "terrain_class": terrain_class,
        "acres": acres,
        "min_open_base_depth_in": min_depth,
        "avalanche_terrain": avalanche,
        "opening_state": "CLOSED",
        "park_state": "NO_PARK",
        "park_feature_count": 0,
        "park_risk_score": 0.0,
        "park_built_by_user_id": None,
        "park_inspected_by_user_id": None,
        "last_groomed_at": None,
        "groom_coverage_pct": 0.0,
        "mitigation_clearance_expires_at": None,
        "machine_swe_af": 0.0,
    })
    db.store.areas[row["id"]] = row
    return response.object_response(serialize.terrain_area(row), 201)


@bp.route("/terrain-areas/<area_id>", methods=["GET"])
def get_area(area_id):
    auth(*ALL_ROLES)
    row = validate.path_row(db.store.areas, area_id, "ERR_TERRAIN_AREA_NOT_FOUND")
    return response.object_response(serialize.terrain_area(row), 200)


@bp.route("/terrain-areas", methods=["GET"])
def list_areas():
    auth(*ALL_ROLES)
    limit, offset = validate.pagination()
    rows = db.ordered(db.store.areas)
    season_id = validate.query_value("season_id")
    serving_lift_id = validate.query_value("serving_lift_id")
    opening_state = validate.query_value("opening_state")
    terrain_class = validate.query_value("terrain_class")
    if season_id:
        rows = [r for r in rows if r["season_id"] == season_id]
    if serving_lift_id:
        rows = [r for r in rows if r["serving_lift_id"] == serving_lift_id]
    if opening_state:
        rows = [r for r in rows if r["opening_state"] == opening_state]
    if terrain_class:
        rows = [r for r in rows if r["terrain_class"] == terrain_class]
    return response.list_response(rows, serialize.terrain_area, limit, offset)


@bp.route("/terrain-areas/<area_id>/snow-depth-readings", methods=["POST"])
def create_reading(area_id):
    auth(GROOMING_LEAD, SNOWMAKING_SUPERVISOR, PATROLLER, MOUNTAIN_OPS_DIRECTOR)
    area = validate.path_row(db.store.areas, area_id, "ERR_TERRAIN_AREA_NOT_FOUND")
    body = validate.body()
    stake_code = validate.get_str(body, "stake_code", max_len=16)
    depth_in = validate.get_num(body, "depth_in", minimum=0)
    measured_at = validate.get_dt(body, "measured_at")
    density = validate.get_num(body, "density_pct", required=False, default=10.0,
                               exclusive_minimum=0, maximum=60)
    source = validate.get_enum(body, "source", READING_SOURCES,
                               required=False, default="MANUAL_STAKE")
    if measured_at > db.now():
        raise ApiError("ERR_READING_TIMESTAMP_FUTURE")
    season = db.season_of_area(area)
    cascade.require_season_writable(season)
    row = db.new_row({
        "terrain_area_id": area["id"],
        "stake_code": stake_code,
        "depth_in": depth_in,
        "density_pct": density,
        "measured_at": measured_at,
        "source": source,
    }, versioned=False)
    db.store.readings[row["id"]] = row
    db.mark(area)
    cascade.reevaluate_readiness(area)
    return response.object_response(serialize.snow_depth_reading(row), 201)


@bp.route("/terrain-areas/<area_id>/snow-depth-readings", methods=["GET"])
def list_readings(area_id):
    auth(*ALL_ROLES)
    area = validate.path_row(db.store.areas, area_id, "ERR_TERRAIN_AREA_NOT_FOUND")
    limit, offset = validate.pagination()
    rows = db.area_readings(area["id"])
    stake_code = validate.query_value("stake_code")
    source = validate.query_value("source")
    if stake_code:
        rows = [r for r in rows if r["stake_code"] == stake_code]
    if source:
        rows = [r for r in rows if r["source"] == source]
    return response.list_response(rows, serialize.snow_depth_reading, limit, offset)


@bp.route("/terrain-areas/<area_id>/park-build", methods=["POST"])
def park_build(area_id):
    user_id, _role = auth(GROOMING_LEAD, PATROLLER)
    area = validate.path_row(db.store.areas, area_id, "ERR_TERRAIN_AREA_NOT_FOUND")
    body = validate.body()
    raw_features = validate.get_list(body, "features")
    features = []
    for entry in raw_features:
        if not isinstance(entry, dict):
            validate.bad("features entries must be objects")
        features.append({
            "feature_type": validate.get_enum(entry, "feature_type", FEATURE_TYPES),
            "size_class": validate.get_enum(entry, "size_class", SIZE_CLASSES),
        })
    season = db.season_of_area(area)
    cascade.require_season_writable(season)
    if area["terrain_class"] != "PARK":
        raise ApiError("ERR_TERRAIN_STATE_INVALID")
    if area["opening_state"] == "SEASON_CLOSED":
        raise ApiError("ERR_TERRAIN_STATE_INVALID")
    if features and area["park_state"] not in ("NO_PARK", "PARK_BUILT", "PARK_CLOSED"):
        raise ApiError("ERR_TERRAIN_STATE_INVALID")
    area["park_built_by_user_id"] = user_id
    area["park_inspected_by_user_id"] = None
    area["park_feature_count"] = len(features)
    area["park_risk_score"] = calc.park_risk_score(features)
    db.mark(area)
    if features:
        area["park_state"] = "PARK_BUILT"
    else:
        area["park_state"] = "PARK_CLOSED"
        if area["opening_state"] == "OPEN":
            cascade.hold_area(area)
            cascade.refresh_after_terrain_change(season, force=True)
    cascade.reevaluate_readiness(area)
    return response.object_response(serialize.terrain_area(area), 200)


@bp.route("/terrain-areas/<area_id>/park-inspection", methods=["POST"])
def park_inspection(area_id):
    user_id, _role, patroller = acting_patroller(PATROLLER)
    area = validate.path_row(db.store.areas, area_id, "ERR_TERRAIN_AREA_NOT_FOUND")
    body = validate.body()
    validate.get_str(body, "inspection_note", required=False, max_len=500,
                     allow_blank=True)
    season = db.season_of_area(area)
    cascade.require_season_writable(season)
    if area["park_state"] != "PARK_BUILT":
        raise ApiError("ERR_TERRAIN_STATE_INVALID")
    if area["park_built_by_user_id"] is not None \
            and user_id == area["park_built_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION")
    if not patroller["on_duty"]:
        raise ApiError("ERR_PATROLLER_NOT_ON_DUTY")
    area["park_state"] = "PARK_INSPECTED"
    area["park_inspected_by_user_id"] = user_id
    db.mark(area)
    cascade.reevaluate_readiness(area)
    return response.object_response(serialize.terrain_area(area), 200)


@bp.route("/terrain-areas/<area_id>/opening-decision", methods=["POST"])
def opening_decision(area_id):
    auth(MOUNTAIN_OPS_DIRECTOR)
    area = validate.path_row(db.store.areas, area_id, "ERR_TERRAIN_AREA_NOT_FOUND")
    body = validate.body()
    decision = validate.get_enum(body, "decision", DECISIONS)
    validate.get_str(body, "note", required=False, max_len=500, allow_blank=True)
    season = db.season_of_area(area)
    cascade.require_season_writable(season, require_operating=True)
    if decision == "OPEN":
        if area["opening_state"] not in ("READY", "PATROL_HOLD"):
            raise ApiError("ERR_TERRAIN_STATE_INVALID")
    else:
        if area["opening_state"] not in ("OPEN", "PATROL_HOLD"):
            raise ApiError("ERR_TERRAIN_STATE_INVALID")
    cascade.require_active_day_plan(season["id"],
                                   require_published=(decision == "OPEN"))
    if decision == "OPEN":
        failure = cascade.readiness_failure(area)
        if failure is None:
            failure = cascade.lift_failure(area)
        if failure is not None:
            raise ApiError(failure)
        area["opening_state"] = "OPEN"
        db.mark(area)
    else:
        cascade.close_area(area, defer=True)
    cascade.refresh_after_terrain_change(season, force=True)
    return response.object_response(serialize.terrain_area(area), 200)
