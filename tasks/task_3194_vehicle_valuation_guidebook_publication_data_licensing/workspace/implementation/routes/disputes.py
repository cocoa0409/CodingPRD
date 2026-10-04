"""Dispute endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import DB
from errors import (
    not_found, invalid_input, invalid_state, duplicate_dispute,
    unauthorized,
)
from middleware import require_roles
from response import success
from services.calculations import compute_dispute_credit
from services.entity import stamp_new, touch


bp = Blueprint("disputes", __name__)

REASON_CODES = ("WRONG_CONDITION", "STALE_DATA", "MISSING_OPTIONS")


def _dispute_view(d):
    return {
        "id": d["id"],
        "offer_id": d["offer_id"],
        "reason_code": d["reason_code"],
        "status": d["status"],
        "credit_cents": d.get("credit_cents"),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


@bp.route("/disputes", methods=["POST"])
def create_dispute():
    role, user_id = require_roles("Consumer")
    body = request.get_json(silent=True) or {}
    offer_id = body.get("offer_id")
    reason_code = body.get("reason_code")

    offer = DB.cash_offers.get(offer_id) if isinstance(offer_id, str) else None
    if offer is None:
        raise not_found("offer not found")

    # Priority 5: state — dispute requires REDEEMED offer (for ADJUSTED to be
    # possible). PRD §3.7: "The offer must be REDEEMED for an adjusted
    # resolution to be possible". A VOID / QUOTED / INSPECTED / EXPIRED offer
    # rejects dispute creation with ERR_INVALID_STATE.
    if offer["status"] != "REDEEMED":
        raise invalid_state("dispute requires a REDEEMED offer")

    # Priority 16: at most one OPEN dispute per offer
    for d in DB.disputes.values():
        if d["offer_id"] == offer_id and d["status"] == "OPEN":
            raise duplicate_dispute("an OPEN dispute already exists for this offer")

    if reason_code not in REASON_CODES:
        raise invalid_input("reason_code invalid")

    d = stamp_new({
        "offer_id": offer_id,
        "reason_code": reason_code,
        "status": "OPEN",
        "credit_cents": None,
    })
    DB.disputes[d["id"]] = d
    return success(_dispute_view(d), 201)


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    require_roles("ValuationAdmin", "Consumer", "DealerPartner")
    items = list(DB.disputes.values())
    offer_id = request.args.get("offer_id")
    status_filter = request.args.get("status")
    if offer_id:
        items = [d for d in items if d["offer_id"] == offer_id]
    if status_filter:
        items = [d for d in items if d["status"] == status_filter]
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda d: d["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success([_dispute_view(d) for d in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)


@bp.route("/disputes/<dispute_id>", methods=["GET"])
def get_dispute(dispute_id):
    require_roles("ValuationAdmin", "Consumer")
    d = DB.disputes.get(dispute_id)
    if d is None:
        raise not_found("dispute not found")
    return success(_dispute_view(d), 200)


@bp.route("/disputes/<dispute_id>/resolve", methods=["POST"])
def resolve_dispute(dispute_id):
    require_roles("ValuationAdmin")
    d = DB.disputes.get(dispute_id)
    if d is None:
        raise not_found("dispute not found")
    body = request.get_json(silent=True) or {}
    resolution = body.get("resolution")
    if d["status"] != "OPEN":
        raise invalid_state("dispute not OPEN")
    if resolution not in ("UPHELD", "ADJUSTED"):
        raise invalid_input("resolution must be UPHELD or ADJUSTED")
    if resolution == "UPHELD":
        d["status"] = "RESOLVED_UPHELD"
    else:
        # ADJUSTED requires the offer be REDEEMED
        offer = DB.cash_offers.get(d["offer_id"])
        if offer is None or offer["status"] != "REDEEMED":
            raise invalid_state("offer not REDEEMED")
        edition = DB.editions.get(offer["edition_id"])
        retail = edition["retail_cents"] if edition else 0
        d["credit_cents"] = compute_dispute_credit(retail)
        d["status"] = "RESOLVED_ADJUSTED"
    touch(d)
    return success(_dispute_view(d), 200)


@bp.route("/disputes/<dispute_id>/withdraw", methods=["POST"])
def withdraw_dispute(dispute_id):
    role, user_id = require_roles("Consumer")
    d = DB.disputes.get(dispute_id)
    if d is None:
        raise not_found("dispute not found")
    if d["status"] != "OPEN":
        raise invalid_state("dispute not OPEN")
    # Ownership: the acting consumer must own the referenced offer
    offer = DB.cash_offers.get(d["offer_id"])
    if offer is None or offer["consumer_id"] != user_id:
        raise unauthorized("consumer does not own the disputed offer")
    d["status"] = "WITHDRAWN"
    touch(d)
    return success(_dispute_view(d), 200)
