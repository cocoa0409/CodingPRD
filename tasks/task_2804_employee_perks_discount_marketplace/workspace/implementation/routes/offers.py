"""Offers: drafting, review, pausing and resumption (PRD 3.5)."""
from flask import Blueprint

import auth
import clock
import db
import derive
import response
import support
import validate
from errors import ApiError

bp = Blueprint("offers", __name__)

SUSPENDED_MERCHANT_STATES = ("SUSPENDED", "TERMINATED")


def _offer_for(principal, row_id):
    row = support.fetch("offers", row_id)
    auth.check_merchant_scope(principal, row["merchant_id"])
    return row


def _agreement_of(offer):
    return db.agreements.get(offer["agreement_id"])


@bp.post("/perks/offers")
def create_offer():
    principal = auth.require(auth.MERCHANT)
    body = validate.json_body()
    agreement = support.resolve_fk(body, "agreement_id", "agreements")
    if agreement is not None:
        auth.check_merchant_scope(principal, agreement["merchant_id"])
    data = validate.fields(body, [
        {"name": "agreement_id", "type": "str", "required": True},
        {"name": "title", "type": "str", "required": True, "min_len": 1, "max_len": 160},
        {"name": "discount_type", "type": "enum", "required": True,
         "values": ["PERCENT", "FIXED"]},
        {"name": "discount_value_bps", "type": "int", "min": 100, "max": 7000},
        {"name": "discount_value_cents", "type": "int", "min": 100, "max": 500000},
        {"name": "min_spend_cents", "type": "int", "min": 0, "max": 1000000,
         "default": 0},
        {"name": "region_codes", "type": "enum_list", "required": True,
         "values": validate.REGIONS, "min_len": 1},
        {"name": "window_start", "type": "datetime", "required": True},
        {"name": "window_end", "type": "datetime", "required": True},
        {"name": "inventory_limit", "type": "int", "min": 1, "max": 1000000},
        {"name": "per_member_limit", "type": "int", "min": 1, "max": 50, "default": 1},
    ])
    validate.window(data["window_start"], data["window_end"])
    if data["discount_type"] == "PERCENT":
        if data["discount_value_bps"] is None or data["discount_value_cents"] is not None:
            raise ApiError("ERR_DISCOUNT_SHAPE_MISMATCH",
                           "A PERCENT offer carries discount_value_bps alone.")
    else:
        if data["discount_value_cents"] is None or data["discount_value_bps"] is not None:
            raise ApiError("ERR_DISCOUNT_SHAPE_MISMATCH",
                           "A FIXED offer carries discount_value_cents alone.")
    merchant = db.merchants.get(agreement["merchant_id"])
    footprint = merchant["region_codes"] if merchant is not None else []
    for region in data["region_codes"]:
        if region not in footprint:
            raise ApiError("ERR_REGION_NOT_COVERED",
                           "Region '%s' is outside the partner's footprint." % region)
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE",
                       "The governing agreement is not ACTIVE.")
    if merchant is None or merchant["status"] in SUSPENDED_MERCHANT_STATES:
        raise ApiError("ERR_MERCHANT_SUSPENDED", "The partner may not publish offers.")
    row = db.insert(db.offers, {
        "agreement_id": agreement["id"],
        # merchant_id and category are copied from the agreement; any supplied
        # value is ignored and neither is ever rewritten afterwards.
        "merchant_id": agreement["merchant_id"],
        "title": data["title"],
        "category": agreement["category"],
        "discount_type": data["discount_type"],
        "discount_value_bps": data["discount_value_bps"],
        "discount_value_cents": data["discount_value_cents"],
        "min_spend_cents": data["min_spend_cents"] if data["min_spend_cents"] is not None else 0,
        "region_codes": data["region_codes"],
        "window_start": data["window_start"],
        "window_end": data["window_end"],
        "inventory_limit": data["inventory_limit"],
        "per_member_limit": data["per_member_limit"] if data["per_member_limit"] is not None else 1,
        "status": "DRAFT",
        "review_note": None,
        "paused_reason": None,
        "expired_at": None,
    })
    return response.created(derive.offer_json(row))


@bp.get("/perks/offers/<row_id>")
def get_offer(row_id):
    principal = auth.require(auth.MERCHANT, auth.PARTNER_MANAGER, auth.PLATFORM_ADMIN,
                             auth.EMPLOYER_ADMIN, auth.EMPLOYEE)
    row = _offer_for(principal, row_id)
    return response.ok(derive.offer_json(row))


