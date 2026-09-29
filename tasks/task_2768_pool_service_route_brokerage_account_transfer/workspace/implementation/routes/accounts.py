"""Customer stops: creation, verification, exclusion, introduction, replacement."""

from datetime import timedelta

from flask import Blueprint, request

from auth import begin, guard_listing
from calc import (BILLING_FREQUENCIES, CHEMICAL_METHODS, INTRODUCTION_WINDOW_DAYS,
                  MAX_INTRODUCTIONS_PER_DATE, ROUTE_DAYS, add_days, claimed_recurring_mrr,
                  trailing_month_labels, verification_figures, verification_outcome,
                  verification_variance)
from errors import ApiError
from responses import list_response, object_response, pagination
from serializers import account_json
from services import (build_account, customer_ref_taken, diligence_cascade, get_account, get_deal,
                      get_listing, introduction_queue, listing_of_account, midnight,
                      permits_cleared, recompute_deal_ledger, recompute_listing)
from store import ordered, store, touch
from validators import bad, body, path_uuid, req_cents, req_date, req_enum, req_id, req_int, req_str

bp = Blueprint("accounts", __name__)

STOP_STATUSES_OPEN = ("UNVERIFIED", "VERIFIED", "DISPUTED")


def _stop_payload(data):
    payload = {
        "customer_ref": req_str(data, "customer_ref", min_len=1, max_len=60),
        "service_start_date": req_date(data, "service_start_date").isoformat(),
        "route_day": req_enum(data, "route_day", ROUTE_DAYS),
        "monthly_service_fee_cents": req_int(data, "monthly_service_fee_cents", minimum=1),
        "avg_monthly_chemical_cents": req_cents(data, "avg_monthly_chemical_cents"),
        "avg_monthly_repair_cents": req_cents(data, "avg_monthly_repair_cents"),
        "chemical_billing_method": req_enum(data, "chemical_billing_method", CHEMICAL_METHODS),
        "billing_frequency": req_enum(data, "billing_frequency", BILLING_FREQUENCIES),
    }
    return payload


@bp.post("/service-accounts")
def create_account():
    begin("Broker")
    data = body()
    listing_id = req_id(data, "listing_id")
    payload = _stop_payload(data)
    listing = get_listing(listing_id)
    if customer_ref_taken(listing_id, payload["customer_ref"]):
        bad("Field 'customer_ref' must be unique within its listing.")
    if listing["status"] not in ("DRAFT", "LISTED"):
        raise ApiError("ERR_LISTING_NOT_LISTED",
                       "Stops may only be added while the listing is DRAFT or LISTED.")

    account = build_account(listing_id, payload)
    recompute_listing(listing)
    return object_response(account_json(account), 201)


@bp.get("/service-accounts/<identifier>")
def read_account(identifier):
    begin("Broker", "PlatformAdmin", "Seller", "Buyer")
    existing = store.service_accounts.get(identifier)
    if existing is not None:
        guard_listing(listing_of_account(existing))
    path_uuid(identifier)
    return object_response(account_json(get_account(identifier)))


@bp.get("/service-accounts")
def list_accounts():
    begin("Broker", "PlatformAdmin", "Seller", "Buyer")
    limit, offset = pagination()
    filters = {key: request.args.get(key) for key in
               ("listing_id", "deal_id", "replaced_account_id", "verification_status",
                "transfer_status", "route_day")}

    def keep(row):
        for key, value in filters.items():
            if value is not None and row.get(key) != value:
                return False
        return True

    return list_response(ordered(store.service_accounts, keep), account_json, limit, offset)


@bp.post("/service-accounts/<identifier>/verify")
def verify_account(identifier):
    role, user_id = begin("Broker")
    path_uuid(identifier)
    account = get_account(identifier)

    if account["verification_status"] == "EXCLUDED":
        raise ApiError("ERR_ACCOUNT_EXCLUDED", "This stop has been excluded from the sale.")

    labels = trailing_month_labels(store.clock)
    rows_by_month = {}
    for record in ordered(store.billing_history_records,
                          lambda r: r["account_id"] == account["id"]):
        if record["source"] == "BANK_VERIFIED" and record["period_month"] in labels:
            rows_by_month[record["period_month"]] = record
    if len(rows_by_month) < len(labels):
        raise ApiError("ERR_INSUFFICIENT_BILLING_HISTORY",
                       "The trailing verification window is not fully covered by bank-verified "
                       "evidence.")

    verified_recurring, verified_repair = verification_figures(
        rows_by_month, labels, account["chemical_billing_method"])
    variance = verification_variance(verified_recurring, account["claimed_recurring_mrr_cents"])
    account["verified_recurring_mrr_cents"] = verified_recurring
    account["verified_repair_mrr_cents"] = verified_repair
    account["verification_variance"] = variance
    account["verification_status"] = verification_outcome(variance)
    account["verified_by_user_id"] = user_id
    touch(account)
    recompute_listing(get_listing(account["listing_id"]))
    return object_response(account_json(account))


