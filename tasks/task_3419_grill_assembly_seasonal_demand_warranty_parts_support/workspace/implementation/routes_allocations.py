"""Allocation offers: create (OCC + supersede + capacity + credit), read, list,
and the respond surface (ACCEPT / DECLINE / RELEASE / REVISE). PRD §3.4."""

from flask import Blueprint, request

import clock
import derive
from auth import authenticate, check_action_role, check_ownership, require_role
from errors import api_error, not_found, validation
from serialize import allocation_out
from store import db, new_entity, touch
from util import get_body, ok, ok_list, paginate, req_int, require

bp = Blueprint("allocations", __name__, url_prefix="/grillops")

ACTION_ROLES = {
    "ACCEPT": ("ChannelRep",),
    "DECLINE": ("ChannelRep",),
    "RELEASE": ("ChannelRep",),
    "REVISE": ("PlannerAdmin",),
}
RESPOND_VALID_FROM = {
    "ACCEPT": ("OFFERED",),
    "DECLINE": ("OFFERED",),
    "REVISE": ("OFFERED",),
    "RELEASE": ("ACCEPTED", "PARTIALLY_CONSUMED"),
}


def _allocation_or_404(allocation_id):
    allocation = db.allocations.get(allocation_id)
    if allocation is None:
        raise not_found("ALLOCATION")
    return allocation


def _check_credit(channel, model, new_units):
    """calc_allocation_credit: exposure + new*price <= limit; equality passes."""
    exposure = derive.channel_exposure(channel["id"])
    if exposure + new_units * model["base_price_cents"] > channel["credit_limit_cents"]:
        raise api_error("ERR_CREDIT_LIMIT_EXCEEDED", "channel credit limit would be exceeded")


@bp.post("/allocations")
def create_allocation():
    _, role = authenticate()
    require_role(role, ("PlannerAdmin",))
    data = get_body()
    # rung 3: body-carried references resolve left to right in input order
    season_id = require(data, "season_id")
    season = db.seasons.get(season_id)
    if season is None:
        raise not_found("SEASON")
    channel_id = require(data, "channel_account_id")
    channel = db.channels.get(channel_id)
    if channel is None:
        raise not_found("CHANNEL")
    model_id = require(data, "model_id")
    model = db.models.get(model_id)
    if model is None:
        raise not_found("MODEL")
    # rung 5: season posture gate
    if season["status"] != "ALLOCATION":
        raise api_error("ERR_SEASON_POSTURE_FORBIDDEN", "allocation offers require the season to be in ALLOCATION")
    # rung 6: body well-formedness (expected_season_version is non-optional, §2.7)
    allocated_units = req_int(data, "allocated_units")
    if allocated_units < 1:
        raise validation("allocated_units must be >= 1")
    expected_season_version = require(data, "expected_season_version")
    # OCC (PRD §2.7 rule 1)
    if expected_season_version != season["version"]:
        raise api_error("ERR_STALE_VERSION", "expected_season_version does not match the season's current version")
    # rung 7: model must be ACTIVE for allocation offers
    if model["status"] != "ACTIVE":
        raise api_error("ERR_MODEL_NOT_SELLABLE", "allocation offers require an ACTIVE model")
    # same-tuple supersession: a live allocation collapses BEFORE capacity check
    live = derive.find_live_allocation(season["id"], channel["id"], model["id"])
    if live is not None:
        live["allocated_units"] = live["committed_units"]
        live["status"] = "SUPERSEDED"
        touch(live)
        derive.recompute_lots(season["id"], model["id"])
        derive.recompute_channel(channel)
    # rung 9: lot capacity — exact fit passes
    if allocated_units > derive.lot_pool_available(season["id"], model["id"]):
        raise api_error("ERR_ALLOCATION_CAPACITY_EXCEEDED", "allocated_units exceeds the lot's units_available")
    # rung 10: credit limit, always last
    _check_credit(channel, model, allocated_units)
    allocation = new_entity({
        "season_id": season["id"],
        "channel_account_id": channel["id"],
        "model_id": model["id"],
        "allocated_units": allocated_units,
        "committed_units": 0,
        "status": "OFFERED",
        "offered_at": clock.iso_z(clock.now()),
    })
    db.allocations[allocation["id"]] = allocation
    # every offer created against a season bumps the season's version (OCC anchor)
    touch(season)
    derive.recompute_lots(season["id"], model["id"])
    derive.recompute_channel(channel)
    return ok(allocation_out(allocation), status=201)


