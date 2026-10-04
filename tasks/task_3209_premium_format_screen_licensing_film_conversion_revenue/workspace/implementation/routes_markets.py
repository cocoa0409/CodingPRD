"""Markets endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    ERR_MARKET_NOT_FOUND, ERR_INVALID_STATE, ERR_NO_SIGNED_AGREEMENT,
    bad_request, conflict, not_found,
)
from util import (
    require_role, get_body, req_str, req_int, req_list, parse_pagination, paginate,
    success_object, success_list, stamp_new, touch, sort_by_created,
)
from domain import serialize_market, serialize_agreement

bp = Blueprint("markets", __name__)

VALID_FORMATS = {"PREMIUM_2D", "PREMIUM_3D", "PREMIUM_70MM"}


def get_market_or_404(market_id):
    m = db.markets.get(market_id)
    if m is None:
        raise not_found(ERR_MARKET_NOT_FOUND, f"Market {market_id} not found")
    return m


@bp.post("/v1/markets")
def create_market():
    require_role("NetworkPlanner")
    body = get_body()
    market_name = req_str(body, "market_name")
    country_code = req_str(body, "country_code")
    screen_capacity_cap = req_int(body, "screen_capacity_cap")
    target_format_mix = req_list(body, "target_format_mix")
    for f in target_format_mix:
        if f not in VALID_FORMATS:
            raise bad_request("ERR_INVALID_REQUEST", f"target_format_mix entry {f} invalid")
    market = {
        "market_name": market_name,
        "country_code": country_code,
        "screen_capacity_cap": screen_capacity_cap,
        "target_format_mix": target_format_mix,
        "opened_screen_count": 0,
        "status": "PROSPECT",
    }
    stamp_new(market)
    db.markets[market["id"]] = market
    return success_object(serialize_market(market), 201)


@bp.get("/v1/markets")
def list_markets():
    require_role("NetworkPlanner", "PlatformContractManager", "ReleaseScheduler", "BoxOfficeAnalyst")
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.markets.values()))
    status = request.args.get("status")
    if status:
        items = [m for m in items if m.get("status") == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_market(m) for m in page], total, limit, offset)


@bp.get("/v1/markets/<market_id>")
def get_market(market_id):
    require_role("NetworkPlanner", "PlatformContractManager", "ReleaseScheduler", "BoxOfficeAnalyst")
    m = get_market_or_404(market_id)
    return success_object(serialize_market(m))


@bp.get("/v1/markets/<market_id>/agreements")
def list_market_agreements(market_id):
    require_role("NetworkPlanner", "PlatformContractManager")
    m = get_market_or_404(market_id)
    limit, offset = parse_pagination()
    items = [a for a in db.agreements.values() if a.get("market_id") == m["id"]]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_agreement(a) for a in page], total, limit, offset)


def _transition(market_id, from_states, to_state, precond=None):
    require_role("NetworkPlanner")
    m = get_market_or_404(market_id)
    if m.get("status") not in from_states:
        raise conflict(ERR_INVALID_STATE,
                       f"Market in state {m.get('status')} cannot perform this transition")
    if precond:
        precond(m)
    m["status"] = to_state
    touch(m)
    return success_object(serialize_market(m))


@bp.post("/v1/markets/<market_id>/begin-evaluation")
def market_begin_evaluation(market_id):
    return _transition(market_id, {"PROSPECT"}, "EVALUATING")


@bp.post("/v1/markets/<market_id>/approve")
def market_approve(market_id):
    def check(m):
        if m.get("screen_capacity_cap", 0) <= 0:
            raise conflict(ERR_INVALID_STATE, "screen_capacity_cap must be > 0 to approve")
    return _transition(market_id, {"EVALUATING"}, "APPROVED", check)


@bp.post("/v1/markets/<market_id>/begin-build")
def market_begin_build(market_id):
    def check(m):
        for a in db.agreements.values():
            if a.get("market_id") == m["id"] and a.get("status") == "SIGNED":
                return
        raise conflict(ERR_NO_SIGNED_AGREEMENT, "No SIGNED agreement exists in this market")
    return _transition(market_id, {"APPROVED"}, "BUILDING", check)


@bp.post("/v1/markets/<market_id>/go-live")
def market_go_live(market_id):
    def check(m):
        count = 0
        for aud in db.auditoriums.values():
            if aud.get("status") != "OPERATING":
                continue
            agr = db.agreements.get(aud.get("agreement_id"))
            if agr and agr.get("market_id") == m["id"]:
                count += 1
        if count < 1:
            raise conflict(ERR_INVALID_STATE, "opened_screen_count must be >= 1 to go live")
    return _transition(market_id, {"BUILDING"}, "LIVE", check)


@bp.post("/v1/markets/<market_id>/abandon")
def market_abandon(market_id):
    require_role("NetworkPlanner")
    m = get_market_or_404(market_id)
    if m.get("status") not in ("EVALUATING", "BUILDING"):
        raise conflict(ERR_INVALID_STATE,
                       f"Market in state {m.get('status')} cannot be abandoned")
    was_building = m.get("status") == "BUILDING"
    m["status"] = "ABANDONED"
    touch(m)
    if was_building:
        for a in db.agreements.values():
            if a.get("market_id") == m["id"] and a.get("status") == "NEGOTIATING":
                a["status"] = "TERMINATED"
                touch(a)
    return success_object(serialize_market(m))
