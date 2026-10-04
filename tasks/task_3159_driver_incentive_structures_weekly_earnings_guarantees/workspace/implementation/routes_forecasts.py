"""CostForecast approve/reject endpoints (top-level)."""
from flask import Blueprint, request

import db
from errors import (
    err_budget_exceeded,
    err_forecast_not_draft,
    err_invalid_request,
    err_stale_program_version,
)
from middleware import require_roles
from response import success_object
from services import (
    forecast_view,
    get_forecast_or_404,
    get_market_or_404,
    get_program_or_404,
    market_available,
    require_int,
    touch,
)

bp = Blueprint("forecasts", __name__)


@bp.post("/cost-forecasts/<fid>/approve")
@require_roles("IncentiveOps")
def approve_forecast(fid, _user_id, _role):
    f = get_forecast_or_404(fid)
    if f["status"] != "DRAFT":
        raise err_forecast_not_draft()
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    if "expected_program_version" not in body:
        raise err_invalid_request("expected_program_version is required")
    expected = require_int(body.get("expected_program_version"), "expected_program_version")
    program = get_program_or_404(f["program_id"])
    if expected != program["version"]:
        raise err_stale_program_version()
    market = get_market_or_404(program["market_id"])
    if f["projected_cost_cents"] > market_available(market):
        raise err_budget_exceeded("Projected cost exceeds available budget")

    for other in db.forecasts.values():
        if (
            other["program_id"] == program["id"]
            and other["id"] != f["id"]
            and other["status"] == "APPROVED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)

    f["status"] = "APPROVED"
    touch(f)
    program["forecast_headroom_cents"] = market_available(market) - f["projected_cost_cents"]
    touch(program)
    return success_object(forecast_view(f))


@bp.post("/cost-forecasts/<fid>/reject")
@require_roles("IncentiveOps")
def reject_forecast(fid, _user_id, _role):
    f = get_forecast_or_404(fid)
    if f["status"] != "DRAFT":
        raise err_forecast_not_draft()
    f["status"] = "REJECTED"
    touch(f)
    return success_object(forecast_view(f))