@bp.post("/service-accounts/<identifier>/exclude")
def exclude_account(identifier):
    begin("Broker")
    data = body()
    reason = req_str(data, "exclusion_reason_code", min_len=1)
    path_uuid(identifier)
    account = get_account(identifier)
    listing = get_listing(account["listing_id"])

    if listing["status"] in ("CLOSED", "WITHDRAWN"):
        raise ApiError("ERR_LISTING_NOT_LISTED",
                       "A settled or abandoned sale has no list left to prune.")
    if account["verification_status"] not in STOP_STATUSES_OPEN:
        raise ApiError("ERR_INVALID_ACCOUNT_TRANSITION",
                       "A %s stop may not be excluded." % account["verification_status"])

    was_verified = account["verification_status"] == "VERIFIED"
    account["verification_status"] = "EXCLUDED"
    account["exclusion_reason_code"] = reason
    touch(account)
    recompute_listing(listing)
    if was_verified:
        diligence_cascade(listing)
    return object_response(account_json(account))


@bp.post("/service-accounts/<identifier>/reinstate")
def reinstate_account(identifier):
    begin("Broker")
    path_uuid(identifier)
    account = get_account(identifier)
    listing = get_listing(account["listing_id"])

    if listing["status"] in ("CLOSED", "WITHDRAWN"):
        raise ApiError("ERR_LISTING_NOT_LISTED",
                       "A settled or abandoned sale has no list left to restore.")
    if account["verification_status"] != "EXCLUDED":
        raise ApiError("ERR_INVALID_ACCOUNT_TRANSITION",
                       "Only an EXCLUDED stop may be reinstated.")

    account["verification_status"] = "UNVERIFIED"
    account["exclusion_reason_code"] = None
    account["verified_recurring_mrr_cents"] = None
    account["verified_repair_mrr_cents"] = None
    account["verification_variance"] = None
    touch(account)
    recompute_listing(listing)
    return object_response(account_json(account))


INTRODUCIBLE_DEAL_STATUSES = ("ACCEPTED", "DILIGENCE_CLEARED", "FINANCING_APPROVED",
                              "ESCROW_FUNDED")


@bp.post("/service-accounts/<identifier>/introduce")
def introduce_account(identifier):
    begin("Broker", "Seller")
    existing = store.service_accounts.get(identifier)
    if existing is not None:
        guard_listing(listing_of_account(existing))
    data = body()
    deal_id = req_id(data, "deal_id")
    introduction_date = req_date(data, "introduction_date").isoformat()
    path_uuid(identifier)
    account = get_account(identifier)
    deal = get_deal(deal_id)
    listing = get_listing(account["listing_id"])

    if account["verification_status"] == "EXCLUDED":
        raise ApiError("ERR_ACCOUNT_EXCLUDED",
                       "A stop carved out of the sale is not the buyer's to meet.")
    if account["transfer_status"] != "PENDING":
        raise ApiError("ERR_ACCOUNT_NOT_INTRODUCIBLE",
                       "This stop's transfer dimension is %s, not PENDING."
                       % account["transfer_status"])

    status = deal["status"]
    if status in ("DRAFT", "OFFER_SUBMITTED", "COUNTERED", "CLOSED", "REPRICE_REQUIRED"):
        raise ApiError("ERR_INVALID_DEAL_TRANSITION",
                       "A %s deal may not hand over customers." % status)
    if status in ("TERMINATED", "GUARANTEE_CLOSED"):
        raise ApiError("ERR_DEAL_TERMINAL", "The deal has reached an absorbing status.")
    if deal["non_solicitation_executed_on"] is None:
        raise ApiError("ERR_INVALID_DEAL_TRANSITION",
                       "Customers are not handed over before the covenant is signed.")

    if account["listing_id"] != deal["listing_id"]:
        raise ApiError("ERR_ACCOUNT_LISTING_MISMATCH",
                       "The account and the deal belong to different routes.")
    if not permits_cleared(deal["id"]):
        raise ApiError("ERR_LICENSE_NOT_TRANSFERRED",
                       "A permit the deal needs has not been approved or waived.")

    window_start = midnight(deal["accepted_on"])
    window_end = window_start + timedelta(days=INTRODUCTION_WINDOW_DAYS)
    if not (window_start <= store.clock < window_end):
        raise ApiError("ERR_INTRODUCTION_WINDOW_CLOSED",
                       "The introduction falls outside the post-acceptance window.")

    same_date = [a for a in store.service_accounts.values()
                 if a["deal_id"] == deal["id"] and a["introduced_on"] == introduction_date]
    if len(same_date) >= MAX_INTRODUCTIONS_PER_DATE:
        raise ApiError("ERR_INTRODUCTION_LIMIT_REACHED",
                       "The per-date introduction cap for the deal has been reached.")

    queue = introduction_queue(listing["id"])
    if not queue or queue[0]["id"] != account["id"]:
        raise ApiError("ERR_INTRODUCTION_OUT_OF_SEQUENCE",
                       "The account is not at the head of the introduction queue.")

    seller = store.sellers.get(listing["seller_id"])
    if seller is not None and seller["status"] == "SUSPENDED":
        raise ApiError("ERR_SELLER_SUSPENDED", "The listing's seller is suspended.")

    account["transfer_status"] = "INTRODUCED"
    account["deal_id"] = deal["id"]
    account["introduced_on"] = introduction_date
    account["introduction_sequence_no"] = listing["introductions_completed_count"] + 1
    touch(account)
    recompute_listing(listing)
    return object_response(account_json(account))


