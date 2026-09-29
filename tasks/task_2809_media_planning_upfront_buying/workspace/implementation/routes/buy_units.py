"""Airing settlement and the preemption cascade (PRD 3.8)."""

from flask import Blueprint

from auth import require_roles, require_seller_owner
from constants import AIRING_OUTCOMES
from errors import ApiError, bad_request
from lookup import get
from response import ok
from routes.common import listing, read_one
from serializers import serialize
from services import cascades, derive
from store import store
from validation import body

bp = Blueprint("buy_units", __name__)


@bp.post("/buy-units/<buy_unit_id>/settle-airing")
@require_roles("SellerRep")
def settle_airing(buy_unit_id):
    data = body()
    outcome = data.enum("outcome", AIRING_OUTCOMES)
    actual_impressions = data.integer("actual_impressions", required=False, minimum=1)
    if outcome == "AIRED" and actual_impressions is None:
        raise bad_request("actual_impressions is required when the unit aired")

    unit = get("units", buy_unit_id)
    forecast = store.forecasts.get(unit["forecast_id"])
    if forecast is not None:
        require_seller_owner(forecast["seller_id"])

    if unit["status"] not in ("SCHEDULED", "MAKE_GOOD_SCHEDULED"):
        raise ApiError("ERR_UNIT_NOT_SCHEDULED")
    if outcome == "PREEMPTED" and unit["status"] != "SCHEDULED":
        # Preemption is only available to an ordered line.
        raise ApiError("ERR_UNIT_NOT_SCHEDULED")
    if store.now() < unit["air_window_end"]:
        raise ApiError("ERR_AIR_WINDOW_NOT_ELAPSED")

    buy = store.buys.get(unit["buy_id"])
    if outcome == "AIRED":
        unit["status"] = "AIRED" if unit["status"] == "SCHEDULED" else "MAKE_GOOD_AIRED"
        unit["actual_impressions"] = actual_impressions
        store.touch(unit)
    else:
        unit["status"] = "PREEMPTED"
        store.touch(unit)
        if forecast is not None:
            cascades.sync_forecast(forecast)
        if buy is not None:
            if derive.placed_impressions(buy) < buy["guaranteed_impressions"]:
                if buy["stewardship_status"] in ("NOT_STARTED", "ON_TRACK"):
                    buy["stewardship_status"] = "AT_RISK"
            store.touch(buy)
    return ok(serialize("units", unit))


@bp.get("/buy-units/<buy_unit_id>")
def get_buy_unit(buy_unit_id):
    return read_one("units", buy_unit_id)


@bp.get("/buy-units")
def list_buy_units():
    return listing(
        "units",
        {
            "buy_id": "buy_id",
            "forecast_id": "forecast_id",
            "make_good_id": "make_good_id",
            "status": "status",
        },
    )
