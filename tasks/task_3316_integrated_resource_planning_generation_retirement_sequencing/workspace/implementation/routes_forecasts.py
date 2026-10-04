"""LoadForecast routes: nested under plans, plus flat reads."""

from flask import Blueprint, request

from calculations import SCENARIO_TAGS, compute_forecast_totals
from db import store
from errors import (
    ERR_DUPLICATE_FORECAST, ERR_FORECAST_LOCKED, ERR_FORECAST_NOT_FOUND,
    ERR_INVALID_REQUEST, ERR_PLAN_NOT_DRAFT, raise_error,
)
from helpers import (
    body, get_int, get_num, paginate, parse_pagination, require_enum,
    require_fields, stamp_new, touch,
)
from middleware import require_roles
from response import success_list, success_object
from routes_plans import ALL_ROLES, get_plan_or_404
from serializers import forecast_view

bp = Blueprint("forecasts", __name__)


def get_forecast_or_404(forecast_id: str, plan_id: str = None) -> dict:
    f = store.forecasts.get(forecast_id)
    if f is None or (plan_id is not None and f["plan_id"] != plan_id):
        raise_error(ERR_FORECAST_NOT_FOUND, f"Forecast {forecast_id} not found")
    return f


def _validate_contributions(payload, existing=None):
    """Extract the four class contributions, validating >= 0 numbers."""
    out = {}
    for field in ("residential_mw", "commercial_mw", "industrial_mw", "electrification_mw"):
        if field in payload:
            v = get_num(payload, field)
        elif existing is not None:
            v = existing[field]
        else:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        if v < 0:
            raise_error(ERR_INVALID_REQUEST, f"{field} must be >= 0")
        out[field] = v
    return out


@bp.route("/plans/<planId>/forecasts", methods=["POST"])
@require_roles("UtilityPlanner")
def create_forecast(user_id, role, planId):
    plan = get_plan_or_404(planId)
    payload = body()
    require_fields(payload, "scenario_tag", "forecast_year",
                   "residential_mw", "commercial_mw", "industrial_mw", "electrification_mw")
    scenario_tag = require_enum(payload, "scenario_tag", SCENARIO_TAGS)
    forecast_year = get_int(payload, "forecast_year")
    if plan["status"] != "DRAFT":
        raise_error(ERR_PLAN_NOT_DRAFT, "Plan is not DRAFT")
    if forecast_year > plan["cycle_year"] + plan["planning_horizon_years"]:
        raise_error(ERR_INVALID_REQUEST, "forecast_year outside plan horizon")
    contrib = _validate_contributions(payload)
    for f in store.forecasts.values():
        if (f["plan_id"] == plan["id"] and f["scenario_tag"] == scenario_tag
                and f["forecast_year"] == forecast_year):
            raise_error(ERR_DUPLICATE_FORECAST,
                        "Forecast for (plan, scenario, year) already exists")
    total, effective = compute_forecast_totals(
        contrib["residential_mw"], contrib["commercial_mw"],
        contrib["industrial_mw"], contrib["electrification_mw"],
    )
    f = stamp_new({
        "plan_id": plan["id"],
        "scenario_tag": scenario_tag,
        "forecast_year": forecast_year,
        **contrib,
        "total_peak_mw": total,
        "effective_load_mw": effective,
        "locked": False,
    })
    store.forecasts[f["id"]] = f
    return success_object(forecast_view(f), 201)


@bp.route("/plans/<planId>/forecasts", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_plan_forecasts(user_id, role, planId):
    plan = get_plan_or_404(planId)
    limit, offset = parse_pagination()
    items = [f for f in store.forecasts.values() if f["plan_id"] == plan["id"]]
    if "scenario_tag" in request.args:
        items = [f for f in items if f["scenario_tag"] == request.args["scenario_tag"]]
    page, total = paginate(items, limit, offset)
    return success_list([forecast_view(f) for f in page], limit, offset, total)


@bp.route("/plans/<planId>/forecasts/<forecastId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_plan_forecast(user_id, role, planId, forecastId):
    get_plan_or_404(planId)
    f = get_forecast_or_404(forecastId, plan_id=planId)
    return success_object(forecast_view(f), 200)


@bp.route("/plans/<planId>/forecasts/<forecastId>", methods=["PUT"])
@require_roles("UtilityPlanner")
def update_forecast(user_id, role, planId, forecastId):
    get_plan_or_404(planId)
    f = get_forecast_or_404(forecastId, plan_id=planId)
    if f["locked"]:
        raise_error(ERR_FORECAST_LOCKED, "Forecast row is locked")
    payload = body()
    contrib = _validate_contributions(payload, existing=f)
    total, effective = compute_forecast_totals(
        contrib["residential_mw"], contrib["commercial_mw"],
        contrib["industrial_mw"], contrib["electrification_mw"],
    )
    f.update(contrib)
    f["total_peak_mw"] = total
    f["effective_load_mw"] = effective
    touch(f)
    return success_object(forecast_view(f), 200)


# --- Flat reads -------------------------------------------------------------

@bp.route("/forecasts", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_forecasts(user_id, role):
    limit, offset = parse_pagination()
    items = list(store.forecasts.values())
    if "plan_id" in request.args:
        items = [f for f in items if f["plan_id"] == request.args["plan_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([forecast_view(f) for f in page], limit, offset, total)


@bp.route("/forecasts/<forecastId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_forecast_flat(user_id, role, forecastId):
    f = get_forecast_or_404(forecastId)
    return success_object(forecast_view(f), 200)
