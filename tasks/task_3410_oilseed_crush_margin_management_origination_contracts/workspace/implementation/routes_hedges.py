"""Board crush hedge positions: enter, read, confirm (SoD), offset."""
from decimal import Decimal

from flask import Blueprint

from auth import require_roles
from calc import BEAN_CONTRACT_BUSHELS, crush_spread, quotes3, round_int
from envelope import success_obj
from errors import fail
from store import db, new_id, stamp_new, to_jsonable, touch
from validate import body_dict, req_datetime, req_int, req_month

bp = Blueprint("hedges", __name__)


@bp.post("/api/board-crush-positions")
def create_position():
    uid, _role = require_roles("CrushTrader")
    body = body_dict()
    month = req_month(body, "futures_month")
    bean_lots = req_int(body, "bean_lots_long")
    oil_lots = req_int(body, "oil_lots_short")
    meal_lots = req_int(body, "meal_lots_short")
    if bean_lots < 1:
        fail("ERR_INVALID_REQUEST", "bean_lots_long must be >= 1")
    if oil_lots < 0 or meal_lots < 0:
        fail("ERR_INVALID_REQUEST", "short lot counts must be >= 0")
    expiry = req_datetime(body, "expiry_date")
    # Lock the spread from as-of quotes (priority 11).
    q = quotes3(month)
    if q is None:
        fail("ERR_NO_MARKET_QUOTE",
             "as-of BEAN/OIL/MEAL quotes are required for futures_month")
    bean, oil, meal = q
    spread = crush_spread(bean, oil, meal)
    rec = {
        "id": new_id(),
        "futures_month": month,
        "bean_lots_long": bean_lots,
        "oil_lots_short": oil_lots,
        "meal_lots_short": meal_lots,
        "expiry_date": expiry,
        "locked_spread_cents_per_bushel": spread,
        "locked_margin_cents": round_int(spread * bean_lots * BEAN_CONTRACT_BUSHELS),
        "realized_pnl_cents": None,
        "entered_by_user_id": uid,
        "confirmed_by_user_id": None,
        "status": "ENTERED",
    }
    stamp_new(rec)
    db["hedges"][rec["id"]] = rec
    return success_obj(to_jsonable(rec), 201)


def _get_position_or_404(pid):
    rec = db["hedges"].get(pid)
    if rec is None:
        fail("ERR_POSITION_NOT_FOUND", "board crush position not found")
    return rec


@bp.get("/api/board-crush-positions/<pid>")
def get_position(pid):
    require_roles("PlatformAdmin", "CrushTrader", "RiskManager")
    return success_obj(to_jsonable(_get_position_or_404(pid)))


@bp.post("/api/board-crush-positions/<pid>/confirm")
def confirm_position(pid):
    uid, _role = require_roles("RiskManager")
    rec = _get_position_or_404(pid)
    # State (priority 6).
    if rec["status"] != "ENTERED":
        fail("ERR_INVALID_STATE", "position is not in ENTERED")
    # Safety (priority 8): segregation of duties.
    if uid is not None and uid == rec["entered_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the confirming RiskManager must differ from the entering trader")
    rec["confirmed_by_user_id"] = uid
    rec["status"] = "CONFIRMED"
    touch(rec)
    return success_obj(to_jsonable(rec))


@bp.post("/api/board-crush-positions/<pid>/offset")
def offset_position(pid):
    require_roles("CrushTrader")
    rec = _get_position_or_404(pid)
    # State (priority 6, dedicated variant).
    if rec["status"] != "CONFIRMED":
        fail("ERR_POSITION_NOT_CONFIRMED", "position is not in CONFIRMED")
    # Referenced market data (priority 11).
    q = quotes3(rec["futures_month"])
    if q is None:
        fail("ERR_NO_MARKET_QUOTE",
             "as-of BEAN/OIL/MEAL quotes are required for futures_month")
    bean, oil, meal = q
    current_spread = crush_spread(bean, oil, meal)
    rec["realized_pnl_cents"] = round_int(
        (current_spread - rec["locked_spread_cents_per_bushel"])
        * rec["bean_lots_long"] * BEAN_CONTRACT_BUSHELS)
    rec["status"] = "OFFSET"
    touch(rec)
    return success_obj(to_jsonable(rec))
