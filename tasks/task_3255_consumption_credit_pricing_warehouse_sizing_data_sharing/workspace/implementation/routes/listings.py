"""Marketplace listings, paid usage, provider payouts and disputes."""
from decimal import Decimal

from flask import Blueprint, g, request

from db import db, find
from auth import authorize
from errors import err
from response import success, paged, sort_by_created, pagination
from serializers import listing as ser_listing, paid_usage as ser_usage
from services import engine
from util import now, r6, r2, new_id

from routes.common import (body, req_str, req_dec, opt_enum, req_enum, required,
                           MISSING, require_provider_ownership)

bp = Blueprint("listings", __name__)


def load(listing_id):
    record = find(db.listings, listing_id)
    if record is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Listing not found.")
    return record


def load_usage(usage_id):
    record = find(db.paid_usage, usage_id)
    if record is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "PaidShareUsage not found.")
    return record


def provider_of(listing):
    share = find(db.shares, listing["share_id"])
    return share["provider_account_id"] if share else None


@bp.route("/v1/listings", methods=["POST"])
def create_listing():
    authorize(g.role, ["ShareAdmin"])
    data = body()
    share_id = req_str(data, "share_id")
    share = find(db.shares, share_id)
    if share is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "DataShare not found.")
    require_provider_ownership(share["provider_account_id"])
    title = req_str(data, "title")
    pricing_model = req_enum(data, "pricing_model", engine.PRICING_MODELS)
    flat_price = req_dec(data, "flat_price_usd")
    if flat_price < 0:
        raise err("ERR_INVALID_REQUEST", "flat_price_usd must be non-negative.")
    if share["status"] != "PUBLISHED":
        raise err("ERR_SHARE_NOT_PUBLISHED",
                  "A listing may only be created over a PUBLISHED share.")
    for existing in engine.child_listings(share_id):
        if existing["title"] == title:
            raise err("ERR_DUPLICATE_RESOURCE",
                      "Listing.title must be unique within its share.")
    ts = now()
    record = {
        "id": new_id(),
        "share_id": share_id,
        "title": title,
        "pricing_model": pricing_model,
        "flat_price_usd": flat_price,
        "listing_state": "DRAFT",
        "gross_credit_volume": r6(0),
        "provider_payout_usd": r2(0),
        "platform_fee_usd": r2(0),
        "frozen_price_usd": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.listings.append(record)
    return success(ser_listing(record), 201)


@bp.route("/v1/listings", methods=["GET"])
def list_listings():
    authorize(g.role, ["ShareAdmin", "PlatformOperator", "FinanceController"])
    items = sort_by_created(db.listings)
    share_id = request.args.get("share_id")
    state = request.args.get("listing_state")
    model = request.args.get("pricing_model")
    if share_id:
        items = [l for l in items if l["share_id"] == share_id]
    if state:
        items = [l for l in items if l["listing_state"] == state]
    if model:
        items = [l for l in items if l["pricing_model"] == model]
    limit, offset = pagination()
    return paged([ser_listing(l) for l in items], limit, offset)


@bp.route("/v1/listings/<listing_id>", methods=["GET"])
def get_listing(listing_id):
    authorize(g.role, ["ShareAdmin", "PlatformOperator", "FinanceController"])
    return success(ser_listing(load(listing_id)))


@bp.route("/v1/listings/<listing_id>/publish", methods=["POST"])
def publish_listing(listing_id):
    authorize(g.role, ["ShareAdmin"])
    listing = load(listing_id)
    require_provider_ownership(provider_of(listing))
    if listing["listing_state"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT listing can be published.")
    share = find(db.shares, listing["share_id"])
    if share is None or share["status"] != "PUBLISHED":
        raise err("ERR_SHARE_NOT_PUBLISHED",
                  "The listing's share is not PUBLISHED.")
    if listing["pricing_model"] == "USAGE_BASED" and listing["flat_price_usd"] <= 0:
        raise err("ERR_INVALID_REQUEST",
                  "A USAGE_BASED listing requires a strictly positive flat_price_usd.")
    listing["listing_state"] = "PUBLISHED"
    engine.touch(listing)
    return success(ser_listing(listing))


@bp.route("/v1/listings/<listing_id>/withdraw", methods=["POST"])
def withdraw_listing(listing_id):
    authorize(g.role, ["ShareAdmin"])
    listing = load(listing_id)
    require_provider_ownership(provider_of(listing))
    if listing["listing_state"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE", "Only a PUBLISHED listing can be withdrawn.")
    listing["listing_state"] = "WITHDRAWN"
    engine.touch(listing)
    return success(ser_listing(listing))


@bp.route("/v1/listings/<listing_id>/provider-payout", methods=["GET"])
def provider_payout(listing_id):
    authorize(g.role, ["FinanceController", "PlatformOperator", "ShareAdmin"])
    listing = load(listing_id)
    require_provider_ownership(provider_of(listing))
    if listing["listing_state"] not in ("PUBLISHED",):
        raise err("ERR_LISTING_NOT_PUBLISHED",
                  "A payout is only reported for a PUBLISHED listing.")
    if listing["pricing_model"] == "FREE":
        raise err("ERR_FREE_LISTING_NOT_PAYABLE", "A free listing is not payable.")
    price_source = "FROZEN" if listing["frozen_price_usd"] is not None else "LISTING"
    payload = {
        "gross_credit_volume": float(listing["gross_credit_volume"]),
        "provider_payout_usd": float(listing["provider_payout_usd"]),
        "platform_fee_usd": float(listing["platform_fee_usd"]),
        "frozen_price_usd": (float(listing["frozen_price_usd"])
                             if listing["frozen_price_usd"] is not None else None),
        "price_source": price_source,
    }
    return success(payload)


@bp.route("/v1/paid-share-usage", methods=["POST"])
def create_paid_usage():
    authorize(g.role, ["DataEngineer", "ShareAdmin"])
    data = body()
    listing_id = req_str(data, "listing_id")
    listing = find(db.listings, listing_id)
    if listing is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Listing not found.")
    require_provider_ownership(provider_of(listing))
    buyer_id = req_str(data, "buyer_account_id")
    buyer = find(db.accounts, buyer_id)
    if buyer is None:
        raise err("ERR_REFERENCE_INVALID", "buyer_account_id does not resolve.")
    if buyer_id == provider_of(listing):
        raise err("ERR_SHARE_SELF_CONSUMPTION",
                  "A buyer may not be the listing's provider account.")
    credits = req_dec(data, "credits_used")
    if credits <= 0:
        raise err("ERR_INVALID_REQUEST", "credits_used must be strictly positive.")
    expected = data.get("expected_listing_version")

    if listing["listing_state"] != "PUBLISHED":
        raise err("ERR_LISTING_NOT_PUBLISHED",
                  "Paid usage may only be recorded against a PUBLISHED listing.")
    if listing["pricing_model"] == "FREE":
        raise err("ERR_FREE_LISTING_NOT_PAYABLE", "A free listing is not payable.")
    if expected is None:
        raise err("ERR_INVALID_REQUEST", "expected_listing_version is required.")
    if expected != listing["version"]:
        raise err("ERR_STALE_VERSION", "The listing version has advanced.")

    ts = now()
    price = listing["flat_price_usd"]
    record = {
        "id": new_id(),
        "listing_id": listing_id,
        "buyer_account_id": buyer_id,
        "credits_used": credits,
        "price_per_credit": price,
        "usage_state": "PENDING",
        "disputed_by_user_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.paid_usage.append(record)
    return success(ser_usage(record), 201)


@bp.route("/v1/paid-share-usage", methods=["GET"])
def list_paid_usage():
    authorize(g.role, ["DataEngineer", "ShareAdmin", "FinanceController", "PlatformOperator"])
    items = sort_by_created(db.paid_usage)
    listing_id = request.args.get("listing_id")
    state = request.args.get("usage_state")
    buyer_id = request.args.get("buyer_account_id")
    if listing_id:
        items = [p for p in items if p["listing_id"] == listing_id]
    if state:
        items = [p for p in items if p["usage_state"] == state]
    if buyer_id:
        items = [p for p in items if p["buyer_account_id"] == buyer_id]
    limit, offset = pagination()
    return paged([ser_usage(p) for p in items], limit, offset)


@bp.route("/v1/paid-share-usage/<usage_id>", methods=["GET"])
def get_paid_usage(usage_id):
    authorize(g.role, ["DataEngineer", "ShareAdmin", "FinanceController", "PlatformOperator"])
    return success(ser_usage(load_usage(usage_id)))


@bp.route("/v1/paid-share-usage/<usage_id>/settle", methods=["POST"])
def settle_usage(usage_id):
    authorize(g.role, ["FinanceController", "PlatformOperator"])
    record = load_usage(usage_id)
    listing = find(db.listings, record["listing_id"])
    if listing is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Listing not found.")
    if record["usage_state"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only a PENDING row can be settled.")
    if listing["pricing_model"] == "FREE":
        raise err("ERR_FREE_LISTING_NOT_PAYABLE", "A free listing is not payable.")

    if listing["pricing_model"] == "USAGE_BASED":
        if listing["frozen_price_usd"] is None:
            listing["frozen_price_usd"] = listing["flat_price_usd"]
        record["price_per_credit"] = listing["frozen_price_usd"]
    else:
        record["price_per_credit"] = listing["flat_price_usd"]

    _gross, prior_payout, _fee = engine.recompute_listing_payout(listing)
    record["usage_state"] = "SETTLED"
    engine.touch(record)
    _gross2, new_payout, _fee2 = engine.recompute_listing_payout(listing)
    engine.touch(listing)
    engine.post_ledger(provider_of(listing) or listing["id"], "PAYOUT", "Listing",
                       record["id"], amount_usd=r2(new_payout - prior_payout))
    return success(ser_usage(record))


@bp.route("/v1/paid-share-usage/<usage_id>/dispute", methods=["POST"])
def dispute_usage(usage_id):
    authorize(g.role, ["PlatformOperator"])
    record = load_usage(usage_id)
    listing = find(db.listings, record["listing_id"])
    if listing is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Listing not found.")
    data = body()
    expected = data.get("expected_listing_version")
    if record["usage_state"] != "SETTLED":
        raise err("ERR_INVALID_STATE", "Only a SETTLED row can be disputed.")
    if expected is None:
        raise err("ERR_INVALID_REQUEST", "expected_listing_version is required.")
    if expected != listing["version"]:
        raise err("ERR_STALE_VERSION", "The listing version has advanced.")

    _gross, prior_payout, _fee = engine.recompute_listing_payout(listing)
    record["usage_state"] = "DISPUTED"
    record["disputed_by_user_id"] = g.user_id
    engine.touch(record)
    _gross2, new_payout, _fee2 = engine.recompute_listing_payout(listing)
    engine.touch(listing)
    engine.post_ledger(provider_of(listing) or listing["id"], "PAYOUT_ADJUST", "Listing",
                       record["id"], amount_usd=r2(new_payout - prior_payout))
    return success(ser_usage(record))


@bp.route("/v1/paid-share-usage/<usage_id>/resolve", methods=["POST"])
def resolve_usage(usage_id):
    authorize(g.role, ["PlatformOperator"])
    record = load_usage(usage_id)
    listing = find(db.listings, record["listing_id"])
    if listing is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Listing not found.")
    if record["usage_state"] != "DISPUTED":
        raise err("ERR_INVALID_STATE", "Only a DISPUTED row can be resolved.")
    if record["disputed_by_user_id"] is not None and \
            record["disputed_by_user_id"] == g.user_id:
        raise err("ERR_DISPUTE_SELF_RESOLVE",
                  "The operator who raised the dispute cannot resolve it.")

    _gross, prior_payout, _fee = engine.recompute_listing_payout(listing)
    record["usage_state"] = "SETTLED"
    engine.touch(record)
    _gross2, new_payout, _fee2 = engine.recompute_listing_payout(listing)
    engine.touch(listing)
    engine.post_ledger(provider_of(listing) or listing["id"], "PAYOUT", "Listing",
                       record["id"], amount_usd=r2(new_payout - prior_payout))
    return success(ser_usage(record))
