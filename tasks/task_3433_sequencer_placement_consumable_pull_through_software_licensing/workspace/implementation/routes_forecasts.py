"""Supply forecast endpoints: create, reads (with variance view), advance
(SUBMIT with horizon + capacity checks, FREEZE with OCC and supersession)."""

from flask import Blueprint

from auth import require_roles
from calc import cold_chain_capacity_ok, forecast_variance_lines, forecast_week_ok
from envelope import ok, ok_list, sort_items, truthy_param
from errors import ApiError, invalid_state, not_found
from serializers import forecast_json
from store import DB, new_id, stamp_new, touch
from validate import (
    f_enum,
    f_int,
    f_list,
    f_str,
    get_body,
    resolve_line_kit_codes,
)
from timeutil import parse_dt

bp = Blueprint("forecasts", __name__)


def _validate_lines(body):
    lines = f_list(body, "lines")
    if not lines:
        raise ApiError("ERR_INVALID_REQUEST", 400, "lines must contain at least one entry")
    parsed = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "lines entries must be objects")
        kit_code = ln.get("kit_code")
        week_start = ln.get("week_start")
        quantity = ln.get("quantity")
        if not isinstance(kit_code, str) or kit_code == "":
            raise ApiError("ERR_INVALID_REQUEST", 400, "lines.kit_code must be a non-empty string")
        week_dt = parse_dt(week_start) if isinstance(week_start, str) else None
        if week_dt is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "lines.week_start must be an ISO 8601 timestamp"
            )
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ApiError("ERR_INVALID_REQUEST", 400, "lines.quantity must be an integer >= 1")
        parsed.append({"kit_code": kit_code, "week_start": week_dt, "quantity": quantity})
    return parsed


def _check_horizon(lines):
    for ln in lines:
        if not forecast_week_ok(ln["week_start"]):
            raise ApiError(
                "ERR_FORECAST_HORIZON_INVALID",
                422,
                "week_start must be a Monday 00:00:00Z, not before the current week, "
                "and within the 26-week horizon",
            )


@bp.post("/genomics/supply-forecasts")
def create_forecast():
    require_roles("SupplyPlanner")
    body = get_body()
    resolve_line_kit_codes(body.get("lines"))
    account_id = f_str(body, "account_id")
    lines = _validate_lines(body)
    _check_horizon(lines)
    forecast = {
        "id": new_id(),
        "account_id": account_id,
        "lines": lines,
        "forecast_state": "DRAFT",
    }
    stamp_new(forecast)
    DB["forecasts"][forecast["id"]] = forecast
    return ok(forecast_json(forecast), 201)


@bp.get("/genomics/supply-forecasts/<forecast_id>")
def get_forecast(forecast_id):
    require_roles("SupplyPlanner", "AccountManager")
    forecast = DB["forecasts"].get(forecast_id)
    if forecast is None:
        raise not_found("SupplyForecast not found")
    variance = forecast_variance_lines(forecast) if truthy_param("include_variance") else []
    return ok(forecast_json(forecast, variance))


@bp.get("/genomics/supply-forecasts")
def list_forecasts():
    require_roles("SupplyPlanner")
    items = list(DB["forecasts"].values())
    from flask import request

    account_id = request.args.get("account_id")
    forecast_state = request.args.get("forecast_state")
    if account_id is not None:
        items = [f for f in items if f["account_id"] == account_id]
    if forecast_state is not None:
        items = [f for f in items if f["forecast_state"] == forecast_state]
    return ok_list([forecast_json(f) for f in sort_items(items)])


@bp.post("/genomics/supply-forecasts/<forecast_id>/advance")
def advance_forecast(forecast_id):
    require_roles("SupplyPlanner")
    forecast = DB["forecasts"].get(forecast_id)
    if forecast is None:
        raise not_found("SupplyForecast not found")
    body = get_body()
    action = f_enum(body, "action", ["SUBMIT", "FREEZE"])
    if action == "SUBMIT":
        if forecast["forecast_state"] != "DRAFT":
            raise invalid_state("SUBMIT requires forecast_state DRAFT")
        _check_horizon(forecast["lines"])
        if not cold_chain_capacity_ok(forecast["lines"]):
            raise ApiError(
                "ERR_CAPACITY_EXCEEDED",
                422,
                "A weekly cold-chain capacity bucket would be exceeded",
            )
        forecast["forecast_state"] = "SUBMITTED"
    else:  # FREEZE
        expected_version = f_int(body, "expected_forecast_version", required=True)
        if forecast["forecast_state"] != "SUBMITTED":
            raise invalid_state("FREEZE requires forecast_state SUBMITTED")
        if expected_version is not None and expected_version != forecast["version"]:
            raise ApiError(
                "ERR_STALE_VERSION",
                412,
                "expected_forecast_version does not match the forecast's current version",
            )
        forecast["forecast_state"] = "FROZEN"
        for other in DB["forecasts"].values():
            if (
                other["id"] != forecast["id"]
                and other["account_id"] == forecast["account_id"]
                and other["forecast_state"] == "FROZEN"
            ):
                other["forecast_state"] = "SUPERSEDED"
                touch(other)
    touch(forecast)
    return ok(forecast_json(forecast))
