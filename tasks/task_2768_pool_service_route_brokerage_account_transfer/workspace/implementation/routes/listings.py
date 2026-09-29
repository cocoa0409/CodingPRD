"""Route listings: creation, amendment, publication, withdrawal, valuations."""

import re

from flask import Blueprint, request

from auth import begin, guard_listing
from calc import VALUATION_BASES, parse_date
from errors import ApiError
from responses import list_response, object_response, pagination
from serializers import listing_json, valuation_json
from services import (create_valuation, exclusivity_conflict, get_listing, get_seller,
                      live_valuation, profile_for_state, valuation_inputs, supersede_valuations,
                      write_valuation)
from store import new_record, ordered, store, touch
from validators import (bad, body, opt_present, path_uuid, req_date, req_enum, req_id, req_int,
                        req_str)

bp = Blueprint("listings", __name__)

STATE_CODE_RE = r"^[A-Z]{2}$"
AMENDABLE_STATUSES = ("DRAFT", "LISTED")


@bp.post("/route-listings")
def create_listing():
    begin("Broker")
    data = body()
    seller_id = req_id(data, "seller_id")
    region_code = req_str(data, "region_code", min_len=1, max_len=20)
    state_code = req_str(data, "state_code", min_len=2, max_len=2)
    if not re.match(STATE_CODE_RE, state_code):
        bad("Field 'state_code' must be exactly two uppercase letters.")
    asking_price = req_int(data, "asking_price_cents", minimum=1)
    listed_mrr = req_int(data, "listed_mrr_cents", minimum=1)
    listed_count = req_int(data, "listed_account_count", minimum=1)
    start_date = req_date(data, "exclusive_start_date")
    end_date = req_date(data, "exclusive_end_date")
    if end_date <= start_date:
        bad("Field 'exclusive_end_date' must fall strictly after 'exclusive_start_date'.")

    get_seller(seller_id)

    if exclusivity_conflict(seller_id, region_code, start_date.isoformat(), end_date.isoformat()):
        raise ApiError("ERR_LISTING_EXCLUSIVITY_OVERLAP",
                       "The exclusive representation window collides with another for this "
                       "seller and region.")

    record = new_record()
    record.update({
        "seller_id": seller_id, "region_code": region_code, "state_code": state_code,
        "asking_price_cents": asking_price, "listed_mrr_cents": listed_mrr,
        "listed_account_count": listed_count,
        "exclusive_start_date": start_date.isoformat(),
        "exclusive_end_date": end_date.isoformat(),
        "status": "DRAFT",
        "claimed_recurring_mrr_cents": 0, "claimed_repair_mrr_cents": 0,
        "claimed_account_count": 0, "verified_recurring_mrr_cents": 0,
        "verified_repair_mrr_cents": 0, "verified_account_count": 0,
        "verification_posture": "EMPTY", "introductions_completed_count": 0,
        "withdrawal_reason_code": None,
    })
    store.route_listings[record["id"]] = record
    return object_response(listing_json(record), 201)


@bp.get("/route-listings/<identifier>")
def read_listing(identifier):
    begin("Broker", "PlatformAdmin", "Seller", "Buyer")
    guard_listing(store.route_listings.get(identifier))
    path_uuid(identifier)
    return object_response(listing_json(get_listing(identifier)))


@bp.get("/route-listings")
def list_listings():
    begin("Broker", "PlatformAdmin", "Seller", "Buyer")
    limit, offset = pagination()
    seller_id = request.args.get("seller_id")
    region_code = request.args.get("region_code")
    state_code = request.args.get("state_code")
    status = request.args.get("status")

    def keep(row):
        return ((seller_id is None or row["seller_id"] == seller_id)
                and (region_code is None or row["region_code"] == region_code)
                and (state_code is None or row["state_code"] == state_code)
                and (status is None or row["status"] == status))

    return list_response(ordered(store.route_listings, keep), listing_json, limit, offset)


