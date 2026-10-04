"""AnalyticsRun endpoints: indices, forecasts and attribution removal (PRD 3.5)."""
from datetime import timedelta

from flask import Blueprint, request

import auth
import calc
import core
import lookups
import responses
from serializers import analytics_run as ser_run

bp = Blueprint("analytics", __name__, url_prefix="/data-research")

ADJUSTMENT_MODES = {"UNADJUSTED", "HEDONIC"}
SELECTORS = {"LATEST", "EARLIEST", "UPPER_BOUND"}


@bp.post("/analytics/index-runs")
def create_index_run():
    auth.authorize(["ResearchAnalyst", "SeatUser"])
    payload = core.body_of(request)
    market = core.require_string(payload, "market")
    window_start = core.require_datetime(payload, "window_start")
    window_end = core.require_datetime(payload, "window_end")
    adjustment_mode = core.optional_enum(payload, "adjustment_mode", ADJUSTMENT_MODES, "UNADJUSTED")
    excluded = core.optional_string_list(payload, "excluded_property_ids", [])

    if not window_end > window_start:
        raise core.ApiError("ERR_INVALID_REQUEST", "window_end must be after window_start.")

    result = calc.market_index_value(
        market, window_start, window_end, adjustment_mode, excluded)
    if result["comp_count"] == 0:
        raise core.ApiError("ERR_EMPTY_INDEX_SET")

    record = {
        "market": market,
        "run_type": "INDEX",
        "adjustment_mode": adjustment_mode,
        "window_start": core.fmt_dt(window_start),
        "window_end": core.fmt_dt(window_end),
        "index_value": result["index_value"],
        "comp_count": result["comp_count"],
        "mean_effective_rent_psf": result["mean_effective_rent_psf"],
        "median_effective_rent_psf": result["median_effective_rent_psf"],
        "selector": "LATEST",
        "horizon_quarters": None,
        "forecast_value": None,
        "forecast_due_at": None,
        "attributed_records_delta": result["comp_count"],
        "attribution_status": "ATTRIBUTED",
    }
    core.stamp_created(record)
    core.analytics_runs[record["id"]] = record
    return responses.ok_object(ser_run(record), 201)


@bp.get("/analytics/index-runs")
def list_index_runs():
    auth.authorize(["ResearchAnalyst", "SeatUser", "LicensingAdmin"])
    limit, offset = core.pagination_args(request)
    rows = [r for r in core.analytics_runs.values() if r["run_type"] == "INDEX"]
    market = request.args.get("market")
    if market:
        rows = [r for r in rows if r["market"] == market]
    return responses.paged(rows, limit, offset, ser_run)


@bp.post("/analytics/forecasts")
def create_forecast():
    auth.authorize(["ResearchAnalyst", "SeatUser"])
    payload = core.body_of(request)
    market = core.require_string(payload, "market")
    selector = core.require_enum(payload, "selector", SELECTORS)
    horizon_quarters = core.optional_int(payload, "horizon_quarters", core.DEFAULT_HORIZON_QUARTERS)
    due_date = core.optional_datetime(payload, "due_date", None)

    candidates = [r for r in core.analytics_runs.values()
                  if r["market"] == market and r["run_type"] == "INDEX"
                  and r["index_value"] is not None]
    if due_date is not None:
        candidates = [r for r in candidates if core.parse_dt(r["created_at"]) <= due_date]

    base, ambiguity = calc.select_base_run(market, selector, candidates)
    if ambiguity == "AMBIGUOUS_SELECTION":
        raise core.ApiError(
            "ERR_INVALID_REQUEST",
            "AMBIGUOUS_SELECTION: two runs tie on the greatest index value.")
    if base is None:
        raise core.ApiError("ERR_INVALID_REQUEST",
                            "No prior index run exists for that market.")

    forecast_value = calc.market_forecast(base["index_value"], horizon_quarters)
    window_end = core.parse_dt(base["window_end"])
    forecast_due_at = window_end + timedelta(days=91 * horizon_quarters)

    record = {
        "market": market,
        "run_type": "FORECAST",
        "adjustment_mode": base["adjustment_mode"],
        "window_start": base["window_start"],
        "window_end": base["window_end"],
        "index_value": base["index_value"],
        "comp_count": base["comp_count"],
        "mean_effective_rent_psf": base["mean_effective_rent_psf"],
        "median_effective_rent_psf": base["median_effective_rent_psf"],
        "selector": selector,
        "horizon_quarters": horizon_quarters,
        "forecast_value": forecast_value,
        "forecast_due_at": core.fmt_dt(forecast_due_at),
        "attributed_records_delta": base["comp_count"],
        "attribution_status": "ATTRIBUTED",
    }
    core.stamp_created(record)
    core.analytics_runs[record["id"]] = record
    return responses.ok_object(ser_run(record), 201)


@bp.get("/analytics/forecasts")
def list_forecasts():
    auth.authorize(["ResearchAnalyst", "SeatUser", "LicensingAdmin"])
    limit, offset = core.pagination_args(request)
    rows = [r for r in core.analytics_runs.values() if r["run_type"] == "FORECAST"]
    market = request.args.get("market")
    if market:
        rows = [r for r in rows if r["market"] == market]
    return responses.paged(rows, limit, offset, ser_run)


@bp.post("/analytics/index-runs/<run_id>/attribution-removals")
def remove_attribution(run_id):
    auth.authorize(["LicensingAdmin", "EnforcementOfficer"])
    core.body_of(request)
    record = lookups.get_run(run_id)
    record["attributed_records_delta"] = 0
    record["attribution_status"] = "UNWOUND"
    core.touch(record)
    return responses.ok_object(ser_run(record))