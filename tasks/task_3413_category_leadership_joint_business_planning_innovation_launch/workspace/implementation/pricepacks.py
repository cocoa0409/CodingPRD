"""PricePackDecision: channel pack proposals, ceiling per-unit pricing, and
retailer approval guarded by the channel-conflict pair (pairwise price gap
first, ECOMMERCE undercut second)."""

from flask import Blueprint, request

import validation as V
from auth import (
    ALL_ROLES,
    ROLE_MANUFACTURER_PLANNER,
    ROLE_RETAILER_BUYER,
    authenticate,
    authorize,
    scope_plan,
)
from calc import D, ceil_int
from constants import (
    CHANNELS,
    CHANNEL_PRICE_GAP_MAX_PCT,
    CLUB_PACK_MIN_UNITS,
    ECOMMERCE_UNDERCUT_MAX_PCT,
    PPD_DECISIONS,
    PPD_TERMINAL,
)
from envelope import success, success_list
from errors import err
from plans import plan_or_404
from storage import STORE, by_seq, new_id, public, stamp_new, touch

bp = Blueprint("pricepacks", __name__)


@bp.post("/jbp/plans/<plan_id>/price-pack-decisions")
def create_ppd(plan_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_MANUFACTURER_PLANNER])
    data = V.body()
    V.check_undeclared(data, {"channel", "pack_family", "pack_code", "unit_count", "list_price_cents"})
    channel = V.as_enum(V.require(data, "channel"), "channel", CHANNELS)
    pack_family = V.as_str(V.require(data, "pack_family"), "pack_family")
    pack_code = V.as_str(V.require(data, "pack_code"), "pack_code")
    unit_count = V.as_int(V.require(data, "unit_count"), "unit_count")
    if unit_count < 1:
        err("ERR_VALIDATION", "unit_count must be >= 1")
    list_price = V.as_int(V.require(data, "list_price_cents"), "list_price_cents")
    if list_price <= 0:
        err("ERR_VALIDATION", "list_price_cents must be > 0")
    plan = plan_or_404(plan_id)  # 6
    retailer = STORE["retailers"].get(plan["retailer_id"])
    if retailer is None or channel not in retailer["channels"]:
        err("ERR_VALIDATION", "channel is not operated by the plan's retailer")  # 4
    if channel == "CLUB" and unit_count < CLUB_PACK_MIN_UNITS:
        err("ERR_CLUB_PACK_TOO_SMALL", "CLUB packs require unit_count >= 12")  # 25
    ppu = -(-list_price // unit_count)  # ceil division, integer cents
    rec = {
        "id": new_id(),
        "plan_id": plan_id,
        "channel": channel,
        "pack_family": pack_family,
        "pack_code": pack_code,
        "unit_count": unit_count,
        "list_price_cents": list_price,
        "price_per_unit_cents": ppu,
        "status": "PROPOSED",
    }
    stamp_new(rec)
    STORE["ppds"][rec["id"]] = rec
    return success(public(rec), 201)


@bp.get("/jbp/plans/<plan_id>/price-pack-decisions")
def list_ppds(plan_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = V.pagination()
    plan = STORE["plans"].get(plan_id)
    scope_plan(uid, role, plan)
    if plan is None:
        err("ERR_PLAN_NOT_FOUND", "plan not found")
    items = [p for p in by_seq(STORE["ppds"].values()) if p["plan_id"] == plan_id]
    f_channel = request.args.get("channel")
    if f_channel is not None:
        items = [p for p in items if p["channel"] == f_channel]
    f_status = request.args.get("status")
    if f_status is not None:
        items = [p for p in items if p["status"] == f_status]
    f_family = request.args.get("pack_family")
    if f_family is not None:
        items = [p for p in items if p["pack_family"] == f_family]
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([public(p) for p in page], limit, offset, total)


@bp.post("/jbp/price-pack-decisions/<ppd_id>/decide")
def decide_ppd(ppd_id):
    uid, role = authenticate()
    authorize(role, [ROLE_RETAILER_BUYER])
    ppd = STORE["ppds"].get(ppd_id)
    plan = STORE["plans"].get(ppd["plan_id"]) if ppd is not None else None
    scope_plan(uid, role, plan)  # 3
    data = V.body()
    V.check_undeclared(data, {"decision"})
    decision = V.as_enum(V.require(data, "decision"), "decision", PPD_DECISIONS)  # 4
    if ppd is None:
        err("ERR_RESOURCE_NOT_FOUND", "price-pack decision not found")  # 6
    if ppd["status"] in PPD_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "price-pack decision is terminal")  # 8
    if ppd["status"] != "PROPOSED":
        err("ERR_INVALID_STATE", "only a PROPOSED decision can be decided")  # 7
    if decision == "APPROVE":
        approved = [
            p
            for p in STORE["ppds"].values()
            if p["plan_id"] == ppd["plan_id"] and p["status"] == "APPROVED" and p["id"] != ppd_id
        ]
        # priority 26, rule 1: pairwise price gap (exactly 15 passes)
        new_ppu = ppd["price_per_unit_cents"]
        for other in approved:
            a, b = new_ppu, other["price_per_unit_cents"]
            gap = D(abs(a - b)) / D(min(a, b)) * 100
            if gap > D(CHANNEL_PRICE_GAP_MAX_PCT):
                err("ERR_CHANNEL_CONFLICT", "price-per-unit gap exceeds 15% against an APPROVED decision")
        # priority 26, rule 2: ECOMMERCE undercut floor
        if ppd["channel"] == "ECOMMERCE":
            floors = [p["price_per_unit_cents"] for p in approved if p["channel"] != "ECOMMERCE"]
            if floors:
                floor = ceil_int(D(min(floors)) * D(100 - ECOMMERCE_UNDERCUT_MAX_PCT) / 100)
                if new_ppu < floor:
                    err("ERR_ECOMMERCE_UNDERCUT", "ECOMMERCE ppu below the 10% undercut floor")
        ppd["status"] = "APPROVED"
    else:
        ppd["status"] = "REJECTED"
    touch(ppd)
    return success(public(ppd))
