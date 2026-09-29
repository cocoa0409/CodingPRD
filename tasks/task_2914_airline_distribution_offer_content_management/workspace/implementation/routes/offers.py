"""Offer construction, pricing and publication (PRD 3.5)."""
from flask import Blueprint

import calc
import validators as v
from auth import (ALL_ROLES, ROLE_AGENCY, ROLE_COMPLIANCE_AUDITOR,
                  ROLE_DISTRIBUTION_MANAGER, ROLE_PLATFORM_ADMIN,
                  ROLE_PRICING_ANALYST, authenticate)
from envelope import paginate, pagination, respond_list, respond_object
from errors import ApiError
from routing import precheck_self, resolve_owned
from serializers import offer_item_out, offer_out
from services import (ancillary_by_code, contract_validity_state, lazy_expire_offer,
                      offer_expiry, offer_items_for, price_offer_lines)
from store import bump, common_fields, db, immutable_fields, now, sort_key

bp = Blueprint("offers", __name__)

CABINS = ("ECONOMY", "PREMIUM", "BUSINESS")
OFFER_STATES = ("CONSTRUCTED", "PUBLISHED", "ORDERED", "WITHDRAWN", "EXPIRED")


def _resolve_components(partner_id, channel_id, fare_filing_id, bundle_id,
                        corporate_contract_id, ancillary_codes):
    """PRD 2.10 step 5, in the declared field order."""
    partner = db.partners.get(partner_id)
    if partner is None:
        raise ApiError("ERR_PARTNER_NOT_FOUND", "partner_id does not resolve.")
    channel = db.channels.get(channel_id)
    if channel is None:
        raise ApiError("ERR_CHANNEL_NOT_FOUND", "channel_id does not resolve.")
    filing = db.fare_filings.get(fare_filing_id)
    if filing is None:
        raise ApiError("ERR_FARE_FILING_NOT_FOUND", "fare_filing_id does not resolve.")
    bundle = None
    if bundle_id is not None:
        bundle = db.bundles.get(bundle_id)
        if bundle is None:
            raise ApiError("ERR_BUNDLE_NOT_FOUND", "bundle_id does not resolve.")
    contract = None
    if corporate_contract_id is not None:
        contract = db.contracts.get(corporate_contract_id)
        if contract is None:
            raise ApiError("ERR_CONTRACT_NOT_FOUND",
                           "corporate_contract_id does not resolve.")
    products = []
    for code in ancillary_codes:
        product = ancillary_by_code(code)
        if product is None:
            raise ApiError("ERR_ANCILLARY_NOT_FOUND",
                           "ancillary_codes names an unknown product: %s" % code)
        products.append(product)
    return partner, channel, filing, bundle, contract, products


def _check_content_tier(channel, filing, bundle, contract, products):
    rank = channel["content_tier_rank"]
    required = [filing["min_content_tier_rank"]]
    required.extend(p["min_content_tier_rank"] for p in products)
    if bundle is not None:
        required.append(bundle["min_content_tier_rank"])
    if contract is not None:
        required.append(contract["min_content_tier_rank"])
    if any(rank < needed for needed in required):
        raise ApiError("ERR_CONTENT_TIER_INSUFFICIENT",
                       "The channel's content tier does not entitle this content.")


@bp.post("/offers")
def construct_offer():
    actor = authenticate([ROLE_AGENCY, ROLE_DISTRIBUTION_MANAGER])
    body = v.json_body()
    precheck_self(actor, body, "partner_id")
    channel_id = v.req_string(body, "channel_id", 1, None)
    partner_id = v.req_string(body, "partner_id", 1, None)
    fare_filing_id = v.req_string(body, "fare_filing_id", 1, None)
    bundle_id = v.opt_string(body, "bundle_id", 1, None)
    corporate_contract_id = v.opt_string(body, "corporate_contract_id", 1, None)
    ancillary_codes = v.opt_str_array(body, "ancillary_codes", [])
    trip_origin = v.req_station(body, "trip_origin")
    trip_destination = v.req_station(body, "trip_destination")
    departure_date = v.req_instant(body, "departure_date")
    cabin = v.req_enum(body, "cabin", CABINS)

    partner, channel, filing, bundle, contract, products = _resolve_components(
        partner_id, channel_id, fare_filing_id, bundle_id,
        corporate_contract_id, ancillary_codes)

    # Step 8: the filing must still be sellable.
    if filing["status"] != "ACTIVE":
        raise ApiError("ERR_FARE_FILING_NOT_ACTIVE",
                       "The fare filing is not ACTIVE.")
    # Step 17: a private fare needs the contract that unlocks this very filing.
    if filing["is_private"]:
        if contract is None or contract["negotiated_fare_filing_id"] != filing["id"]:
            raise ApiError("ERR_PRIVATE_FARE_REQUIRES_CONTRACT",
                           "A private fare requires the contract that unlocks it.")
    # Step 21: a named contract must be in effect against the logical clock.
    if contract is not None and contract_validity_state(contract) != "IN_EFFECT":
        raise ApiError("ERR_CONTRACT_NOT_IN_EFFECT",
                       "The corporate contract is not IN_EFFECT.")
    # Step 22: half-open sale window.
    clock = now()
    if not (filing["sale_from"] <= clock < filing["sale_to"]):
        raise ApiError("ERR_FARE_SALE_WINDOW_CLOSED",
                       "The filing's sale window is closed.")
    # Step 23: closed travel window.
    if not (filing["travel_from"] <= departure_date <= filing["travel_to"]):
        raise ApiError("ERR_TRAVEL_DATE_OUT_OF_WINDOW",
                       "departure_date falls outside the filing's travel window.")
    # Step 27: content entitlement across every component at once.
    _check_content_tier(channel, filing, bundle, contract, products)

    lines, subtotal, surcharge_total, total = price_offer_lines(
        channel, filing, bundle, ancillary_codes)

    # Step 31: the fiscal cap is decided on the finished figure.
    if contract is not None and total > contract["max_offer_total_cents"]:
        raise ApiError("ERR_CONTRACT_CAP_EXCEEDED",
                       "The priced total exceeds the contract's cap.")

    offer = common_fields()
    offer.update({
        "channel_id": channel["id"],
        "partner_id": partner["id"],
        "fare_filing_id": filing["id"],
        "bundle_id": bundle["id"] if bundle is not None else None,
        "corporate_contract_id": contract["id"] if contract is not None else None,
        "ancillary_codes": list(ancillary_codes),
        "trip_origin": trip_origin,
        "trip_destination": trip_destination,
        "departure_date": departure_date,
        "cabin": cabin,
        "subtotal_cents": subtotal,
        "surcharge_cents": surcharge_total,
        "total_cents": total,
        "item_count": len(lines),
        "acknowledged_disclosure_codes": [],
        "disclosure_complete": False,
        "expires_at": None,
        "priced_channel_version": channel["version"],
        "status": "CONSTRUCTED",
    })
    offer["expires_at"] = offer_expiry(offer["created_at"])
    db.offers[offer["id"]] = offer

    for index, line in enumerate(lines, start=1):
        item = immutable_fields()
        item.update({
            "offer_id": offer["id"],
            "item_type": line["item_type"],
            "item_code": line["item_code"],
            "sequence": index,
            "list_amount_cents": line["list_amount_cents"],
            "net_amount_cents": line["net_amount_cents"],
            "refundable": line["refundable"],
        })
        db.offer_items[item["id"]] = item

    return respond_object(offer_out(offer), 201)