@bp.get("/allocations/<allocation_id>")
def get_allocation(allocation_id):
    user_id, role = authenticate()
    require_role(role, ("PlannerAdmin", "ChannelRep"))
    allocation = _allocation_or_404(allocation_id)
    if role == "ChannelRep":
        check_ownership(user_id, allocation["channel_account_id"])
    return ok(allocation_out(allocation))


@bp.get("/allocations")
def list_allocations():
    user_id, role = authenticate()
    require_role(role, ("PlannerAdmin", "ChannelRep"))
    items = list(db.allocations.values())
    if role == "ChannelRep":
        items = [a for a in items if a["channel_account_id"] == user_id]
    for field in ("season_id", "channel_account_id", "model_id", "status"):
        raw = request.args.get(field)
        if raw is not None:
            items = [a for a in items if a.get(field) == raw]
    page, total, limit, offset = paginate(items)
    return ok_list([allocation_out(a) for a in page], total, limit, offset)


@bp.post("/allocations/<allocation_id>/respond")
def respond_allocation(allocation_id):
    user_id, role = authenticate()
    require_role(role, ("PlannerAdmin", "ChannelRep"))
    allocation = _allocation_or_404(allocation_id)
    data = get_body()
    action = data.get("action")
    # rung 2 (action level) for known actions
    check_action_role(role, action, ACTION_ROLES)
    # rung 4: ChannelRep may only touch their own allocation
    if role == "ChannelRep":
        check_ownership(user_id, allocation["channel_account_id"])
    # rung 6: action is a required enum field
    if action is None:
        raise validation("action is required")
    if action not in ACTION_ROLES:
        raise validation("action must be one of ACCEPT, DECLINE, RELEASE, REVISE")
    # rung 5: valid-from state for this action
    if allocation["status"] not in RESPOND_VALID_FROM[action]:
        raise api_error(
            "ERR_ALLOCATION_NOT_ACTIONABLE",
            "action %s is not available from status %s" % (action, allocation["status"]),
        )
    # rung 6: expected_allocation_version is non-optional (§2.7)
    expected_version = require(data, "expected_allocation_version")
    if action == "REVISE":
        new_units = req_int(data, "allocated_units")
        if new_units < 1:
            raise validation("allocated_units must be >= 1")
    # OCC (PRD §2.7 rule 2)
    if expected_version != allocation["version"]:
        raise api_error("ERR_STALE_VERSION", "expected_allocation_version does not match the allocation's current version")

    season = db.seasons.get(allocation["season_id"])
    channel = db.channels.get(allocation["channel_account_id"])
    model = db.models.get(allocation["model_id"])

    if action == "ACCEPT":
        allocation["status"] = "ACCEPTED"
        touch(allocation)
        if channel is not None:
            derive.recompute_channel(channel)
    elif action == "DECLINE":
        allocation["status"] = "DECLINED"
        allocation["allocated_units"] = 0
        touch(allocation)
        derive.recompute_lots(allocation["season_id"], allocation["model_id"])
        if channel is not None:
            derive.recompute_channel(channel)
    elif action == "RELEASE":
        allocation["allocated_units"] = allocation["committed_units"]
        allocation["status"] = "RELEASED"
        touch(allocation)
        derive.recompute_lots(allocation["season_id"], allocation["model_id"])
        if channel is not None:
            derive.recompute_channel(channel)
    elif action == "REVISE":
        # recapture the current offer first, then re-run capacity and credit
        available = derive.lot_pool_available(allocation["season_id"], allocation["model_id"])
        available += allocation["allocated_units"] - allocation["committed_units"]
        if new_units > available:
            raise api_error("ERR_ALLOCATION_CAPACITY_EXCEEDED", "revised allocated_units exceeds the lot's units_available")
        _check_credit(channel, model, new_units)
        allocation["allocated_units"] = new_units
        touch(allocation)
        derive.recompute_lots(allocation["season_id"], allocation["model_id"])
        if channel is not None:
            derive.recompute_channel(channel)
    return ok(allocation_out(allocation))
