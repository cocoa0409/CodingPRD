"""SupplyShortfall endpoints."""
import math
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import err_geo_cell_unknown, err_invalid_request, err_invalid_state
from middleware import require_roles
from response import success_object
from services import (
    get_market_or_404,
    get_shortfall_or_404,
    new_entity,
    parse_iso,
    require_int,
    shortfall_view,
    touch,
    touch_expiry,
)

bp = Blueprint("shortfalls", __name__)


def _cell_median_base_fare(market_id, geo_cell_id):
    cutoff = db.now() - timedelta(weeks=4)
    fares = []
    for r in db.rides.values():
        if r["market_id"] != market_id or r["geo_cell_id"] != geo_cell_id:
            continue
        if r["status"] != "COMPLETED":
            continue
        comp = r.get("completed_at")
        if not comp:
            continue
        if parse_iso(comp) >= cutoff:
            fares.append(r["base_fare_cents"])
    if not fares:
        return 0
    fares.sort()
    n = len(fares)
    if n % 2 == 1:
        return fares[n // 2]
    return (fares[n // 2 - 1] + fares[n // 2]) // 2


@bp.post("/supply-shortfalls")
@require_roles("IncentiveOps")
def create_shortfall(_user_id, _role):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    market_id = body.get("market_id")
    if not isinstance(market_id, str):
        raise err_invalid_request("market_id is required")
    market = get_market_or_404(market_id)
    geo_cell_id = body.get("geo_cell_id")
    if not isinstance(geo_cell_id, str):
        raise err_invalid_request("geo_cell_id is required")
    if geo_cell_id not in market["geo_cells"]:
        raise err_geo_cell_unknown()
    hour_bucket = require_int(body.get("hour_bucket"), "hour_bucket", minimum=0, maximum=167)
    severity_bps = require_int(body.get("severity_bps"), "severity_bps", minimum=1, maximum=10000)

    median = _cell_median_base_fare(market["id"], geo_cell_id)
    recommended = math.ceil(severity_bps * median / 10000)

    s = new_entity(
        {
            "market_id": market["id"],
            "geo_cell_id": geo_cell_id,
            "hour_bucket": hour_bucket,
            "severity_bps": severity_bps,
            "recommended_bonus_cents": recommended,
            "status": "OPEN",
        }
    )
    db.shortfalls[s["id"]] = s
    return success_object(shortfall_view(s), 201)


@bp.get("/supply-shortfalls/<sid>")
@require_roles("PlatformAdmin", "IncentiveOps")
def get_shortfall(sid, _user_id, _role):
    s = get_shortfall_or_404(sid)
    touch_expiry("shortfall", s)
    return success_object(shortfall_view(s))


@bp.post("/supply-shortfalls/<sid>/address")
@require_roles("IncentiveOps")
def address_shortfall(sid, _user_id, _role):
    s = get_shortfall_or_404(sid)
    touch_expiry("shortfall", s)
    if s["status"] != "OPEN":
        raise err_invalid_state("Shortfall must be OPEN to address")
    s["status"] = "ADDRESSED"
    touch(s)
    return success_object(shortfall_view(s))
