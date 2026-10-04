"""Production forecasts (PRD 3.7).

POST /farm-network/farms/{id}/forecasts   (NetworkManager, 201)
GET  /farm-network/farms/{id}/forecasts   (NetworkManager, PlatformAdmin, 200)
"""
from flask import Blueprint, request

import constants as C
import domain
import store
from auth import authenticate, authorize
from clock import now
from errors import ApiError
from responses import ok, ok_list
from serialize import forecast_out
from validation import get_body, f_enum, f_date, pagination

bp = Blueprint("forecasts", __name__, url_prefix="/farm-network")


@bp.route("/farms/<fid>/forecasts", methods=["POST"])
def create_forecast(fid):
    uid, role = authenticate()
    authorize(role, ("NetworkManager",))
    farm = domain.get_farm_or_404(fid)
    data = get_body()
    week_raw, week = f_date(data, "week_start")
    season = f_enum(data, "season", C.SEASONS)
    severity = f_enum(data, "weather_severity", C.WEATHER_SEVERITIES)
    if farm["status"] != "ACTIVE":
        raise ApiError("ERR_FARM_NOT_ACTIVE", 409, "farm is not ACTIVE")
    for f in store.forecasts.values():
        if f["farm_id"] == farm["id"] and f["week_start"] == week_raw:
            raise ApiError("ERR_FORECAST_EXISTS", 409,
                           "a forecast already exists for this farm and week")
    optimistic, conservative = domain.forecast_variants(
        farm["declared_bird_count"], season, severity)
    ts = now()
    forecast = {
        "id": domain.new_id(),
        "farm_id": farm["id"],
        "week_start": week_raw,
        "season": season,
        "weather_severity": severity,
        "optimistic_dozens": optimistic,
        "conservative_dozens": conservative,
        "created_at": ts,
        "_seq": store.next_seq(),
    }
    store.forecasts[forecast["id"]] = forecast
    return ok(forecast_out(forecast), 201)


@bp.route("/farms/<fid>/forecasts", methods=["GET"])
def list_forecasts(fid):
    uid, role = authenticate()
    authorize(role, ("NetworkManager", "PlatformAdmin"))
    farm = domain.get_farm_or_404(fid)
    limit, offset = pagination()
    week_start = request.args.get("week_start")
    rows = [f for f in store.forecasts.values() if f["farm_id"] == farm["id"]]
    if week_start is not None:
        rows = [f for f in rows if f["week_start"] == week_start]
    page, total = domain.sorted_page(rows, limit, offset)
    return ok_list([forecast_out(f) for f in page], limit, offset, total)
