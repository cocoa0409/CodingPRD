"""Customer forecast endpoints: file, list, close (with accuracy cascade)."""
from flask import Blueprint, request

from db import store, new_id, now_iso, next_seq, touch
from errors import (ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_DUPLICATE_PERIOD)
from middleware import actor, require_role, require_customer_owner
from response import ok_object, ok_list
from services import calc
from services.serialize import forecast_public
from validation import body_json, req_str, req_int, parse_period, pagination_args

bp = Blueprint("forecasts", __name__)


@bp.post("/supply-agreements/<aid>/forecasts")
def create_forecast(aid):
    user_id, role = actor()
    require_role(role, ["CustomerPlanner"])
    agr = store["agreements"].get(aid)
    if agr is not None:
        require_customer_owner(user_id, agr["customer_id"])
    data = body_json()
    period = parse_period(req_str(data, "period"), "period")
    forecast_qty = req_int(data, "forecast_qty", minimum=0)
    if agr is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Supply agreement not found.")
    for f in store["forecasts"].values():
        if f["agreement_id"] == aid and f["period"] == period:
            raise ApiError(ERR_DUPLICATE_PERIOD[0], ERR_DUPLICATE_PERIOD[1],
                           "A forecast for period %s already exists for this agreement." % period)
    ts = now_iso()
    forecast = {
        "id": new_id(),
        "agreement_id": aid,
        "period": period,
        "forecast_qty": forecast_qty,
        "actual_qty": None,
        "accuracy_pct": None,
        "status": "OPEN",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_sort": next_seq(),
    }
    store["forecasts"][forecast["id"]] = forecast
    return ok_object(forecast_public(forecast), code=201)


@bp.get("/supply-agreements/<aid>/forecasts")
def list_forecasts(aid):
    actor()
    if store["agreements"].get(aid) is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Supply agreement not found.")
    limit, offset = pagination_args()
    status = request.args.get("status")
    items = sorted(
        (f for f in store["forecasts"].values() if f["agreement_id"] == aid),
        key=lambda f: f["_created_sort"],
    )
    if status is not None:
        items = [f for f in items if f["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([forecast_public(f) for f in page], limit, offset, total)


@bp.post("/forecasts/<fid>/close")
def close_forecast(fid):
    user_id, role = actor()
    require_role(role, ["CustomerPlanner"])
    forecast = store["forecasts"].get(fid)
    if forecast is not None:
        agr = store["agreements"].get(forecast["agreement_id"])
        if agr is not None:
            require_customer_owner(user_id, agr["customer_id"])
    data = body_json()
    actual_qty = req_int(data, "actual_qty", minimum=0)
    if forecast is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Forecast not found.")
    if forecast["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only an OPEN forecast can be closed.")
    forecast["actual_qty"] = actual_qty
    forecast["accuracy_pct"] = float(
        calc.forecast_accuracy_pct(forecast["forecast_qty"], actual_qty)
    )
    forecast["status"] = "CLOSED"
    touch(forecast)
    # Agreement rolling/lifetime accuracy fields are derived at read time.
    return ok_object(forecast_public(forecast))