@bp.patch("/route-listings/<identifier>")
def amend_listing(identifier):
    begin("Broker")
    data = body()
    asking_price = req_int(data, "asking_price_cents", required=False, minimum=1)
    listed_mrr = req_int(data, "listed_mrr_cents", required=False, minimum=1)
    listed_count = req_int(data, "listed_account_count", required=False, minimum=1)
    start_date = req_date(data, "exclusive_start_date", required=False)
    end_date = req_date(data, "exclusive_end_date", required=False)
    path_uuid(identifier)
    listing = get_listing(identifier)

    merged_start = start_date or parse_date(listing["exclusive_start_date"])
    merged_end = end_date or parse_date(listing["exclusive_end_date"])
    if merged_end <= merged_start:
        bad("Field 'exclusive_end_date' must fall strictly after 'exclusive_start_date'.")

    if listing["status"] not in AMENDABLE_STATUSES:
        raise ApiError("ERR_INVALID_LISTING_TRANSITION",
                       "A %s listing may not be amended." % listing["status"])

    if exclusivity_conflict(listing["seller_id"], listing["region_code"],
                            merged_start.isoformat(), merged_end.isoformat(),
                            exclude_listing_id=listing["id"]):
        raise ApiError("ERR_LISTING_EXCLUSIVITY_OVERLAP",
                       "The amended window collides with another for this seller and region.")

    if opt_present(data, "asking_price_cents"):
        listing["asking_price_cents"] = asking_price
    if opt_present(data, "listed_mrr_cents"):
        listing["listed_mrr_cents"] = listed_mrr
    if opt_present(data, "listed_account_count"):
        listing["listed_account_count"] = listed_count
    listing["exclusive_start_date"] = merged_start.isoformat()
    listing["exclusive_end_date"] = merged_end.isoformat()
    touch(listing)
    return object_response(listing_json(listing))


@bp.post("/route-listings/<identifier>/publish")
def publish_listing(identifier):
    begin("Broker")
    path_uuid(identifier)
    listing = get_listing(identifier)

    if listing["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_LISTING_TRANSITION",
                       "Publication is available from DRAFT only.")
    if profile_for_state(listing["state_code"]) is None:
        raise ApiError("ERR_STATE_PROFILE_MISSING",
                       "No licensing profile exists for state %s." % listing["state_code"])
    if exclusivity_conflict(listing["seller_id"], listing["region_code"],
                            listing["exclusive_start_date"], listing["exclusive_end_date"],
                            exclude_listing_id=listing["id"]):
        raise ApiError("ERR_LISTING_EXCLUSIVITY_OVERLAP",
                       "The exclusive representation window collides with another for this "
                       "seller and region.")
    seller = store.sellers.get(listing["seller_id"])
    if seller is not None and seller["status"] == "SUSPENDED":
        raise ApiError("ERR_SELLER_SUSPENDED", "The listing's seller is suspended.")
    if listing["claimed_account_count"] < 1 or live_valuation(listing["id"], "LISTED_BASIS") is None:
        raise ApiError("ERR_LISTING_NOT_PUBLISHABLE",
                       "The listing lacks the accounts or the live listed-basis valuation "
                       "publication requires.")

    listing["status"] = "LISTED"
    touch(listing)
    return object_response(listing_json(listing))


@bp.post("/route-listings/<identifier>/withdraw")
def withdraw_listing(identifier):
    begin("Broker", "Seller")
    guard_listing(store.route_listings.get(identifier))
    data = body()
    reason = req_str(data, "withdrawal_reason_code", min_len=1)
    path_uuid(identifier)
    listing = get_listing(identifier)

    if listing["status"] not in ("DRAFT", "LISTED"):
        raise ApiError("ERR_INVALID_LISTING_TRANSITION",
                       "Withdrawal is available from DRAFT and LISTED only.")

    listing["status"] = "WITHDRAWN"
    listing["withdrawal_reason_code"] = reason
    touch(listing)

    for deal in ordered(store.deals, lambda d: d["listing_id"] == listing["id"]):
        if deal["status"] in ("OFFER_SUBMITTED", "COUNTERED", "REPRICE_REQUIRED"):
            deal["status"] = "TERMINATED"
            deal["termination_reason_code"] = "LISTING_WITHDRAWN"
            touch(deal)
    return object_response(listing_json(listing))


@bp.post("/route-listings/<identifier>/valuations")
def create_listing_valuation(identifier):
    begin("Broker")
    data = body()
    basis = req_enum(data, "basis", VALUATION_BASES)
    expected_version = req_int(data, "expected_listing_version", minimum=0)
    path_uuid(identifier)
    listing = get_listing(identifier)

    if expected_version != listing["version"]:
        raise ApiError("ERR_STALE_LISTING_VERSION",
                       "The listing has moved on since version %s." % expected_version)
    if listing["status"] not in ("DRAFT", "LISTED"):
        raise ApiError("ERR_LISTING_NOT_LISTED",
                       "Snapshots may only be taken while the listing is DRAFT or LISTED.")
    inputs = valuation_inputs(listing["id"], basis)
    if not inputs:
        raise ApiError("ERR_NO_VALUATION_INPUTS",
                       "The requested valuation basis selects no accounts at all.")
    seller = store.sellers.get(listing["seller_id"])
    if seller is not None and seller["status"] == "SUSPENDED":
        raise ApiError("ERR_SELLER_SUSPENDED", "The listing's seller is suspended.")

    supersede_valuations(listing["id"], basis)
    record = write_valuation(listing["id"], basis, inputs)
    touch(listing)
    return object_response(valuation_json(record), 201)
