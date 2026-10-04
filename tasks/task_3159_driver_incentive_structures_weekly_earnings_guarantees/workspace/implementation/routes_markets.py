"""Market endpoints."""
import uuid

from flask import Blueprint, request

import db
from errors import (
    err_budget_exceeded,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
    err_stale_market_version,
)
from middleware import require_roles
from response import success_list, success_object
from services import (
    get_market_or_404,
    iso_now,
    market_available,
    market_recompute,
    market_view,
    new_entity,
    paginate,
    require_int,
    require_list_of_str,
    require_str,
    touch,
)

bp = Blueprint("markets", __name__)

ALL_READ = ("PlatformAdmin", "IncentiveOps", "PaymentsOfficer", "FraudAnalyst", "Driver")
STAFF_READ = ("PlatformAdmin", "IncentiveOps", "PaymentsOfficer", "FraudAnalyst")


@bp.post("/markets")
@require_roles("PlatformAdmin")
def create_market(_user_id, _role):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    market_code = require_str(body.get("market_code"), "market_code")
    geo_cells = require_list_of_str(body.get("geo_cells"), "geo_cells")
    budget = require_int(body.get("incentive_budget_cents"), "incentive_budget_cents", minimum=0)
    m = new_entity(
        {
            "market_code": market_code,
            "geo_cells": list(geo_cells),
            "incentive_budget_cents": budget,
            "budget_spent_cents": 0,
            "budget_reserved_cents": 0,
            "status": "ACTIVE",
        }
    )
    db.markets[m["id"]] = m
    return success_object(market_view(m), 201)


@bp.get("/markets/<mid>")
@require_roles(*ALL_READ)
def get_market(mid, _user_id, _role):
    m = get_market_or_404(mid)
    return success_object(market_view(m))


@bp.get("/markets")
@require_roles(*STAFF_READ)
def list_markets(_user_id, _role):
    status = request.args.get("status")
    items = list(db.markets.values())
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([market_view(m) for m in page], limit, offset, total)


@bp.put("/markets/<mid>")
@require_roles("PlatformAdmin")
def update_market(mid, _user_id, _role):
    m = get_market_or_404(mid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    if "expected_market_version" not in body:
        raise err_invalid_request("expected_market_version is required")
    expected = require_int(body.get("expected_market_version"), "expected_market_version")
    new_budget = require_int(body.get("incentive_budget_cents"), "incentive_budget_cents", minimum=0)
    if expected != m["version"]:
        raise err_stale_market_version()
    if new_budget < m["budget_spent_cents"] + m["budget_reserved_cents"]:
        raise err_budget_exceeded(
            "New budget ceiling below committed spent + reserved"
        )
    m["incentive_budget_cents"] = new_budget
    touch(m)
    return success_object(market_view(m))


@bp.post("/markets/<mid>/freeze")
@require_roles("PlatformAdmin")
def freeze_market(mid, _user_id, _role):
    m = get_market_or_404(mid)
    if m["status"] != "ACTIVE":
        raise err_invalid_state("Market must be ACTIVE to freeze")
    m["status"] = "FROZEN"
    touch(m)
    for p in db.programs.values():
        if p["market_id"] == m["id"] and p["status"] in ("ACTIVE", "DRAFT"):
            p["status"] = "PAUSED"
            if p.get("program_type") == "GUARANTEE":
                p["promised_make_up_max_cents"] = 0
            touch(p)
    market_recompute(m, touch_it=True)
    return success_object(market_view(m))


@bp.post("/markets/<mid>/unfreeze")
@require_roles("PlatformAdmin")
def unfreeze_market(mid, _user_id, _role):
    m = get_market_or_404(mid)
    if m["status"] != "FROZEN":
        raise err_invalid_state("Market must be FROZEN to unfreeze")
    m["status"] = "ACTIVE"
    touch(m)
    # Programs stay PAUSED; recompute reserved from currently ACTIVE programs
    market_recompute(m, touch_it=True)
    return success_object(market_view(m))


@bp.post("/markets/<mid>/close")
@require_roles("PlatformAdmin")
def close_market(mid, _user_id, _role):
    m = get_market_or_404(mid)
    if m["status"] not in ("ACTIVE", "FROZEN"):
        raise err_invalid_state("Market must be ACTIVE or FROZEN to close")
    for p in db.programs.values():
        if p["market_id"] == m["id"] and p["status"] == "ACTIVE":
            raise err_invalid_state("Active programs remain in market")
    for s in db.settlements.values():
        prog = db.programs.get(s["program_id"])
        if prog and prog["market_id"] == m["id"] and s["status"] in ("DRAFT", "REOPENED"):
            raise err_invalid_state("Open settlements remain in market")
    m["status"] = "CLOSED"
    touch(m)
    for p in db.programs.values():
        if p["market_id"] == m["id"] and p["status"] in ("DRAFT", "PAUSED"):
            p["status"] = "RETIRED"
            if p.get("program_type") == "GUARANTEE":
                p["promised_make_up_max_cents"] = 0
            touch(p)
    for sf in db.shortfalls.values():
        if sf["market_id"] == m["id"] and sf["status"] == "OPEN":
            sf["status"] = "EXPIRED"
            touch(sf)
    market_recompute(m, touch_it=True)
    return success_object(market_view(m))


@bp.get("/markets/<mid>/supply-shortfalls")
@require_roles("PlatformAdmin", "IncentiveOps")
def list_market_shortfalls(mid, _user_id, _role):
    m = get_market_or_404(mid)
    status = request.args.get("status")
    items = [s for s in db.shortfalls.values() if s["market_id"] == m["id"]]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    from services import shortfall_view, touch_expiry

    for s in items:
        touch_expiry("shortfall", s)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([shortfall_view(s) for s in page], limit, offset, total)
