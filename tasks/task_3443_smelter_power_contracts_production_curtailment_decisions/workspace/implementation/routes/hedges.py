"""Hedge positions: open and close (PRD 3.7)."""
from flask import Blueprint

from auth import require_roles
from constants import HEDGE_INSTRUMENTS
from db import STORE, bump, logical_clock, new_id, stamp_new
from envelope import ok_object
from errors import raise_err
from serializers import hedge_json
from services.core import expire_hedges, lazy_expire_hedge, monthly_capacity
from util import D, as_enum, as_number, as_str, get_body, parse_month, req, round2_dec

bp = Blueprint("hedges", __name__, url_prefix="/smelter-ops")


def get_hedge_or_404(hedge_id):
    h = STORE["hedge_positions"].get(hedge_id)
    if h is None:
        raise_err("ERR_NOT_FOUND", "HedgePosition not found.")
    return h


@bp.post("/hedge-positions")
@require_roles("TradingAnalyst")
def create_hedge():
    body = get_body()
    smelter_id = as_str(req(body, "smelter_id"), "smelter_id")
    smelter = STORE["smelters"].get(smelter_id)
    if smelter is None:
        raise_err("ERR_NOT_FOUND", "Smelter not found.")
    instrument = as_enum(req(body, "instrument"), "instrument", HEDGE_INSTRUMENTS)
    volume = as_number(req(body, "volume_tonnes"), "volume_tonnes")
    if volume <= 0:
        raise_err("ERR_INVALID_REQUEST", "volume_tonnes must be > 0.")
    strike = as_number(req(body, "strike_price_usd"), "strike_price_usd")
    if strike <= 0:
        raise_err("ERR_INVALID_REQUEST", "strike_price_usd must be > 0.")
    delivery_month = req(body, "delivery_month")
    year, month = parse_month(delivery_month, "delivery_month")
    now = logical_clock()
    if (year, month) < (now.year, now.month):
        raise_err(
            "ERR_INVALID_REQUEST",
            "delivery_month must not be earlier than the current month.",
        )
    # Gate A: aggregate OPEN volume for (smelter, delivery_month) <= monthly capacity.
    expire_hedges(smelter_id)
    open_volume = D(0)
    for h in STORE["hedge_positions"].values():
        if (
            h["smelter_id"] == smelter_id
            and h["status"] == "OPEN"
            and h["delivery_ym"] == (year, month)
        ):
            open_volume += D(h["volume_tonnes"])
    if open_volume + D(volume) > monthly_capacity(smelter):
        raise_err(
            "ERR_HEDGE_VOLUME_EXCEEDS_EXPOSURE",
            "OPEN hedge volume for the delivery month exceeds monthly capacity.",
        )
    rec = stamp_new(
        {
            "id": new_id(),
            "smelter_id": smelter_id,
            "instrument": instrument,
            "volume_tonnes": volume,
            "strike_price_usd": strike,
            "delivery_month": delivery_month,
            "delivery_ym": (year, month),
            "status": "OPEN",
            "closed_price_usd": None,
            "realized_pnl_usd": None,
        }
    )
    STORE["hedge_positions"][rec["id"]] = rec
    return ok_object(hedge_json(rec), 201)


@bp.post("/hedge-positions/<hedge_id>/close")
@require_roles("TradingAnalyst")
def close_hedge(hedge_id):
    h = get_hedge_or_404(hedge_id)
    lazy_expire_hedge(h)
    if h["status"] != "OPEN":
        raise_err(
            "ERR_INVALID_LIFECYCLE_STATE",
            "Only an OPEN hedge position can be closed.",
        )
    body = get_body()
    closed_price = as_number(req(body, "closed_price_usd"), "closed_price_usd")
    h["closed_price_usd"] = closed_price
    h["realized_pnl_usd"] = round2_dec(
        (D(closed_price) - D(h["strike_price_usd"])) * D(h["volume_tonnes"])
    )
    h["status"] = "CLOSED"
    bump(h)
    return ok_object(hedge_json(h))
