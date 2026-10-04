"""Market price observations (PRD 2.10)."""
from flask import Blueprint

from auth import require_roles
from constants import GLOBAL_REGION, INSTRUMENTS, REGION_CODES, REGIONAL_INSTRUMENTS
from db import STORE, logical_clock, new_id, now_wall
from envelope import ok_object
from errors import raise_err
from serializers import price_observation_json
from util import as_datetime, as_enum, as_number, decimal_places_ok, get_body, req

bp = Blueprint("prices", __name__, url_prefix="/smelter-ops")


@bp.post("/price-observations")
@require_roles("TradingAnalyst", "EnergyManager")
def create_price_observation():
    body = get_body()
    instrument = as_enum(req(body, "instrument"), "instrument", INSTRUMENTS)
    if instrument in REGIONAL_INSTRUMENTS:
        region = as_enum(req(body, "region_code"), "region_code", REGION_CODES)
    else:
        region = as_enum(req(body, "region_code"), "region_code", (GLOBAL_REGION,))
    observed_at = as_datetime(req(body, "observed_at"), "observed_at")
    if observed_at > logical_clock():
        raise_err(
            "ERR_INVALID_REQUEST",
            "observed_at must not lie after the current logical clock.",
        )
    price = as_number(req(body, "price_usd"), "price_usd")
    if price <= 0:
        raise_err("ERR_INVALID_REQUEST", "price_usd must be > 0.")
    if not decimal_places_ok(price, 2):
        raise_err(
            "ERR_INVALID_REQUEST",
            "price_usd must be quoted with at most 2 decimal places.",
        )
    rec = {
        "id": new_id(),
        "instrument": instrument,
        "region_code": region,
        "observed_at": observed_at,
        "price_usd": price,
        "created_at": now_wall(),
    }
    STORE["price_observations"][rec["id"]] = rec
    return ok_object(price_observation_json(rec), 201)
