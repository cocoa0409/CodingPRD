"""Clawback settlements: snapshot, proposal cycle and execution."""

from flask import Blueprint, request

from auth import begin, guard_deal, guard_listing, segregation_violation
from calc import REMEDY_BASES, settlement_figures
from errors import ApiError
from responses import list_response, object_response, pagination
from serializers import settlement_json
from services import escrow_of_deal, get_deal, get_escrow, get_settlement, live_ledger
from store import new_record, ordered, store, touch
from validators import bad, body, path_uuid, req_cents, req_enum, req_id, req_str

bp = Blueprint("settlements", __name__)

LIVE_STATUSES = ("DRAFT", "PROPOSED", "DISPUTED")


def _escrow_for(settlement, deal):
    if settlement["escrow_id"] is not None:
        return store.escrow_accounts.get(settlement["escrow_id"])
    return escrow_of_deal(deal)


def _not_proposed(settlement, what):
    raise ApiError("ERR_SETTLEMENT_NOT_PROPOSED",
                   "A %s settlement may not be %s." % (settlement["status"], what))


@bp.post("/clawback-settlements")
def create_settlement():
    begin("Broker")
    data = body()
    deal_id = req_id(data, "deal_id")
    remedy_basis = req_enum(data, "remedy_basis", REMEDY_BASES)
    escrow_id = req_id(data, "escrow_id", required=False)

    deal = get_deal(deal_id)
    escrow = get_escrow(escrow_id) if escrow_id is not None else None

    if deal["status"] == "TERMINATED":
        raise ApiError("ERR_DEAL_TERMINAL", "The deal has reached an absorbing status.")
    if deal["status"] not in ("CLOSED", "GUARANTEE_CLOSED"):
        raise ApiError("ERR_GUARANTEE_NOT_STARTED",
                       "A post-close operation was attempted on a deal that has not closed.")
    if escrow is not None and escrow["deal_id"] != deal_id:
        raise ApiError("ERR_ESCROW_DEAL_MISMATCH",
                       "The escrow account named does not belong to the deal being processed.")
    if deal["clawback_status"] != "CLAWBACK_TRIGGERED":
        raise ApiError("ERR_NO_CLAWBACK_DUE",
                       "The deal's retention ledger has not triggered a clawback.")
    for other in store.clawback_settlements.values():
        if other["deal_id"] == deal_id and other["status"] in LIVE_STATUSES:
            raise ApiError("ERR_DUPLICATE_ACTIVE_SETTLEMENT",
                           "The deal already has a live settlement.")

    record = new_record()
    record.update({
        "deal_id": deal_id,
        "escrow_id": escrow_id,
        "remedy_basis": remedy_basis,
        "status": "DRAFT",
        "computed_from_clock_utc": store.clock,
        "dispute_reason_code": None,
        "settled_at_utc": None,
    })
    figures = settlement_figures(live_ledger(deal), deal,
                                escrow if escrow is not None else escrow_of_deal(deal),
                                remedy_basis)
    record.update(figures)
    store.clawback_settlements[record["id"]] = record
    return object_response(settlement_json(record), 201)


@bp.get("/clawback-settlements/<identifier>")
def read_settlement(identifier):
    begin("Broker", "PlatformAdmin", "Seller", "Buyer", "EscrowAgent")
    existing = store.clawback_settlements.get(identifier)
    if existing is not None:
        deal = store.deals.get(existing["deal_id"])
        if deal is not None:
            guard_deal(deal, store.route_listings.get(deal["listing_id"]))
    path_uuid(identifier)
    return object_response(settlement_json(get_settlement(identifier)))


@bp.get("/clawback-settlements")
def list_settlements():
    begin("Broker", "PlatformAdmin", "Seller", "Buyer", "EscrowAgent")
    limit, offset = pagination()
    filters = {key: request.args.get(key) for key in ("deal_id", "remedy_basis", "status")}

    def keep(row):
        for key, value in filters.items():
            if value is not None and row.get(key) != value:
                return False
        return True

    return list_response(ordered(store.clawback_settlements, keep), settlement_json, limit, offset)


