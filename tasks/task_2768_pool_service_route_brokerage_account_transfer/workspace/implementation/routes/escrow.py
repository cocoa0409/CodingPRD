"""Escrow accounts: deposits in, holdback out. Created only by acceptance."""

from flask import Blueprint, request

from auth import begin, guard_deal, segregation_violation
from errors import ApiError
from responses import list_response, object_response, pagination
from serializers import escrow_json
from services import get_escrow
from store import ordered, store, touch
from validators import body, path_uuid, req_cents

bp = Blueprint("escrow", __name__)


def _deal_of(escrow):
    return store.deals.get(escrow["deal_id"])


@bp.get("/escrow-accounts/<identifier>")
def read_escrow(identifier):
    begin("Broker", "PlatformAdmin", "Seller", "Buyer", "EscrowAgent")
    existing = store.escrow_accounts.get(identifier)
    if existing is not None:
        deal = _deal_of(existing)
        if deal is not None:
            guard_deal(deal, store.route_listings.get(deal["listing_id"]))
    path_uuid(identifier)
    return object_response(escrow_json(get_escrow(identifier)))


@bp.get("/escrow-accounts")
def list_escrow():
    begin("Broker", "PlatformAdmin", "Seller", "Buyer", "EscrowAgent")
    limit, offset = pagination()
    filters = {key: request.args.get(key) for key in ("deal_id", "status")}

    def keep(row):
        for key, value in filters.items():
            if value is not None and row.get(key) != value:
                return False
        return True

    return list_response(ordered(store.escrow_accounts, keep), escrow_json, limit, offset)


@bp.post("/escrow-accounts/<identifier>/deposits")
def deposit(identifier):
    role, user_id = begin("EscrowAgent")
    data = body()
    amount = req_cents(data, "amount_cents")
    path_uuid(identifier)
    escrow = get_escrow(identifier)
    deal = _deal_of(escrow)

    if deal is not None and deal["status"] in ("TERMINATED", "GUARANTEE_CLOSED"):
        raise ApiError("ERR_DEAL_TERMINAL", "The deal has reached an absorbing status.")
    if escrow["status"] != "OPEN" or escrow["deposits_blocked"]:
        raise ApiError("ERR_ESCROW_NOT_OPEN",
                       "The escrow account is in the wrong status, or its deposit block is set.")
    if escrow["funded_amount_cents"] + amount > escrow["target_amount_cents"]:
        raise ApiError("ERR_ESCROW_OVERFUNDED",
                       "The deposit would push the escrow above its target.")

    if escrow["funded_by_user_id"] is None:
        escrow["funded_by_user_id"] = user_id
    escrow["funded_amount_cents"] += amount
    escrow["undisbursed_balance_cents"] += amount
    if escrow["funded_amount_cents"] == escrow["target_amount_cents"]:
        escrow["status"] = "FUNDED"
        if deal is not None and deal["status"] == "FINANCING_APPROVED":
            deal["status"] = "ESCROW_FUNDED"
            touch(deal)
    touch(escrow)
    return object_response(escrow_json(escrow), 201)


@bp.post("/escrow-accounts/<identifier>/holdback-releases")
def release_holdback(identifier):
    role, user_id = begin("EscrowAgent")
    existing = store.escrow_accounts.get(identifier)
    if existing is not None and existing["funded_by_user_id"] == user_id:
        segregation_violation()
    path_uuid(identifier)
    escrow = get_escrow(identifier)
    deal = _deal_of(escrow)

    # PRD §3.9 states the holdback release's preconditions as a PARTIALLY_RELEASED escrow
    # whose deal is CLOSED; it never names an absorbing-deal refusal on this endpoint, so
    # the escrow status check is the reported answer.
    if escrow["status"] != "PARTIALLY_RELEASED":
        raise ApiError("ERR_ESCROW_NOT_OPEN", "The escrow account is in the wrong status.")
    if deal is not None and deal["status"] != "CLOSED":
        raise ApiError("ERR_GUARANTEE_NOT_STARTED",
                       "A post-close operation was attempted on a deal that has not closed.")
    if (escrow["scheduled_holdback_release_utc"] is None
            or store.clock < escrow["scheduled_holdback_release_utc"]
            or escrow["holdback_release_blocked"]):
        raise ApiError("ERR_HOLDBACK_NOT_RELEASABLE",
                       "The holdback release is early, unscheduled, or blocked by an open "
                       "clawback.")

    escrow["disbursed_to_seller_cents"] += escrow["holdback_balance_cents"]
    escrow["holdback_balance_cents"] = 0
    escrow["status"] = "RELEASED"
    touch(escrow)
    if deal is not None:
        deal["status"] = "GUARANTEE_CLOSED"
        touch(deal)
    return object_response(escrow_json(escrow), 201)