@bp.post("/service-accounts/<identifier>/replace")
def replace_account(identifier):
    begin("Seller", "Broker")
    existing = store.service_accounts.get(identifier)
    if existing is not None:
        guard_listing(listing_of_account(existing))
    data = body()
    payload = _stop_payload(data)
    path_uuid(identifier)
    lost = get_account(identifier)
    if lost["deal_id"] is None:
        raise ApiError("ERR_GUARANTEE_NOT_STARTED",
                       "This stop has never been handed over under a deal.")
    deal = get_deal(lost["deal_id"])
    if customer_ref_taken(lost["listing_id"], payload["customer_ref"]):
        bad("Field 'customer_ref' must be unique within its listing.")

    if lost["transfer_status"] != "LOST":
        raise ApiError("ERR_ACCOUNT_NOT_INTRODUCIBLE",
                       "Only a LOST stop may be substituted, not %s."
                       % lost["transfer_status"])
    if deal["status"] in ("TERMINATED", "GUARANTEE_CLOSED"):
        raise ApiError("ERR_DEAL_TERMINAL", "The deal has reached an absorbing status.")
    if deal["status"] != "CLOSED":
        raise ApiError("ERR_GUARANTEE_NOT_STARTED",
                       "A post-close operation was attempted on a deal that has not closed.")
    if lost["listing_id"] != deal["listing_id"]:
        raise ApiError("ERR_ACCOUNT_LISTING_MISMATCH",
                       "The account and the deal belong to different routes.")

    claimed = claimed_recurring_mrr(payload["monthly_service_fee_cents"],
                                    payload["avg_monthly_chemical_cents"],
                                    payload["chemical_billing_method"],
                                    payload["billing_frequency"])
    if claimed <= 0 or payload["route_day"] != lost["route_day"]:
        raise ApiError("ERR_REPLACEMENT_TARGET_INVALID",
                       "The substitute stop offered does not qualify as a replacement.")
    if deal["replacement_deadline_utc"] is not None and store.clock > deal["replacement_deadline_utc"]:
        raise ApiError("ERR_REPLACEMENT_DEADLINE_PASSED",
                       "The substitution grace period has expired.")

    lost["transfer_status"] = "REPLACED"
    touch(lost)
    substitute = build_account(lost["listing_id"], payload, deal_id=deal["id"],
                               replaced_account_id=lost["id"],
                               verification_status="VERIFIED",
                               transfer_status="TRANSFERRED")
    substitute["verified_recurring_mrr_cents"] = substitute["claimed_recurring_mrr_cents"]
    substitute["current_mrr_cents"] = substitute["claimed_recurring_mrr_cents"]
    recompute_listing(get_listing(lost["listing_id"]))
    recompute_deal_ledger(deal)
    return object_response(account_json(substitute), 201)
