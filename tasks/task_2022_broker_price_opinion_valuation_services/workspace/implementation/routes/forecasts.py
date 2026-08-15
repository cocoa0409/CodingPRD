"""Volume forecast endpoints (PRD 3.8)."""

from flask import Blueprint, request

import db
from middleware import allowed
from response import success_object, success_list
from serializers import ser_volume_forecast
from services.forecasting import compute_predicted_order_count, MODEL_VERSION
from validation import body, req_str, sort_and_page

bp = Blueprint("forecasts", __name__)

STATE_CODE_PATTERN = r"^[A-Z]{2}$"
MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


@bp.post("/bpo/volume-forecasts")
@allowed("OperationsManager", "PlatformAdmin")
def create_volume_forecast(user_id, role):
    b = body()
    state_code = req_str(b, "state_code", pattern=STATE_CODE_PATTERN)
    forecast_month = req_str(b, "forecast_month", pattern=MONTH_PATTERN)

    predicted = compute_predicted_order_count(state_code, forecast_month)
    record = db.stamp_new_append_only({
        "id": db.new_id(),
        "state_code": state_code,
        "forecast_month": forecast_month,
        "predicted_order_count": predicted,
        "model_version": MODEL_VERSION,
        "generated_at": db.logical_now(),
    })
    db.volume_forecasts[record["id"]] = record
    return success_object(ser_volume_forecast(record), 201)


@bp.get("/bpo/volume-forecasts")
@allowed("OperationsManager", "PlatformAdmin")
def list_volume_forecasts(user_id, role):
    records = list(db.volume_forecasts.values())
    state_code = request.args.get("state_code")
    if state_code is not None:
        records = [r for r in records if r["state_code"] == state_code]
    forecast_month = request.args.get("forecast_month")
    if forecast_month is not None:
        records = [r for r in records if r["forecast_month"] == forecast_month]
    items, limit, offset, total = sort_and_page(records, ser_volume_forecast)
    return success_list(items, limit, offset, total)