@bp.post("/clawback-settlements/<identifier>/propose")
def propose_settlement(identifier):
    role, user_id = begin("Broker")
    existing = store.clawback_settlements.get(identifier)
    if existing is not None:
        for event in store.attrition_events.values():
            if (event["deal_id"] == existing["deal_id"]
                    and event.get("_recorded_by_user_id") == user_id):
                segregation_violation()
    data = body()
    submitted = req_cents(data, "adjustment_cents")
    if submitted <= 0:
        bad("Field 'adjustment_cents' must be strictly positive.")
    path_uuid(identifier)
    settlement = get_settlement(identifier)
    deal = get_deal(settlement["deal_id"])

    if settlement["status"] not in ("DRAFT", "DISPUTED"):
        _not_proposed(settlement, "proposed")
    if deal["clawback_status"] != "CLAWBACK_TRIGGERED":
        raise ApiError("ERR_NO_CLAWBACK_DUE",
                       "The deal's retention ledger has not triggered a clawback.")

    figures = settlement_figures(live_ledger(deal), deal, _escrow_for(settlement, deal),
                                 settlement["remedy_basis"])
    if submitted != figures["adjustment_cents"]:
        raise ApiError("ERR_SETTLEMENT_AMOUNT_MISMATCH",
                       "The submitted adjustment is not the figure the formula produces.")

    settlement.update(figures)
    settlement["computed_from_clock_utc"] = store.clock
    settlement["status"] = "PROPOSED"
    touch(settlement)
    return object_response(settlement_json(settlement))


@bp.post("/clawback-settlements/<identifier>/dispute")
def dispute_settlement(identifier):
    begin("Seller")
    existing = store.clawback_settlements.get(identifier)
    if existing is not None:
        deal = store.deals.get(existing["deal_id"])
        if deal is not None:
            guard_listing(store.route_listings.get(deal["listing_id"]))
    data = body()
    reason = req_str(data, "dispute_reason_code", min_len=1)
    path_uuid(identifier)
    settlement = get_settlement(identifier)

    if settlement["status"] != "PROPOSED":
        _not_proposed(settlement, "disputed")

    settlement["status"] = "DISPUTED"
    settlement["dispute_reason_code"] = reason
    touch(settlement)
    return object_response(settlement_json(settlement))


@bp.post("/clawback-settlements/<identifier>/settle")
def settle_settlement(identifier):
    role, user_id = begin("EscrowAgent")
    existing = store.clawback_settlements.get(identifier)
    if existing is not None:
        deal = store.deals.get(existing["deal_id"])
        escrow = _escrow_for(existing, deal) if deal is not None else None
        if escrow is not None and escrow["funded_by_user_id"] == user_id:
            segregation_violation()
    data = body()
    submitted = req_cents(data, "adjustment_cents")
    path_uuid(identifier)
    settlement = get_settlement(identifier)
    deal = get_deal(settlement["deal_id"])
    escrow = _escrow_for(settlement, deal)

    if escrow is not None and escrow["deal_id"] != deal["id"]:
        raise ApiError("ERR_ESCROW_DEAL_MISMATCH",
                       "The escrow account resolved does not belong to the deal being processed.")
    if settlement["status"] != "PROPOSED":
        _not_proposed(settlement, "settled")
    if escrow is None or escrow["status"] != "PARTIALLY_RELEASED":
        raise ApiError("ERR_ESCROW_NOT_OPEN", "The escrow account is in the wrong status.")
    if submitted != settlement["adjustment_cents"]:
        raise ApiError("ERR_SETTLEMENT_AMOUNT_MISMATCH",
                       "The submitted adjustment is not the figure the settlement was proposed at.")

    escrow["disbursed_to_buyer_cents"] += settlement["from_holdback_cents"]
    escrow["disbursed_to_seller_cents"] += settlement["holdback_release_to_seller_cents"]
    escrow["holdback_balance_cents"] = 0
    escrow["status"] = "RELEASED"
    touch(escrow)

    deal["note_principal_cents"] -= settlement["from_note_principal_cents"]
    deal["clawback_status"] = "SETTLED"
    deal["status"] = "GUARANTEE_CLOSED"
    touch(deal)

    settlement["status"] = "SETTLED"
    settlement["settled_at_utc"] = store.clock
    touch(settlement)
    return object_response(settlement_json(settlement))
