"""Clock, ops runs, partnerships and markets."""

from flask import Blueprint, request

from clock import CLOCK
from db import DB
from errors import ApiError
from response import ok, public
from routes import actor, payload
from services import lifecycle, sweep

bp = Blueprint("config", __name__)

HANDOFF_MODELS = ("MOBILE_PUSH", "CONCIERGE_DESK", "HYBRID")


@bp.post("/_clock/set_current_utc")
def set_clock():
    actor(["PlatformAdmin"])
    body = payload()
    CLOCK.set(body.get("to_iso8601"))
    return ok({})


@bp.post("/ops-runs")
def ops_run():
    actor(["PlatformAdmin"])
    body = payload()
    return ok(sweep.run(body.get("as_of_iso8601")))


@bp.post("/productions")
def create_production():
    actor(["OpsManager"])
    body = payload()
    refund_window_hours = body.get("refund_window_hours")
    exchange_fee_cents = body.get("exchange_fee_cents")
    refund_window_hours = 0 if refund_window_hours is None else int(refund_window_hours)
    exchange_fee_cents = 0 if exchange_fee_cents is None else int(exchange_fee_cents)
    if refund_window_hours < 0 or exchange_fee_cents < 0:
        raise ApiError("ERR_INVALID_STATE")
    production = {
        "title": body.get("title"),
        "producer_org": body.get("producer_org"),
        "status": "DRAFT",
        "refund_window_hours": refund_window_hours,
        "exchange_fee_cents": exchange_fee_cents,
        "exchange_allowed": bool(body.get("exchange_allowed", False)),
    }
    DB.insert("production", production)
    return ok(public(production), 201)


@bp.get("/productions/<production_id>")
def read_production(production_id):
    """Read a production; the lookup surface resolves a production_id."""
    actor(
        [
            "OpsManager",
            "AllocationsCoordinator",
            "ProducerAnalyst",
            "DemandAnalyst",
            "CustomerService",
            "PlatformAdmin",
        ]
    )
    production = DB.get("production", production_id)
    if production is None:
        raise ApiError("ERR_PRODUCTION_NOT_FOUND")
    return ok(public(production))


@bp.post("/productions/<production_id>/status-transitions")
def production_transition(production_id):
    actor(["OpsManager"])
    body = payload()
    production = DB.get("production", production_id)
    if production is None:
        raise ApiError("ERR_PRODUCTION_NOT_FOUND")
    to_status = body.get("to_status")
    expected = body.get("expected_production_version")
    if expected is not None and str(expected) != str(production.get("version")):
        raise ApiError("ERR_STALE_VERSION")
    lifecycle.apply_production_transition(
        production, to_status, body.get("suspension_reason")
    )
    return ok(public(production))


@bp.post("/markets")
def create_market():
    actor(["OpsManager", "PlatformAdmin"])
    body = payload()
    market_code = body.get("market_code")
    if market_code is None or not str(market_code).strip():
        raise ApiError("ERR_INVALID_STATE")
    for existing in DB.all("market"):
        if existing["market_code"] == market_code:
            raise ApiError("ERR_INVALID_STATE")
    handoff_model = body.get("handoff_model") or "MOBILE_PUSH"
    if handoff_model not in HANDOFF_MODELS:
        raise ApiError("ERR_INVALID_STATE")
    market = {
        "market_code": market_code,
        "city": body.get("city"),
        "handoff_model": handoff_model,
    }
    DB.insert("market", market)

    desk_code = body.get("desk_code")
    daily_capacity = body.get("daily_capacity")
    if desk_code and daily_capacity and handoff_model != "MOBILE_PUSH":
        capacity = int(daily_capacity)
        if capacity <= 0:
            raise ApiError("ERR_INVALID_STATE")
        _create_desk(market_code, desk_code, capacity)
    return ok(public(market), 201)


def _create_desk(market_code, desk_code, daily_capacity):
    for existing in DB.all("desk"):
        if existing["market_code"] == market_code and existing["desk_code"] == desk_code:
            raise ApiError("ERR_INVALID_STATE")
    desk = {
        "market_code": market_code,
        "desk_code": desk_code,
        "daily_capacity": int(daily_capacity),
        "handoffs_today": 0,
        "status": "OPEN",
    }
    DB.insert("desk", desk)
    return desk


@bp.get("/markets/<market_id>")
def read_market(market_id):
    actor(
        [
            "OpsManager",
            "AllocationsCoordinator",
            "ConciergeDeskStaff",
            "CustomerService",
            "DemandAnalyst",
        ]
    )
    market = DB.get("market", market_id)
    if market is None:
        raise ApiError("ERR_MARKET_NOT_FOUND")
    return ok(public(market))