@bp.get("/offers/<offer_id>")
def read_offer(offer_id):
    actor = authenticate(ALL_ROLES)
    pending, offer = resolve_owned(db.offers, offer_id, "ERR_OFFER_NOT_FOUND", actor)
    pending.raise_if_missing()
    # Lazy expiry runs before the read is served.
    lazy_expire_offer(offer)
    return respond_object(offer_out(offer))


@bp.get("/offers")
def list_offers():
    authenticate([ROLE_PLATFORM_ADMIN, ROLE_PRICING_ANALYST,
                  ROLE_DISTRIBUTION_MANAGER, ROLE_COMPLIANCE_AUDITOR, ROLE_AGENCY])
    limit, offset = pagination()
    channel_id = v.query_string("channel_id")
    partner_id = v.query_string("partner_id")
    fare_filing_id = v.query_string("fare_filing_id")
    bundle_id = v.query_string("bundle_id")
    corporate_contract_id = v.query_string("corporate_contract_id")
    status = v.query_enum("status", OFFER_STATES)

    rows = []
    for offer in db.offers.values():
        if channel_id is not None and offer["channel_id"] != channel_id:
            continue
        if partner_id is not None and offer["partner_id"] != partner_id:
            continue
        if fare_filing_id is not None and offer["fare_filing_id"] != fare_filing_id:
            continue
        if bundle_id is not None and offer["bundle_id"] != bundle_id:
            continue
        if (corporate_contract_id is not None
                and offer["corporate_contract_id"] != corporate_contract_id):
            continue
        if status is not None and offer["status"] != status:
            continue
        rows.append(offer)
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return respond_list([offer_out(o) for o in page], limit, offset, total)


@bp.get("/offers/<offer_id>/items")
def list_offer_items(offer_id):
    actor = authenticate([ROLE_PLATFORM_ADMIN, ROLE_PRICING_ANALYST,
                          ROLE_DISTRIBUTION_MANAGER, ROLE_COMPLIANCE_AUDITOR,
                          ROLE_AGENCY])
    limit, offset = pagination()
    pending, offer = resolve_owned(db.offers, offer_id, "ERR_OFFER_NOT_FOUND", actor)
    pending.raise_if_missing()
    items = offer_items_for(offer["id"])
    page, total = paginate(items, limit, offset)
    return respond_list([offer_item_out(i) for i in page], limit, offset, total)


@bp.post("/offers/<offer_id>/publish")
def publish_offer(offer_id):
    actor = authenticate([ROLE_AGENCY, ROLE_DISTRIBUTION_MANAGER])
    pending, offer = resolve_owned(db.offers, offer_id, "ERR_OFFER_NOT_FOUND", actor)
    body = v.json_body()
    ack_codes = v.opt_str_array(body, "disclosure_ack_codes", [])
    pending.raise_if_missing()

    # Step 7: lazy expiry is applied, then the operation is refused.
    lazy_expire_offer(offer)
    if offer["status"] == "EXPIRED":
        raise ApiError("ERR_OFFER_EXPIRED", "The offer has reached expires_at.")

    filing = db.fare_filings[offer["fare_filing_id"]]
    if filing["status"] != "ACTIVE":
        raise ApiError("ERR_FARE_FILING_NOT_ACTIVE",
                       "The offer's fare filing is no longer ACTIVE.")
    if offer["status"] != "CONSTRUCTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a CONSTRUCTED offer may be published.")

    channel = db.channels[offer["channel_id"]]
    missing = calc.missing_disclosure_codes(channel["required_disclosure_codes"],
                                            ack_codes)
    if missing:
        raise ApiError("ERR_DISCLOSURE_INCOMPLETE",
                       "Unacknowledged disclosure codes: %s" % ", ".join(missing))

    offer["acknowledged_disclosure_codes"] = list(ack_codes)
    offer["disclosure_complete"] = True
    offer["status"] = "PUBLISHED"
    bump(offer)
    return respond_object(offer_out(offer))
