"""The negotiation cycle, acceptance fan-out, sign-off, closing and abandonment."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from auth import begin, guard_buyer_id, guard_deal, guard_listing, segregation_violation
from calc import (FINANCING_TYPES, REPLACEMENT_GRACE_DAYS, add_days, allowance_for,
                  clawback_cap_for, commission_for, fmt_date, holdback_for, minimum_down_payment,
                  verified_mrr_floor)
from errors import ApiError
from responses import list_response, object_response, pagination
from serializers import deal_json
from services import (escrow_of_deal, get_buyer, get_deal, get_listing, get_valuation,
                      live_valuation, permits_cleared, profile_for_state, recompute_listing,
                      transfers_of_deal)
from store import new_record, ordered, store, touch
from validators import body, path_uuid, req_cents, req_enum, req_id, req_int, req_str

bp = Blueprint("deals", __name__)

TERMINAL_STATUSES = ("TERMINATED", "GUARANTEE_CLOSED")
HOLDING_STATUSES = ("ACCEPTED", "DILIGENCE_CLEARED", "FINANCING_APPROVED", "ESCROW_FUNDED",
                    "REPRICE_REQUIRED")


def _terminal(deal):
    raise ApiError("ERR_DEAL_TERMINAL", "The deal has reached an absorbing status.")


def _invalid(deal, what):
    raise ApiError("ERR_INVALID_DEAL_TRANSITION",
                   "A %s deal may not %s." % (deal["status"], what))


def _gate(deal, allowed, what):
    """Transition validity, then the terminal bar.

    PRD §3.5 pins acceptance's order as "transition validity, then the repricing
    lockout", and every endpoint that refuses `REPRICE_REQUIRED` also fails to declare
    that transition for the status — so the repricing lockout is structurally masked by
    the transition check and `ERR_REPRICE_REQUIRED` is never the reported answer.
    """
    status = deal["status"]
    if status in allowed:
        return
    if status in TERMINAL_STATUSES:
        _terminal(deal)
    _invalid(deal, what)


def _prequal(buyer, price):
    if price > buyer["prequalified_amount_cents"]:
        raise ApiError("ERR_BUYER_PREQUAL_EXCEEDED",
                       "The price on the table exceeds the buyer's prequalified ceiling.")


def _split(price, down, note):
    if down + note != price:
        raise ApiError("ERR_FINANCING_SPLIT_MISMATCH",
                       "Cash down plus carried note does not equal the price.")


def _seller_standing(listing):
    seller = store.sellers.get(listing["seller_id"])
    if seller is not None and seller["status"] == "SUSPENDED":
        raise ApiError("ERR_SELLER_SUSPENDED", "The listing's seller is suspended.")


@bp.post("/deals")
def create_deal():
    begin("Buyer", "Broker")
    data = body()
    if isinstance(data.get("buyer_id"), str):
        guard_buyer_id(data["buyer_id"])

    listing_id = req_id(data, "listing_id")
    buyer_id = req_id(data, "buyer_id")
    price = req_cents(data, "offer_price_cents")
    financing_type = req_enum(data, "financing_type", FINANCING_TYPES)
    down = req_cents(data, "down_payment_cents")
    note = req_cents(data, "note_principal_cents")
    days = req_int(data, "retention_guarantee_days", minimum=30, maximum=365)

    listing = get_listing(listing_id)
    buyer = get_buyer(buyer_id)

    if listing["status"] != "LISTED":
        raise ApiError("ERR_LISTING_NOT_LISTED", "A deal may only be opened against a LISTED route.")
    if buyer["qualification_status"] != "APPROVED":
        raise ApiError("ERR_BUYER_NOT_QUALIFIED",
                       "The deal's buyer has not been qualified by the brokerage.")
    _prequal(buyer, price)
    _split(price, down, note)

    record = new_record()
    record.update({
        "listing_id": listing_id,
        "buyer_id": buyer_id,
        "offer_round": 1,
        "current_offer_price_cents": price,
        "financing_type": financing_type,
        "down_payment_cents": down,
        "note_principal_cents": note,
        "lender_name": None,
        "approved_amount_cents": None,
        "retention_guarantee_days": days,
        "status": "OFFER_SUBMITTED",
        "clawback_status": "NOT_APPLICABLE",
        "accepted_on": None,
        "closed_at_utc": None,
        "guarantee_start_utc": None,
        "guarantee_end_utc": None,
        "replacement_deadline_utc": None,
        "holdback_release_utc": None,
        "effective_multiple_at_close": None,
        "commission_cents": None,
        "holdback_cents": None,
        "escrow_target_amount_cents": None,
        "clawback_cap_cents": None,
        "guaranteed_mrr_cents": None,
        "attrited_mrr_cents": 0,
        "retained_mrr_cents": None,
        "replacement_mrr_cents": 0,
        "net_attrition_mrr_cents": 0,
        "allowance_mrr_cents": None,
        "attrition_pct": Decimal("0.0000"),
        "non_solicitation_executed_on": None,
        "non_solicitation_end_date": None,
        "repricing_reason_code": None,
        "termination_reason_code": None,
    })
    store.deals[record["id"]] = record
    return object_response(deal_json(record), 201)


@bp.get("/deals/<identifier>")
def read_deal(identifier):
    begin("Broker", "PlatformAdmin", "Seller", "Buyer")
    existing = store.deals.get(identifier)
    if existing is not None:
        guard_deal(existing, store.route_listings.get(existing["listing_id"]))
    path_uuid(identifier)
    return object_response(deal_json(get_deal(identifier)))


@bp.get("/deals")
def list_deals():
    begin("Broker", "PlatformAdmin", "Seller", "Buyer")
    limit, offset = pagination()
    filters = {key: request.args.get(key) for key in
               ("listing_id", "buyer_id", "status", "clawback_status", "financing_type")}

    def keep(row):
        for key, value in filters.items():
            if value is not None and row.get(key) != value:
                return False
        return True

    return list_response(ordered(store.deals, keep), deal_json, limit, offset)


@bp.post("/deals/<identifier>/counter-offers")
def counter_offer(identifier):
    begin("Seller")
    existing = store.deals.get(identifier)
    if existing is not None:
        guard_listing(store.route_listings.get(existing["listing_id"]))
    data = body()
    price = req_cents(data, "counter_price_cents")
    path_uuid(identifier)
    deal = get_deal(identifier)

    _gate(deal, ("OFFER_SUBMITTED",), "be countered")
    _prequal(get_buyer(deal["buyer_id"]), price)
    if price <= deal["current_offer_price_cents"]:
        raise ApiError("ERR_COUNTER_NOT_IMPROVED",
                       "A seller's counter must be strictly greater than the standing offer.")

    deal["current_offer_price_cents"] = price
    deal["offer_round"] += 1
    deal["status"] = "COUNTERED"
    touch(deal)
    return object_response(deal_json(deal))


@bp.post("/deals/<identifier>/offers")
def submit_offer(identifier):
    begin("Buyer")
    existing = store.deals.get(identifier)
    if existing is not None:
        guard_buyer_id(existing["buyer_id"])
    data = body()
    price = req_cents(data, "offer_price_cents")
    down = req_cents(data, "down_payment_cents")
    note = req_cents(data, "note_principal_cents")
    path_uuid(identifier)
    deal = get_deal(identifier)

    _gate(deal, ("COUNTERED", "REPRICE_REQUIRED"), "be re-offered")
    repricing = deal["status"] == "REPRICE_REQUIRED"
    _prequal(get_buyer(deal["buyer_id"]), price)
    if not repricing and price >= deal["current_offer_price_cents"]:
        raise ApiError("ERR_COUNTER_NOT_IMPROVED",
                       "A buyer's re-offer must be strictly less than the standing offer.")
    _split(price, down, note)

    deal["current_offer_price_cents"] = price
    deal["down_payment_cents"] = down
    deal["note_principal_cents"] = note
    deal["offer_round"] += 1
    deal["status"] = "OFFER_SUBMITTED"
    if repricing:
        deal["repricing_reason_code"] = None
        escrow = escrow_of_deal(deal)
        if escrow is not None:
            escrow["deposits_blocked"] = False
            escrow["target_amount_cents"] = 0
            touch(escrow)
        listing = store.route_listings.get(deal["listing_id"])
        if listing is not None and listing["status"] == "UNDER_CONTRACT":
            listing["status"] = "LISTED"
            touch(listing)
    touch(deal)
    return object_response(deal_json(deal))


@bp.post("/deals/<identifier>/accept")
def accept_deal(identifier):
    begin("Seller")
    existing = store.deals.get(identifier)
    if existing is not None:
        guard_listing(store.route_listings.get(existing["listing_id"]))
    data = body()
    days = req_int(data, "retention_guarantee_days", minimum=30, maximum=365)
    path_uuid(identifier)
    deal = get_deal(identifier)
    listing = get_listing(deal["listing_id"])

    _gate(deal, ("OFFER_SUBMITTED",), "be accepted")
    buyer = get_buyer(deal["buyer_id"])
    if buyer["qualification_status"] != "APPROVED":
        raise ApiError("ERR_BUYER_NOT_QUALIFIED",
                       "The deal's buyer has not been qualified by the brokerage.")
    if days < 60 or days > 365:
        raise ApiError("ERR_COVENANT_TERMS_INSUFFICIENT",
                       "The retention guarantee offered at acceptance is too short.")
    price = deal["current_offer_price_cents"]
    if deal["down_payment_cents"] < minimum_down_payment(price, deal["financing_type"]):
        raise ApiError("ERR_DOWN_PAYMENT_INSUFFICIENT",
                       "The cash down payment is below the minimum the financing type requires.")
    _seller_standing(listing)
    _split(price, deal["down_payment_cents"], deal["note_principal_cents"])

    accepted_on = fmt_date(store.clock.date())
    holdback = holdback_for(price)
    deal["status"] = "ACCEPTED"
    deal["accepted_on"] = accepted_on
    deal["retention_guarantee_days"] = days
    deal["holdback_cents"] = holdback
    deal["escrow_target_amount_cents"] = deal["down_payment_cents"] + holdback
    deal["non_solicitation_executed_on"] = accepted_on
    deal["non_solicitation_end_date"] = fmt_date(add_days(store.clock.date(), days))

    # Exactly one escrow account exists per deal (PRD 3.5). A deal that was
    # repriced and re-accepted keeps the same escrow row: the re-offer zeroed its
    # target "until a fresh acceptance sets it again".
    escrow = escrow_of_deal(deal)
    if escrow is None:
        escrow = new_record()
        escrow.update({
            "deal_id": deal["id"],
            "target_amount_cents": deal["escrow_target_amount_cents"],
            "funded_amount_cents": 0,
            "holdback_amount_cents": holdback,
            "holdback_balance_cents": 0,
            "undisbursed_balance_cents": 0,
            "disbursed_to_broker_cents": 0,
            "disbursed_to_seller_cents": 0,
            "disbursed_to_buyer_cents": 0,
            "status": "OPEN",
            "funded_by_user_id": None,
            "deposits_blocked": False,
            "holdback_release_blocked": False,
            "scheduled_holdback_release_utc": None,
        })
        store.escrow_accounts[escrow["id"]] = escrow
    else:
        escrow["target_amount_cents"] = deal["escrow_target_amount_cents"]
        escrow["holdback_amount_cents"] = holdback
        escrow["deposits_blocked"] = False
        if escrow["status"] == "FUNDED" and escrow["funded_amount_cents"] < escrow["target_amount_cents"]:
            escrow["status"] = "OPEN"
        touch(escrow)

    profile = profile_for_state(listing["state_code"])
    if profile is not None:
        held = set()
        for row in transfers_of_deal(deal["id"]):
            if row["status"] != "CANCELLED":
                held.add(row["permit_type"])
        for permit_type in profile["required_permit_types"]:
            if permit_type in held:
                continue
            transfer = new_record()
            transfer.update({
                "deal_id": deal["id"],
                "state_profile_id": profile["id"],
                "permit_type": permit_type,
                "status": "NOT_STARTED",
                "applied_on": None,
                "processing_window_end": None,
                "decided_on": None,
                "denial_reason_code": None,
                "attempt_count": 0,
                "waiver_basis": None,
            })
            store.license_transfers[transfer["id"]] = transfer

    listing["status"] = "UNDER_CONTRACT"
    touch(listing)
    for other in ordered(store.deals, lambda d: d["listing_id"] == listing["id"]):
        if other["id"] == deal["id"]:
            continue
        if other["status"] in ("OFFER_SUBMITTED", "COUNTERED", "REPRICE_REQUIRED"):
            other["status"] = "TERMINATED"
            other["termination_reason_code"] = "COMPETING_OFFER_ACCEPTED"
            touch(other)
    touch(deal)
    return object_response(deal_json(deal))


@bp.post("/deals/<identifier>/clear-diligence")
def clear_diligence(identifier):
    role, user_id = begin("Broker")
    existing = store.deals.get(identifier)
    if existing is not None:
        for account in store.service_accounts.values():
            if (account["listing_id"] == existing["listing_id"]
                    and account.get("verified_by_user_id") == user_id):
                segregation_violation()
    data = body()
    valuation_id = req_id(data, "valuation_id")
    path_uuid(identifier)
    deal = get_deal(identifier)
    valuation = get_valuation(valuation_id)
    listing = get_listing(deal["listing_id"])

    _gate(deal, ("ACCEPTED",), "clear diligence")

    if (valuation["listing_id"] != deal["listing_id"] or valuation["basis"] != "VERIFIED_BASIS"
            or valuation["is_superseded"]):
        raise ApiError("ERR_VALUATION_SUPERSEDED",
                       "The named valuation is not a live verified-basis snapshot of the deal's "
                       "listing.")
    if valuation["created_at"] < deal["created_at"]:
        raise ApiError("ERR_VERIFIED_VALUATION_MISSING",
                       "No eligible verified-basis valuation exists for the deal's listing.")
    if listing["verification_posture"] != "COMPLETE":
        raise ApiError("ERR_VERIFIED_MRR_SHORTFALL",
                       "The listing's verification posture is not COMPLETE.")
    if listing["verified_recurring_mrr_cents"] < verified_mrr_floor(listing["listed_mrr_cents"]):
        raise ApiError("ERR_VERIFIED_MRR_SHORTFALL",
                       "The verified recurring base falls short of the advertised one.")

    deal["status"] = "DILIGENCE_CLEARED"
    touch(deal)
    return object_response(deal_json(deal))


@bp.post("/deals/<identifier>/approve-financing")
def approve_financing(identifier):
    begin("Broker")
    data = body()
    lender_name = req_str(data, "lender_name", min_len=1, max_len=160)
    approved = req_cents(data, "approved_amount_cents")
    path_uuid(identifier)
    deal = get_deal(identifier)

    _gate(deal, ("DILIGENCE_CLEARED",), "have its financing approved")
    buyer = get_buyer(deal["buyer_id"])
    if approved > buyer["prequalified_amount_cents"]:
        raise ApiError("ERR_BUYER_PREQUAL_EXCEEDED",
                       "The approved amount exceeds the buyer's prequalified ceiling.")
    if approved != deal["note_principal_cents"]:
        raise ApiError("ERR_FINANCING_SPLIT_MISMATCH",
                       "The approved amount must equal the deal's note principal exactly.")

    deal["status"] = "FINANCING_APPROVED"
    deal["lender_name"] = lender_name
    deal["approved_amount_cents"] = approved
    touch(deal)
    return object_response(deal_json(deal))


@bp.post("/deals/<identifier>/close")
def close_deal(identifier):
    begin("Broker")
    path_uuid(identifier)
    deal = get_deal(identifier)
    listing = get_listing(deal["listing_id"])

    status = deal["status"]
    if status != "ESCROW_FUNDED":
        if status in TERMINAL_STATUSES:
            _terminal(deal)
        if status == "CLOSED":
            _invalid(deal, "be closed again")
        raise ApiError("ERR_DEAL_NOT_FUNDED",
                       "Closing was attempted on a deal that has not reached the funded state.")

    if not permits_cleared(deal["id"]):
        raise ApiError("ERR_LICENSE_NOT_TRANSFERRED",
                       "A permit the deal needs has not been approved or waived.")

    escrow = escrow_of_deal(deal)
    if escrow is None or escrow["funded_amount_cents"] < escrow["target_amount_cents"]:
        raise ApiError("ERR_ESCROW_UNDERFUNDED", "The escrow balance has not reached its target.")

    accounts = ordered(store.service_accounts, lambda a: a["listing_id"] == listing["id"])
    for account in accounts:
        if account["verification_status"] == "EXCLUDED":
            continue
        if account["transfer_status"] not in ("INTRODUCED", "TRANSFERRED"):
            raise ApiError("ERR_INTRODUCTIONS_INCOMPLETE",
                           "A stop the buyer has never been walked to still sits on the route.")

    clock = store.clock
    guarantee_end = clock + timedelta(days=deal["retention_guarantee_days"])
    price = deal["current_offer_price_cents"]
    commission = commission_for(price)
    deal["closed_at_utc"] = clock
    deal["guarantee_start_utc"] = clock
    deal["guarantee_end_utc"] = guarantee_end
    deal["holdback_release_utc"] = guarantee_end
    deal["replacement_deadline_utc"] = guarantee_end + timedelta(days=REPLACEMENT_GRACE_DAYS)
    deal["commission_cents"] = commission
    deal["clawback_cap_cents"] = clawback_cap_for(price)
    live = live_valuation(listing["id"], "VERIFIED_BASIS")
    deal["effective_multiple_at_close"] = live["effective_multiple"] if live is not None else None

    guaranteed = 0
    for account in ordered(store.service_accounts, lambda a: a["deal_id"] == deal["id"]):
        if account["transfer_status"] != "INTRODUCED":
            continue
        account["transfer_status"] = "TRANSFERRED"
        account["current_mrr_cents"] = account["verified_recurring_mrr_cents"]
        guaranteed += account["verified_recurring_mrr_cents"] or 0
        touch(account)
    deal["guaranteed_mrr_cents"] = guaranteed
    deal["retained_mrr_cents"] = guaranteed
    deal["attrited_mrr_cents"] = 0
    deal["allowance_mrr_cents"] = allowance_for(guaranteed)
    deal["clawback_status"] = "MONITORING"

    available = escrow["funded_amount_cents"] - escrow["holdback_amount_cents"]
    to_broker = commission if commission < available else available
    escrow["disbursed_to_broker_cents"] += to_broker
    escrow["disbursed_to_seller_cents"] += available - to_broker
    escrow["holdback_balance_cents"] = escrow["holdback_amount_cents"]
    escrow["undisbursed_balance_cents"] = 0
    escrow["status"] = "PARTIALLY_RELEASED"
    escrow["scheduled_holdback_release_utc"] = deal["holdback_release_utc"]
    touch(escrow)

    listing["status"] = "CLOSED"
    touch(listing)
    deal["status"] = "CLOSED"
    touch(deal)
    return object_response(deal_json(deal))


def _refund_escrow(deal):
    escrow = escrow_of_deal(deal)
    if escrow is None or escrow["status"] == "REFUNDED":
        return
    escrow["disbursed_to_buyer_cents"] += escrow["funded_amount_cents"]
    escrow["holdback_balance_cents"] = 0
    escrow["undisbursed_balance_cents"] = 0
    escrow["status"] = "REFUNDED"
    touch(escrow)


def _release_listing(listing, guard_other=None):
    if listing is None or listing["status"] != "UNDER_CONTRACT":
        return False
    if guard_other is not None:
        for other in store.deals.values():
            if other["id"] != guard_other["id"] and other["listing_id"] == listing["id"] \
                    and other["status"] in HOLDING_STATUSES:
                return False
    listing["status"] = "LISTED"
    return True


@bp.post("/deals/<identifier>/terminate")
def terminate_deal(identifier):
    begin("Broker", "Seller", "Buyer")
    existing = store.deals.get(identifier)
    if existing is not None:
        guard_deal(existing, store.route_listings.get(existing["listing_id"]))
    data = body()
    reason = req_str(data, "termination_reason_code", min_len=1)
    path_uuid(identifier)
    deal = get_deal(identifier)
    listing = store.route_listings.get(deal["listing_id"])

    status = deal["status"]
    if status in ("CLOSED", "GUARANTEE_CLOSED", "TERMINATED"):
        _terminal(deal)

    if status == "REPRICE_REQUIRED":
        _refund_escrow(deal)
        if _release_listing(listing, guard_other=deal):
            touch(listing)
    elif status in ("ACCEPTED", "DILIGENCE_CLEARED", "FINANCING_APPROVED", "ESCROW_FUNDED"):
        _refund_escrow(deal)
        for transfer in transfers_of_deal(deal["id"]):
            if transfer["status"] in ("NOT_STARTED", "APPLIED", "DENIED"):
                transfer["status"] = "CANCELLED"
                touch(transfer)
        for account in ordered(store.service_accounts, lambda a: a["deal_id"] == deal["id"]):
            if account["transfer_status"] == "INTRODUCED":
                account["transfer_status"] = "PENDING"
                account["deal_id"] = None
                account["introduced_on"] = None
                account["introduction_sequence_no"] = None
                touch(account)
        _release_listing(listing)
        if listing is not None:
            recompute_listing(listing)

    deal["status"] = "TERMINATED"
    deal["termination_reason_code"] = reason
    touch(deal)
    return object_response(deal_json(deal))
