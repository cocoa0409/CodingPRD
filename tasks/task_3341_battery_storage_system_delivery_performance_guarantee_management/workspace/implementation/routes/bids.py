"""BidSession routes: open/list/get/record-clearing/settle/cancel."""
from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles, ALL_ROLES
from pagination import paginate
from response import success_object, success_list
from services import active_esa_for_project
from util import new_id, stamp_new, touch, req_enum, req_pos_number, req_nonneg_int, parse_iso, round2, to_number

bp = Blueprint("bids", __name__)

MARKETS = {"DAY_AHEAD", "REAL_TIME"}


def serialize_session(s):
    return dict(s)


def get_session_or_404(sid):
    s = store.bid_sessions.get(sid)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", 404, "BidSession not found")
    return s


def _overlaps(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


@bp.route("/bid-sessions", methods=["POST"])
@require_roles({"MarketOperator"})
def create_session():
    body = request.get_json(silent=True) or {}
    project_id = body.get("project_id")
    if not isinstance(project_id, str) or project_id not in store.projects:
        raise ApiError("ERR_PROJECT_NOT_FOUND", 404, "project_id does not reference an existing Project")
    market = req_enum(body, "market", MARKETS)
    offer = req_pos_number(body, "offer_mwh")
    price = req_nonneg_int(body, "offer_price_cents_per_mwh")
    ws_raw = body.get("window_start")
    we_raw = body.get("window_end")
    ws = parse_iso(ws_raw, "window_start")
    we = parse_iso(we_raw, "window_end")
    if we <= ws:
        raise ApiError("ERR_INVALID_WINDOW", 409, "window_end must be strictly after window_start")
    if active_esa_for_project(project_id) is None:
        raise ApiError("ERR_NO_ACTIVE_ESA", 409,
                       "Project must have an ESA in EXECUTED or COMPLETED")
    for s in store.bid_sessions.values():
        if s["project_id"] == project_id and s["status"] in ("OPEN", "CLEARED"):
            ss = parse_iso(s["window_start"], "window_start")
            se = parse_iso(s["window_end"], "window_end")
            if _overlaps(ws, we, ss, se):
                raise ApiError("ERR_BID_WINDOW_OVERLAP", 409,
                               "Bid window overlaps another OPEN or CLEARED session on this project")
    s = {
        "id": new_id(),
        "project_id": project_id,
        "market": market,
        "window_start": ws_raw,
        "window_end": we_raw,
        "offer_mwh": offer,
        "offer_price_cents_per_mwh": price,
        "clearing_price_cents_per_mwh": None,
        "market_cleared_mwh": None,
        "cleared_mwh": None,
        "revenue_cents": 0,
        "status": "OPEN",
    }
    stamp_new(s)
    store.bid_sessions[s["id"]] = s
    return success_object(serialize_session(s), 201)


@bp.route("/bid-sessions", methods=["GET"])
@require_roles(set(ALL_ROLES))
def list_sessions():
    project_id = request.args.get("project_id")
    items = [s for s in store.bid_sessions.values()
             if project_id is None or s["project_id"] == project_id]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_session(s) for s in page], limit, offset, total)


@bp.route("/bid-sessions/<sid>", methods=["GET"])
@require_roles(set(ALL_ROLES))
def get_session(sid):
    return success_object(serialize_session(get_session_or_404(sid)))


@bp.route("/bid-sessions/<sid>/record-clearing", methods=["POST"])
@require_roles({"MarketOperator"})
def record_clearing(sid):
    s = get_session_or_404(sid)
    if s["status"] != "OPEN":
        raise ApiError("ERR_BID_SESSION_NOT_OPEN", 409, "Session must be OPEN")
    body = request.get_json(silent=True) or {}
    clearing_price = body.get("clearing_price_cents_per_mwh")
    if not isinstance(clearing_price, int) or isinstance(clearing_price, bool) or clearing_price < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "clearing_price_cents_per_mwh must be a non-negative integer")
    market_cleared = body.get("market_cleared_mwh")
    if isinstance(market_cleared, bool) or not isinstance(market_cleared, (int, float)) or market_cleared < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "market_cleared_mwh must be a non-negative number")

    project = store.projects.get(s["project_id"])
    projected = Decimal(str(project.get("projected_capacity_mwh") or 0))
    capacity_cap = min(projected, Decimal(str(market_cleared)))
    if clearing_price < s["offer_price_cents_per_mwh"]:
        cleared = Decimal("0")
    else:
        cleared = min(Decimal(str(s["offer_mwh"])), capacity_cap)
    cleared = round2(cleared)
    s["clearing_price_cents_per_mwh"] = clearing_price
    s["market_cleared_mwh"] = market_cleared
    s["cleared_mwh"] = to_number(cleared)
    s["status"] = "CLEARED"
    touch(s)
    return success_object(serialize_session(s))


@bp.route("/bid-sessions/<sid>/settle", methods=["POST"])
@require_roles({"MarketOperator"})
def settle_session(sid):
    s = get_session_or_404(sid)
    if s["status"] != "CLEARED":
        raise ApiError("ERR_BID_SESSION_NOT_CLEARED", 409, "Settle requires CLEARED")
    revenue = (Decimal(str(s["cleared_mwh"])) * Decimal(str(s["clearing_price_cents_per_mwh"])))
    s["revenue_cents"] = int(revenue.quantize(Decimal("1"), rounding="ROUND_HALF_UP"))
    s["status"] = "SETTLED"
    touch(s)
    return success_object(serialize_session(s))


@bp.route("/bid-sessions/<sid>/cancel", methods=["POST"])
@require_roles({"MarketOperator"})
def cancel_session(sid):
    s = get_session_or_404(sid)
    if s["status"] != "OPEN":
        raise ApiError("ERR_BID_SESSION_NOT_OPEN", 409, "Session must be OPEN")
    s["status"] = "CANCELLED"
    touch(s)
    return success_object(serialize_session(s))
