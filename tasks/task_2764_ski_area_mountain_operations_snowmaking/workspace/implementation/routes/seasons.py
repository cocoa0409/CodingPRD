"""Season configuration endpoints."""
from flask import Blueprint

import db
import response
import validate
from errors import ApiError
from middleware import auth, ALL_ROLES, MOUNTAIN_OPS_DIRECTOR
from services import calc, serialize

bp = Blueprint("seasons", __name__)

BASE_DEPTH_POLICIES = ("MEAN_OF_STAKES", "MIN_OF_STAKES")
ENERGY_TIERS = ("OFF_PEAK", "MID_PEAK", "ON_PEAK", "CRITICAL_PEAK")


def _energy_windows(raw):
    if len(raw) < 1 or len(raw) > 6:
        validate.bad("energy_windows must carry 1..6 entries")
    windows = []
    for entry in raw:
        if not isinstance(entry, dict):
            validate.bad("energy_windows entries must be objects")
        code = validate.get_str(entry, "code", max_len=32)
        start_hour = validate.get_int(entry, "start_hour_utc", minimum=0, maximum=24)
        end_hour = validate.get_int(entry, "end_hour_utc", minimum=0, maximum=24)
        price = validate.get_num(entry, "price_usd_per_kwh", minimum=0)
        tier = validate.get_enum(entry, "tier", ENERGY_TIERS, required=False)
        if start_hour >= end_hour:
            validate.bad("energy window start_hour_utc must be below end_hour_utc")
        window = {
            "code": code,
            "start_hour_utc": start_hour,
            "end_hour_utc": end_hour,
            "price_usd_per_kwh": price,
        }
        if tier is not None:
            window["tier"] = tier
        windows.append(window)
    ordered = sorted(windows, key=lambda w: w["start_hour_utc"])
    cursor = 0
    for window in ordered:
        if window["start_hour_utc"] != cursor:
            raise ApiError("ERR_ENERGY_WINDOW_COVERAGE_GAP")
        cursor = window["end_hour_utc"]
    if cursor != 24:
        raise ApiError("ERR_ENERGY_WINDOW_COVERAGE_GAP")
    return windows


@bp.route("/seasons", methods=["POST"])
def create_season():
    auth(MOUNTAIN_OPS_DIRECTOR)
    body = validate.body()
    label = validate.get_str(body, "season_label", max_len=32)
    water_right = validate.get_num(body, "water_right_seasonal_af", exclusive_minimum=0)
    plant_max = validate.get_int(body, "plant_max_gpm", minimum=1)
    kwh_per_af = validate.get_num(body, "snowmaking_kwh_per_af", exclusive_minimum=0)
    raw_windows = validate.get_list(body, "energy_windows")
    policy = validate.get_enum(body, "base_depth_policy", BASE_DEPTH_POLICIES,
                               required=False, default="MEAN_OF_STAKES")
    min_patrollers = validate.get_int(body, "min_patrollers_per_open_area",
                                     required=False, default=2, minimum=1)
    freshness = validate.get_int(body, "groom_freshness_hours",
                                required=False, default=18, minimum=1)
    windows = _energy_windows(raw_windows)
    for existing in db.store.seasons.values():
        if existing["season_label"] == label:
            raise ApiError("ERR_DUPLICATE_CODE")
    row = db.new_row({
        "season_label": label,
        "base_depth_policy": policy,
        "water_right_seasonal_af": water_right,
        "plant_max_gpm": plant_max,
        "snowmaking_kwh_per_af": kwh_per_af,
        "min_patrollers_per_open_area": min_patrollers,
        "groom_freshness_hours": freshness,
        "energy_windows": windows,
        "season_state": "PRESEASON",
        "water_reserved_af": 0.0,
        "water_used_af": 0.0,
        "snow_produced_swe_af": 0.0,
        "open_area_count": 0,
    })
    db.store.seasons[row["id"]] = row
    return response.object_response(serialize.season(row), 201)


@bp.route("/seasons/<season_id>", methods=["GET"])
def get_season(season_id):
    auth(*ALL_ROLES)
    row = validate.path_row(db.store.seasons, season_id, "ERR_SEASON_NOT_FOUND")
    return response.object_response(serialize.season(row), 200)


@bp.route("/seasons/<season_id>/snow-accounting", methods=["GET"])
def snow_accounting(season_id):
    auth(*ALL_ROLES)
    row = validate.path_row(db.store.seasons, season_id, "ERR_SEASON_NOT_FOUND")
    return response.object_response(calc.season_accounting(row), 200)
