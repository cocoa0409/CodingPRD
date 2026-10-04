"""Launch allocations: dealer requests against an open drop (with the credit
check), reads, and manual forfeiture."""
from flask import Blueprint, request

from auth import context, forbidden, require_roles
from calc import dealer_outstanding_balance, refresh_drop
from envelope import (
    get_body, new_entity, req_int, req_str, sort_created, success,
    success_list, touch,
)
from errors import fail
from serialize import ser_allocation
from store import DB, get_clock

bp = Blueprint("allocations", __name__)


def load_allocation(allocation_id):
    a = DB.allocations.get(allocation_id)
    if a is None:
        fail("ERR_ALLOCATION_NOT_FOUND", "no launch allocation with id %s" % allocation_id)
    return a


@bp.post("/drinkware/launch-allocations")
def create_allocation():
    uid, role = context()
    require_roles(role, ["Dealer"])
    body = get_body()
    dealer_id = req_str(body, "dealer_id")
    drop_id = req_str(body, "drop_id")
    requested_units = req_int(body, "requested_units", minimum=1)
    if dealer_id != uid:
        forbidden("dealer_id must equal the acting Dealer identity")
    dealer = DB.dealers.get(dealer_id)
    if dealer is None:
        fail("ERR_DEALER_NOT_FOUND", "no dealer with id %s" % dealer_id)
    drop = DB.drops.get(drop_id)
    if drop is None:
        fail("ERR_DROP_NOT_FOUND", "no colorway drop with id %s" % drop_id)
    refresh_drop(drop)
    if dealer["status"] != "AUTHORIZED":
        fail("ERR_DEALER_NOT_AUTHORIZED",
             "allocation requests require an AUTHORIZED dealer")
    if drop["status"] != "ALLOCATION_OPEN":
        fail("ERR_DROP_NOT_OPEN_FOR_ALLOCATION",
             "the drop is not open for allocation requests")
    if get_clock() >= drop["allocation_closes_at"]:
        fail("ERR_ALLOCATION_WINDOW_CLOSED",
             "allocation requests close at allocation_closes_at")
    for existing in DB.allocations.values():
        if (existing["dealer_id"] == dealer_id
                and existing["drop_id"] == drop_id
                and existing["status"] == "REQUESTED"):
            fail("ERR_DUPLICATE_ALLOCATION_REQUEST",
                 "the dealer already has a REQUESTED allocation on this drop")
    projected = (dealer_outstanding_balance(dealer_id)
                 + requested_units * drop["dealer_unit_price_cents"])
    if projected > dealer["credit_limit_cents"]:
        fail("ERR_CREDIT_LIMIT_EXCEEDED",
             "the request would push the dealer's outstanding balance above its credit limit")
    allocation = new_entity({
        "dealer_id": dealer_id,
        "drop_id": drop_id,
        "requested_units": requested_units,
        "unit_price_cents": drop["dealer_unit_price_cents"],
        "allocated_units": 0,
        "status": "REQUESTED",
        "forfeit_reason": None,
    })
    DB.allocations[allocation["id"]] = allocation
    # The request set changed; the drop's version guards it (OCC on lock).
    touch(drop)
    return success(ser_allocation(allocation), 201)


@bp.get("/drinkware/launch-allocations/<allocation_id>")
def get_allocation(allocation_id):
    uid, role = context()
    require_roles(role, ["Dealer", "PlatformAdmin", "ChannelManager"])
    allocation = load_allocation(allocation_id)
    if role == "Dealer" and allocation["dealer_id"] != uid:
        forbidden("Dealer role may read only its own allocations")
    return success(ser_allocation(allocation))


@bp.get("/drinkware/launch-allocations")
def list_allocations():
    uid, role = context()
    require_roles(role, ["Dealer", "PlatformAdmin", "ChannelManager"])
    dealer_id = request.args.get("dealer_id")
    drop_id = request.args.get("drop_id")
    status = request.args.get("status")
    if role == "Dealer":
        dealer_id = uid  # filter forced to the acting dealer
    items = sort_created(list(DB.allocations.values()))
    if dealer_id is not None:
        items = [a for a in items if a["dealer_id"] == dealer_id]
    if drop_id is not None:
        items = [a for a in items if a["drop_id"] == drop_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return success_list([ser_allocation(a) for a in items])


@bp.post("/drinkware/launch-allocations/<allocation_id>/forfeit")
def forfeit_allocation(allocation_id):
    uid, role = context()
    require_roles(role, ["Dealer", "ChannelManager"])
    allocation = load_allocation(allocation_id)
    if role == "Dealer" and allocation["dealer_id"] != uid:
        forbidden("Dealer role may forfeit only its own allocations")
    get_body()
    if allocation["status"] not in ("REQUESTED", "ALLOCATED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a REQUESTED or ALLOCATED allocation can be forfeited")
    drop = DB.drops.get(allocation["drop_id"])
    if drop is not None:
        refresh_drop(drop)
        if drop["status"] not in ("ANNOUNCED", "ALLOCATION_OPEN", "ALLOCATION_LOCKED"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "allocations on LIVE or CLOSED drops cannot be forfeited")
    allocation["status"] = "FORFEITED"
    allocation["forfeit_reason"] = "DEALER_CHOICE"
    touch(allocation)
    if drop is not None:
        touch(drop)
    return success(ser_allocation(allocation))