@bp.get("/perks/offers")
def list_offers():
    principal = auth.require(auth.MERCHANT, auth.PARTNER_MANAGER, auth.PLATFORM_ADMIN,
                             auth.EMPLOYER_ADMIN, auth.EMPLOYEE)
    agreement_id = support.arg("agreement_id")
    merchant_id = support.arg("merchant_id")
    category = support.arg("category")
    status = support.arg("status")
    region = support.arg("region_code")
    is_sold_out = validate.query_flag("sold_out")
    rows = []
    for row in db.offers.values():
        if principal.is_merchant and row["merchant_id"] != principal.user_id:
            continue
        if not support.matches(row, "agreement_id", agreement_id):
            continue
        if not support.matches(row, "merchant_id", merchant_id):
            continue
        if not support.matches(row, "category", category):
            continue
        if not support.matches(row, "status", status):
            continue
        if region is not None and region not in row["region_codes"]:
            continue
        if is_sold_out is not None and derive.sold_out(row) != is_sold_out:
            continue
        rows.append(row)
    return support.paged_sorted(rows, derive.offer_json)


@bp.post("/perks/offers/<row_id>/submit")
def submit_offer(row_id):
    principal = auth.require(auth.MERCHANT)
    row = _offer_for(principal, row_id)
    if row["status"] != "DRAFT":
        raise ApiError("ERR_OFFER_INVALID_STATE",
                       "Only a DRAFT offer can be submitted.")
    agreement = _agreement_of(row)
    if agreement is None or agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE",
                       "The governing agreement is not ACTIVE.")
    merchant = db.merchants.get(row["merchant_id"])
    if merchant is None or merchant["status"] in SUSPENDED_MERCHANT_STATES:
        raise ApiError("ERR_MERCHANT_SUSPENDED", "The partner may not submit offers.")
    row["status"] = "PENDING_REVIEW"
    db.touch(row)
    return response.ok(derive.offer_json(row))


@bp.post("/perks/offers/<row_id>/review")
def review_offer(row_id):
    auth.require(auth.PLATFORM_ADMIN)
    row = support.fetch("offers", row_id)
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "decision", "type": "enum", "required": True,
         "values": ["APPROVE", "REJECT"]},
        {"name": "review_note", "type": "str"},
    ])
    if row["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_OFFER_INVALID_STATE",
                       "Only a PENDING_REVIEW offer can be reviewed.")
    if data["decision"] == "APPROVE":
        agreement = _agreement_of(row)
        if agreement is None or agreement["status"] != "ACTIVE":
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE",
                           "The governing agreement is not ACTIVE.")
        merchant = db.merchants.get(row["merchant_id"])
        if merchant is None or merchant["status"] != "ACTIVE":
            raise ApiError("ERR_MERCHANT_SUSPENDED", "The partner is not ACTIVE.")
        row["review_note"] = data["review_note"]
        row["status"] = "ACTIVE"
    else:
        # A rejection can always be recorded, even for a lapsed agreement.
        row["review_note"] = data["review_note"]
        row["status"] = "REJECTED"
    db.touch(row)
    return response.ok(derive.offer_json(row))


@bp.post("/perks/offers/<row_id>/pause")
def pause_offer(row_id):
    principal = auth.require(auth.MERCHANT, auth.PLATFORM_ADMIN)
    row = _offer_for(principal, row_id)
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "paused_reason", "type": "str", "required": True},
    ])
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_OFFER_INVALID_STATE", "Only an ACTIVE offer can be paused.")
    # Pausing does NOT void redemptions that are already PENDING.
    row["status"] = "PAUSED"
    row["paused_reason"] = data["paused_reason"]
    db.touch(row)
    return response.ok(derive.offer_json(row))


@bp.post("/perks/offers/<row_id>/resume")
def resume_offer(row_id):
    principal = auth.require(auth.MERCHANT)
    row = _offer_for(principal, row_id)
    if row["status"] != "PAUSED":
        raise ApiError("ERR_OFFER_INVALID_STATE", "Only a PAUSED offer can be resumed.")
    if row["window_end"] <= clock.now():
        raise ApiError("ERR_OFFER_INVALID_STATE",
                       "The offer's redemption window has already closed.")
    agreement = _agreement_of(row)
    if agreement is None or agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE",
                       "The governing agreement is not ACTIVE.")
    merchant = db.merchants.get(row["merchant_id"])
    if merchant is None or merchant["status"] != "ACTIVE":
        raise ApiError("ERR_MERCHANT_SUSPENDED", "The partner is not ACTIVE.")
    row["status"] = "ACTIVE"
    row["paused_reason"] = None
    db.touch(row)
    return response.ok(derive.offer_json(row))
