"""Inventory forecasts - the avail marketplace (PRD 3.4)."""

from flask import Blueprint

from auth import require_roles, require_seller_owner
from constants import DAYPARTS, EXCLUSIVITY_MODES, MARKETS, PLATFORMS
from errors import ApiError
from lookup import get
from response import created, ok
from routes.common import listing, read_one
from routes.campaigns import fiscal_quarter
from serializers import serialize
from services import derive
from store import store
from validation import body, require_window

bp = Blueprint("forecasts", __name__)


@bp.post("/inventory-forecasts")
@require_roles("SellerRep")
def create_forecast():
    data = body()
    seller_id = data.string("seller_id")
    market = data.enum("market", MARKETS)
    quarter = fiscal_quarter(data)
    daypart = data.enum("daypart", DAYPARTS)
    program = data.string("program", max_len=120)
    platform = data.enum("platform", PLATFORMS)
    window_start = data.timestamp("window_start")
    window_end = data.timestamp("window_end")
    total_impressions = data.integer("total_impressions", minimum=1)
    forecast_cpm_cents = data.integer("forecast_cpm_cents", minimum=1)
    exclusivity_mode = data.enum(
        "exclusivity_mode", EXCLUSIVITY_MODES, required=False, default="SHARED"
    )
    require_window(window_start, window_end, "window")

    seller = get("sellers", seller_id)
    require_seller_owner(seller["id"])

    record = store.new(
        "forecasts",
        {
            "seller_id": seller["id"],
            "market": market,
            "fiscal_quarter": quarter,
            "daypart": daypart,
            "program": program,
            "platform": platform,
            "window_start": window_start,
            "window_end": window_end,
            "total_impressions": total_impressions,
            "forecast_cpm_cents": forecast_cpm_cents,
            "exclusivity_mode": exclusivity_mode,
            "status": "DRAFT",
        },
    )
    return created(serialize("forecasts", record))


@bp.post("/inventory-forecasts/<forecast_id>/publish")
@require_roles("SellerRep")
def publish_forecast(forecast_id):
    forecast = get("forecasts", forecast_id)
    require_seller_owner(forecast["seller_id"])
    if forecast["status"] != "DRAFT":
        raise ApiError("ERR_FORECAST_NOT_IN_EXPECTED_STATE")
    if derive.available_impressions(forecast) <= 0:
        raise ApiError("ERR_FORECAST_NOT_IN_EXPECTED_STATE")

    forecast["status"] = "PUBLISHED"
    store.touch(forecast)
    return ok(serialize("forecasts", forecast))


@bp.get("/inventory-forecasts/<forecast_id>")
def get_forecast(forecast_id):
    return read_one("forecasts", forecast_id)


@bp.get("/inventory-forecasts")
def list_forecasts():
    return listing(
        "forecasts",
        {
            "seller_id": "seller_id",
            "market": "market",
            "fiscal_quarter": "fiscal_quarter",
            "platform": "platform",
            "status": "status",
        },
    )
