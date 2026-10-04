"""Secure data shares and consumer consumption attribution."""
from decimal import Decimal

from flask import Blueprint, g, request

from db import db, find
from auth import authorize
from errors import err
from response import success, paged, sort_by_created, pagination
from serializers import share as ser_share, share_usage as ser_usage
from services import engine
from util import now, r6, new_id

from routes.common import (body, req_str, req_int, req_dec, opt_enum, opt_int,
                           required, MISSING, require_provider_ownership)

bp = Blueprint("shares", __name__)


def load(share_id):
    record = find(db.shares, share_id)
    if record is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "DataShare not found.")
    return record


def validate_consumers(provider_account_id, consumer_ids):
    for consumer_id in consumer_ids:
        if find(db.accounts, consumer_id) is None:
            raise err("ERR_REFERENCE_INVALID",
                      "consumer_account_ids contains an unknown account.")
        if consumer_id == provider_account_id:
            raise err("ERR_SHARE_SELF_CONSUMPTION",
                      "A share may not list its own provider as a consumer.")


@bp.route("/v1/data-shares", methods=["POST"])
def create_share():
    authorize(g.role, ["ShareAdmin"])
    data = body()
    provider_id = req_str(data, "provider_account_id")
    provider = find(db.accounts, provider_id)
    if provider is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Account not found.")
    require_provider_ownership(provider_id)
    name = req_str(data, "name")
    objects_exposed = req_int(data, "objects_exposed")
    consumers = required(data, "consumer_account_ids")
    if not isinstance(consumers, list):
        raise err("ERR_INVALID_REQUEST", "consumer_account_ids must be an array.")
    if objects_exposed < 1:
        raise err("ERR_INVALID_REQUEST", "objects_exposed must be at least 1.")
    validate_consumers(provider_id, consumers)
    status = opt_enum(data, "status", ("DRAFT", "PUBLISHED", "SUSPENDED"), "DRAFT")
    for existing in engine.child_shares(provider_id):
        if existing["name"] == name:
            raise err("ERR_DUPLICATE_RESOURCE",
                      "DataShare.name must be unique within its provider account.")
    ts = now()
    record = {
        "id": new_id(),
        "provider_account_id": provider_id,
        "name": name,
        "objects_exposed": objects_exposed,
        "consumer_account_ids": list(consumers),
        "status": status,
        "consumer_query_count": 0,
        "consumer_credits": r6(0),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.shares.append(record)
    return success(ser_share(record), 201)


@bp.route("/v1/data-shares", methods=["GET"])
def list_shares():
    authorize(g.role, ["ShareAdmin", "PlatformOperator", "FinanceController", "DataEngineer"])
    items = sort_by_created(db.shares)
    provider_id = request.args.get("provider_account_id")
    status = request.args.get("status")
    if provider_id:
        items = [s for s in items if s["provider_account_id"] == provider_id]
    if status:
        items = [s for s in items if s["status"] == status]
    limit, offset = pagination()
    return paged([ser_share(s) for s in items], limit, offset)


@bp.route("/v1/data-shares/<share_id>", methods=["GET"])
def get_share(share_id):
    authorize(g.role, ["ShareAdmin", "PlatformOperator", "FinanceController", "DataEngineer"])
    return success(ser_share(load(share_id)))


@bp.route("/v1/data-shares/<share_id>", methods=["PATCH"])
def patch_share(share_id):
    authorize(g.role, ["ShareAdmin"])
    share = load(share_id)
    require_provider_ownership(share["provider_account_id"])
    data = body()
    objects_exposed = opt_int(data, "objects_exposed", None)
    consumers = data.get("consumer_account_ids", MISSING)
    if objects_exposed is not None:
        if objects_exposed < 1:
            raise err("ERR_INVALID_REQUEST", "objects_exposed must be at least 1.")
        share["objects_exposed"] = objects_exposed
    if consumers is not MISSING and consumers is not None:
        if not isinstance(consumers, list):
            raise err("ERR_INVALID_REQUEST", "consumer_account_ids must be an array.")
        validate_consumers(share["provider_account_id"], consumers)
        if share["status"] != "PUBLISHED":
            raise err("ERR_SHARE_NOT_PUBLISHED",
                      "A consumer list may only be amended on a PUBLISHED share.")
        share["consumer_account_ids"] = list(consumers)
    engine.touch(share)
    return success(ser_share(share))


@bp.route("/v1/data-shares/<share_id>/publish", methods=["POST"])
def publish_share(share_id):
    authorize(g.role, ["ShareAdmin"])
    share = load(share_id)
    require_provider_ownership(share["provider_account_id"])
    if share["status"] not in ("DRAFT", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "The share cannot be published from its current state.")
    validate_consumers(share["provider_account_id"], share["consumer_account_ids"])
    if share["objects_exposed"] < 1:
        raise err("ERR_INVALID_REQUEST", "objects_exposed must be at least 1.")
    share["status"] = "PUBLISHED"
    engine.touch(share)
    return success(ser_share(share))


@bp.route("/v1/data-shares/<share_id>/suspend", methods=["POST"])
def suspend_share(share_id):
    authorize(g.role, ["ShareAdmin"])
    share = load(share_id)
    require_provider_ownership(share["provider_account_id"])
    if share["status"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE", "Only a PUBLISHED share can be suspended.")
    share["status"] = "SUSPENDED"
    engine.touch(share)
    return success(ser_share(share))


@bp.route("/v1/data-shares/<share_id>/revoke", methods=["POST"])
def revoke_share(share_id):
    authorize(g.role, ["ShareAdmin"])
    share = load(share_id)
    require_provider_ownership(share["provider_account_id"])
    data = body()
    if share["status"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE", "Only a PUBLISHED share can be revoked.")
    if any(event["attributed_row_count"] > 0
           for event in engine.child_usage_events(share["id"])):
        raise err("ERR_INVALID_STATE",
                  "A share with attributed rows cannot be revoked.")
    account = find(db.accounts, share["provider_account_id"])
    expected = data.get("expected_account_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST", "expected_account_version is required.")
    if account is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Account not found.")
    if expected != account["version"]:
        raise err("ERR_STALE_VERSION", "The account version has advanced.")

    share["status"] = "DRAFT"
    share["consumer_query_count"] = 0
    share["consumer_credits"] = r6(0)
    engine.touch(share)
    for listing in engine.child_listings(share["id"]):
        if listing["listing_state"] == "PUBLISHED":
            listing["listing_state"] = "WITHDRAWN"
            engine.touch(listing)
    engine.touch(account)
    return success(ser_share(share))


@bp.route("/v1/shares/<share_id>/usage-events", methods=["POST"])
def create_usage_event(share_id):
    authorize(g.role, ["DataEngineer", "ShareAdmin"])
    share = load(share_id)
    data = body()
    consumer_id = req_str(data, "consumer_account_id")
    consumer = find(db.accounts, consumer_id)
    if consumer is None:
        raise err("ERR_REFERENCE_INVALID", "consumer_account_id does not resolve.")
    if consumer_id == share["provider_account_id"]:
        raise err("ERR_SHARE_SELF_CONSUMPTION",
                  "A consumer may not be the share's provider.")
    credits = req_dec(data, "credits_consumed")
    row_count = req_int(data, "row_count")
    if credits <= 0:
        raise err("ERR_INVALID_REQUEST", "credits_consumed must be strictly positive.")
    if row_count < 0:
        raise err("ERR_INVALID_REQUEST", "row_count must be non-negative.")
    if share["status"] != "PUBLISHED":
        raise err("ERR_SHARE_NOT_PUBLISHED",
                  "A share must be PUBLISHED to admit consumer attribution.")

    ts = now()
    record = {
        "id": new_id(),
        "share_id": share_id,
        "consumer_account_id": consumer_id,
        "queried_at": ts,
        "credits_consumed": credits,
        "row_count": row_count,
        "attribution": "CONSUMER",
        "attributed_row_count": row_count,
        "credited_account_id": consumer_id,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.share_usage_events.append(record)
    engine.recompute_share(share)
    charged = engine.attribution_charged_credits(record)
    if charged > 0:
        engine.post_ledger(consumer_id, "SHARE_CONSUMPTION", "ShareUsageEvent",
                           record["id"], amount_credits=charged)
    return success(ser_usage(record), 201)


@bp.route("/v1/shares/<share_id>/usage-events", methods=["GET"])
def list_share_usage(share_id):
    authorize(g.role, ["DataEngineer", "ShareAdmin", "FinanceController", "PlatformOperator"])
    share = load(share_id)
    items = sorted(engine.child_usage_events(share["id"]),
                   key=lambda e: (e["created_at"], e["id"]))
    consumer_id = request.args.get("consumer_account_id")
    if consumer_id:
        items = [e for e in items if e["consumer_account_id"] == consumer_id]
    limit, offset = pagination()
    return paged([ser_usage(e) for e in items], limit, offset)


@bp.route("/v1/share-usage-events", methods=["GET"])
def list_all_usage():
    authorize(g.role, ["PlatformOperator", "FinanceController", "ShareAdmin", "DataEngineer"])
    items = sort_by_created(db.share_usage_events)
    share_id = request.args.get("share_id")
    consumer_id = request.args.get("consumer_account_id")
    attribution = request.args.get("attribution")
    if share_id:
        items = [e for e in items if e["share_id"] == share_id]
    if consumer_id:
        items = [e for e in items if e["consumer_account_id"] == consumer_id]
    if attribution:
        items = [e for e in items if e["attribution"] == attribution]
    limit, offset = pagination()
    return paged([ser_usage(e) for e in items], limit, offset)


@bp.route("/v1/share-usage-events/<event_id>", methods=["GET"])
def get_usage(event_id):
    authorize(g.role, ["PlatformOperator", "FinanceController", "ShareAdmin", "DataEngineer"])
    record = find(db.share_usage_events, event_id)
    if record is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "ShareUsageEvent not found.")
    return success(ser_usage(record))
