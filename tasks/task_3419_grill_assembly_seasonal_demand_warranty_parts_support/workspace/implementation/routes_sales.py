"""Sale recording (consumes allocations, clearance pricing), registration and
returns with their claim cascade. PRD §3.5."""

from flask import Blueprint, request

import clock
import derive
from auth import authenticate, check_ownership, require_role
from constants import ACCESSORY_TYPES
from errors import api_error, not_found, validation
from serialize import sale_out
from store import db, new_entity, touch
from util import as_int, as_list, get_body, ok, ok_list, paginate, require

bp = Blueprint("sales", __name__, url_prefix="/grillops")

READ_ROLES = ("PlannerAdmin", "ChannelRep", "ServiceAgent")
IN_FLIGHT_CLAIM_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "ESCALATED", "REOPENED")


def _sale_or_404(sale_id):
    sale = db.sales.get(sale_id)
    if sale is None:
        raise not_found("SALE")
    return sale


def _validate_accessories(raw):
    accessories = as_list(raw, "accessories")
    for item in accessories:
        if not isinstance(item, dict):
            raise validation("each accessory must be an object")
        if not isinstance(item.get("sku"), str) or not item.get("sku"):
            raise validation("accessory.sku is required")
        if item.get("accessory_type") not in ACCESSORY_TYPES:
            raise validation("accessory.accessory_type must be one of COVER, TOOLS, FUEL, OTHER")
        as_int(item.get("unit_price_cents"), "accessory.unit_price_cents")
    return accessories


@bp.post("/sales")
def create_sale():
    user_id, role = authenticate()
    require_role(role, ("ChannelRep",))
    data = get_body()
    # rung 3: body-carried references, left to right in input order
    season_id = require(data, "season_id")
    season = db.seasons.get(season_id)
    if season is None:
        raise not_found("SEASON")
    model_id = require(data, "model_id")
    model = db.models.get(model_id)
    if model is None:
        raise not_found("MODEL")
    channel_id = require(data, "channel_account_id")
    channel = db.channels.get(channel_id)
    if channel is None:
        raise not_found("CHANNEL")
    # rung 4: the acting ChannelRep must be the selling channel
    check_ownership(user_id, channel["id"])
    # rung 5: season posture gate
    if season["status"] not in ("IN_SEASON", "CLEARANCE"):
        raise api_error("ERR_SEASON_POSTURE_FORBIDDEN", "sales require the season to be IN_SEASON or CLEARANCE")
    # rung 6: body well-formedness
    quantity = as_int(require(data, "quantity"), "quantity")
    if quantity < 1:
        raise validation("quantity must be >= 1")
    serials = data.get("serials")
    if serials is not None:
        serials = as_list(serials, "serials")
        if len(serials) != quantity:
            raise validation("serials length must equal quantity")
        for serial in serials:
            if not isinstance(serial, str) or not serial:
                raise validation("each serial must be a non-empty string")
    accessories = _validate_accessories(data.get("accessories", []))
    proof = data.get("proof_of_purchase_token")
    if proof is not None and not isinstance(proof, str):
        raise validation("proof_of_purchase_token must be a string")
    # rung 7: model sellable + an active allocation for the tuple
    if model["status"] not in ("ACTIVE", "CLEARANCE_ELIGIBLE"):
        raise api_error("ERR_MODEL_NOT_SELLABLE", "sales require an ACTIVE or CLEARANCE_ELIGIBLE model")
    allocation = derive.find_active_allocation(season["id"], channel["id"], model["id"])
    if allocation is None:
        raise api_error("ERR_NO_ACTIVE_ALLOCATION", "no ACCEPTED or PARTIALLY_CONSUMED allocation exists for (season, channel, model)")
    # rung 9: serial uniqueness (global across sales), then remaining capacity
    if serials:
        wanted = set(serials)
        for other in db.sales.values():
            for existing in other["serials"]:
                if existing in wanted:
                    raise api_error("ERR_DUPLICATE_SERIAL", "serial %s already appears on another sale" % existing)
    if quantity > allocation["allocated_units"] - allocation["committed_units"]:
        raise api_error("ERR_ALLOCATION_CAPACITY_EXCEEDED", "quantity exceeds the allocation's remaining units")
    # pricing is computed, never taken from the client
    now = clock.now()
    if season["status"] == "CLEARANCE":
        unit_price = derive.calc_clearance_price(season, model, channel, now)
    else:
        unit_price = model["base_price_cents"]
    registered = proof is not None
    sale = new_entity({
        "season_id": season["id"],
        "model_id": model["id"],
        "channel_account_id": channel["id"],
        "quantity": quantity,
        "serials": list(serials) if serials else [],
        "accessories": accessories,
        "accessory_count": len(accessories),
        "has_cover": any(a["accessory_type"] == "COVER" for a in accessories),
        "has_tools": any(a["accessory_type"] == "TOOLS" for a in accessories),
        "has_fuel": any(a["accessory_type"] == "FUEL" for a in accessories),
        "unit_price_cents": unit_price,
        "proof_of_purchase_token": proof,
        "status": "REGISTERED" if registered else "SOLD",
        "sold_at": clock.iso_z(now),
        "registered_at": clock.iso_z(now) if registered else None,
    })
    db.sales[sale["id"]] = sale
    # consumption: first sale ACCEPTED -> PARTIALLY_CONSUMED; reaching equality
    # (in one step or gradually) -> CONSUMED
    allocation["committed_units"] += quantity
    if allocation["committed_units"] >= allocation["allocated_units"]:
        allocation["status"] = "CONSUMED"
    else:
        allocation["status"] = "PARTIALLY_CONSUMED"
    touch(allocation)
    derive.recompute_lots(season["id"], model["id"])
    derive.recompute_channel(channel)
    return ok(sale_out(sale), status=201)


@bp.get("/sales/<sale_id>")
def get_sale(sale_id):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    sale = _sale_or_404(sale_id)
    if role == "ChannelRep":
        check_ownership(user_id, sale["channel_account_id"])
    return ok(sale_out(sale))


@bp.get("/sales")
def list_sales():
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    items = list(db.sales.values())
    if role == "ChannelRep":
        items = [s for s in items if s["channel_account_id"] == user_id]
    for field in ("season_id", "model_id", "channel_account_id", "status"):
        raw = request.args.get(field)
        if raw is not None:
            items = [s for s in items if s.get(field) == raw]
    page, total, limit, offset = paginate(items)
    return ok_list([sale_out(s) for s in page], total, limit, offset)


def _return_effects(sale):
    """RETURN side effects: allocation un-commit, lot/channel recompute, and
    force-deny of in-flight claims. APPROVED / SETTLED claims are untouched."""
    quantity = sale["quantity"]
    allocation = derive.find_active_allocation(sale["season_id"], sale["channel_account_id"], sale["model_id"])
    if allocation is None:
        # the live allocation may have reached a terminal state since the sale;
        # fall back to the most recent terminal allocation that still carries
        # committed units for this tuple
        candidates = [
            a for a in db.allocations.values()
            if a["season_id"] == sale["season_id"]
            and a["channel_account_id"] == sale["channel_account_id"]
            and a["model_id"] == sale["model_id"]
            and a["status"] == "CONSUMED"
        ]
        if not candidates:
            candidates = [
                a for a in db.allocations.values()
                if a["season_id"] == sale["season_id"]
                and a["channel_account_id"] == sale["channel_account_id"]
                and a["model_id"] == sale["model_id"]
                and a["committed_units"] >= quantity
                and a["status"] in ("RELEASED", "EXPIRED", "SUPERSEDED")
            ]
        if candidates:
            allocation = max(candidates, key=lambda a: a["_seq"])
    if allocation is not None:
        allocation["committed_units"] = max(0, allocation["committed_units"] - quantity)
        if allocation["status"] == "CONSUMED" and allocation["committed_units"] < allocation["allocated_units"]:
            allocation["status"] = "PARTIALLY_CONSUMED"
        touch(allocation)
    derive.recompute_lots(sale["season_id"], sale["model_id"])
    channel = db.channels.get(sale["channel_account_id"])
    if channel is not None:
        derive.recompute_channel(channel)
    denied_stamp = clock.iso_z(clock.now())
    for claim in db.claims.values():
        if claim["sale_id"] == sale["id"] and claim["status"] in IN_FLIGHT_CLAIM_STATUSES:
            claim["status"] = "DENIED"
            claim["denied_at"] = denied_stamp
            touch(claim)


@bp.post("/sales/<sale_id>/transition")
def transition_sale(sale_id):
    user_id, role = authenticate()
    require_role(role, ("ChannelRep", "ServiceAgent"))
    sale = _sale_or_404(sale_id)
    # rung 4: ChannelRep is ownership-scoped; ServiceAgent is not
    if role == "ChannelRep":
        check_ownership(user_id, sale["channel_account_id"])
    data = get_body()
    action = require(data, "action")
    if action not in ("REGISTER", "RETURN"):
        raise validation("action must be REGISTER or RETURN")
    # rung 5: valid-from state
    if action == "REGISTER":
        if sale["status"] == "RETURNED":
            raise api_error("ERR_INVALID_STATE", "a RETURNED sale cannot be registered")
        if sale["status"] != "SOLD":
            raise api_error("ERR_INVALID_STATE", "only a SOLD sale can be registered")
        proof = data.get("proof_of_purchase_token")
        if not proof or not isinstance(proof, str):
            raise validation("proof_of_purchase_token is required for REGISTER")
        sale["status"] = "REGISTERED"
        sale["proof_of_purchase_token"] = proof
        sale["registered_at"] = clock.iso_z(clock.now())
        touch(sale)
    else:  # RETURN
        if sale["status"] == "RETURNED":
            raise api_error("ERR_SALE_RETURNED", "sale has already been returned")
        sale["status"] = "RETURNED"
        touch(sale)
        _return_effects(sale)
    return ok(sale_out(sale))
