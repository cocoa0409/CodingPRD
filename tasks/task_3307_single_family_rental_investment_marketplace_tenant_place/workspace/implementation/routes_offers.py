"""Routes: offers and escrows (negotiation, OCC, signing, funding, closing cascade)."""
from datetime import timedelta

from flask import Blueprint, request

import errors
import middleware as mw
import response as resp
import services as svc
from db import store, _parse_iso, fmt_iso
from helpers import (body, new_id, stamp_new, touch, pagination_args, paginate,
                     req_str, req_int, req_enum)

bp = Blueprint("offers", __name__)


# ---------------- Offers ----------------

@bp.post("/listings/<lid>/offers")
def create_offer(lid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "Buyer")
    listing = store.listings.get(lid)
    if not listing:
        raise errors.not_found("Listing not found")
    data = body()
    buyer_id = req_str(data, "buyer_id")
    if ctx.user_id != buyer_id:
        raise errors.forbidden("buyer_id must be the acting buyer's own id")
    buyer = store.buyers.get(buyer_id)
    if not buyer:
        raise errors.not_found("Buyer not found")
    # OCC (priority: stale-version reported before any business-rule failure)
    expected = data.get("expected_listing_version")
    if expected is None:
        raise errors.validation("expected_listing_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.validation("expected_listing_version must be an integer")
    if expected != listing["version"]:
        raise errors.stale_listing()
    amount = req_int(data, "amount_cents")
    if amount <= 0:
        raise errors.validation("amount_cents must be > 0")
    earnest = req_int(data, "earnest_money_cents")
    if earnest < 0:
        raise errors.validation("earnest_money_cents must be >= 0")
    fin = req_enum(data, "financing_type", {"CASH", "CONVENTIONAL", "HARD_MONEY"})
    offer = stamp_new({
        "id": new_id(),
        "listing_id": lid,
        "buyer_id": buyer_id,
        "amount_cents": amount,
        "earnest_money_cents": earnest,
        "financing_type": fin,
        "status": "DRAFT",
        "round_number": 1,
        "is_out_of_state": buyer["buyer_state"] != listing["listing_state"],
        "expires_at": None,
    })
    store.offers[offer["id"]] = offer
    touch(listing)  # offer creation bumps the listing version
    return resp.created(offer)


@bp.get("/offers")
def list_offers():
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Seller", "Buyer")
    svc.offer_expiry_sweep()
    limit, offset = pagination_args()
    items = list(store.offers.values())
    for key in ("listing_id", "buyer_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [o for o in items if str(o.get(key)) == v]
    page, total = paginate(items, limit, offset)
    return resp.listing_ok(page, limit, offset, total)


@bp.get("/offers/<oid>")
def get_offer(oid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Seller", "Buyer")
    offer = store.offers.get(oid)
    if not offer:
        raise errors.not_found("Offer not found")
    svc.offer_expiry_sweep()
    offer = store.offers[oid]
    return resp.ok(offer)


def _funds_checks(offer, buyer):
    if offer["earnest_money_cents"] < svc.EARNEST_MIN_CENTS:
        raise errors.insufficient_funds("earnest_money_cents below EARNEST_MIN_CENTS")
    if offer["financing_type"] == "CASH" and buyer["proof_of_funds_cents"] < offer["amount_cents"]:
        raise errors.insufficient_funds("CASH offer exceeds proof of funds")


@bp.post("/offers/<oid>/transition")
def offer_transition(oid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "Buyer", "Seller")
    data = body()
    action = data.get("action")
    # role-per-action (priority 2)
    if action in ("SUBMIT", "RESUBMIT", "WITHDRAW"):
        mw.require_role(ctx, "Buyer")
    elif action in ("COUNTER", "ACCEPT"):
        mw.require_role(ctx, "Seller")
    elif action == "DECLINE":
        mw.require_role(ctx, "Buyer", "Seller")
    offer = store.offers.get(oid)
    if not offer:
        raise errors.not_found("Offer not found")
    svc.offer_expiry_sweep()
    offer = store.offers[oid]
    listing = store.listings[offer["listing_id"]]
    buyer = store.buyers[offer["buyer_id"]]
    cur = offer["status"]

    if action == "SUBMIT":
        if cur != "DRAFT":
            raise errors.invalid_state(f"SUBMIT not defined from {cur}")
        mw.require_owner(ctx, offer["buyer_id"])
        if listing["status"] not in ("LISTED", "OFFER_PENDING"):
            raise errors.precondition("Listing must be LISTED or OFFER_PENDING")
        _funds_checks(offer, buyer)
        offer["status"] = "SUBMITTED"
        offer["expires_at"] = fmt_iso(store.clock + timedelta(hours=svc.OFFER_TTL_HOURS))
        touch(offer)
        if listing["status"] == "LISTED":
            listing["status"] = "OFFER_PENDING"
            touch(listing)
    elif action == "COUNTER":
        if cur != "SUBMITTED":
            raise errors.invalid_state(f"COUNTER not defined from {cur}")
        mw.require_owner(ctx, listing["seller_id"])
        counter = data.get("counter_amount_cents")
        if isinstance(counter, bool) or not isinstance(counter, int) or counter <= 0:
            raise errors.validation("counter_amount_cents must be > 0")
        offer["status"] = "COUNTERED"
        offer["round_number"] = int(offer["round_number"]) + 1
        touch(offer)
    elif action == "RESUBMIT":
        if cur != "COUNTERED":
            raise errors.invalid_state(f"RESUBMIT not defined from {cur}")
        mw.require_owner(ctx, offer["buyer_id"])
        if offer["round_number"] >= svc.MAX_NEGOTIATION_ROUNDS:
            raise errors.negotiation_exceeded()
        if listing["status"] not in ("LISTED", "OFFER_PENDING"):
            raise errors.precondition("Listing must be LISTED or OFFER_PENDING")
        amount = data.get("amount_cents")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise errors.validation("amount_cents must be > 0")
        offer["amount_cents"] = amount
        _funds_checks(offer, buyer)
        offer["status"] = "SUBMITTED"
        offer["expires_at"] = fmt_iso(store.clock + timedelta(hours=svc.OFFER_TTL_HOURS))
        touch(offer)
        if listing["status"] == "LISTED":
            listing["status"] = "OFFER_PENDING"
            touch(listing)
    elif action == "ACCEPT":
        if cur not in ("SUBMITTED", "COUNTERED"):
            raise errors.invalid_state(f"ACCEPT not defined from {cur}")
        mw.require_owner(ctx, listing["seller_id"])
        # temporal check (priority 9): offer not past expires_at at accept
        if cur == "SUBMITTED" and offer.get("expires_at") and _parse_iso(offer["expires_at"]) <= store.clock:
            offer["status"] = "EXPIRED"
            touch(offer)
            svc._maybe_listing_fall_back(listing["id"])
            raise errors.expired("Offer has expired")
        if any(o["listing_id"] == listing["id"] and o["status"] == "ACCEPTED" for o in store.offers.values()):
            raise errors.precondition("Another offer is already ACCEPTED")
        offer["status"] = "ACCEPTED"
        touch(offer)
        svc.offer_accept_cascade(offer)
    elif action == "DECLINE":
        if ctx.role == "Buyer":
            if cur != "COUNTERED":
                raise errors.invalid_state(f"Buyer DECLINE not defined from {cur}")
            mw.require_owner(ctx, offer["buyer_id"])
        else:  # Seller
            if cur not in ("SUBMITTED", "COUNTERED"):
                raise errors.invalid_state(f"Seller DECLINE not defined from {cur}")
            mw.require_owner(ctx, listing["seller_id"])
        offer["status"] = "DECLINED"
        touch(offer)
        svc._maybe_listing_fall_back(listing["id"])
    elif action == "WITHDRAW":
        if cur not in ("DRAFT", "SUBMITTED", "COUNTERED"):
            raise errors.invalid_state(f"WITHDRAW not defined from {cur}")
        mw.require_owner(ctx, offer["buyer_id"])
        offer["status"] = "WITHDRAWN"
        touch(offer)
        svc._maybe_listing_fall_back(listing["id"])
    else:
        raise errors.invalid_state(f"Unknown or inapplicable action {action!r}")
    return resp.ok(offer)


@bp.get("/offers/<oid>/escrow")
def get_offer_escrow(oid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Seller", "Buyer", "EscrowOfficer")
    if oid not in store.offers:
        raise errors.not_found("Offer not found")
    items = [e for e in store.escrows.values() if e["offer_id"] == oid]
    limit, offset = pagination_args()
    page, total = paginate(items, limit, offset)
    return resp.listing_ok(page, limit, offset, total)


# ---------------- Escrows ----------------

@bp.post("/escrows/<eid>/sign")
def escrow_sign(eid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "Buyer")
    escrow = store.escrows.get(eid)
    if not escrow:
        raise errors.not_found("Escrow not found")
    offer = store.offers[escrow["offer_id"]]
    mw.require_owner(ctx, offer["buyer_id"])
    if escrow["status"] != "DOCS_SENT":
        raise errors.invalid_state(f"sign not defined from {escrow['status']}")
    data = body()
    expected = data.get("expected_escrow_version")
    if expected is None:
        raise errors.validation("expected_escrow_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.validation("expected_escrow_version must be an integer")
    if expected != escrow["version"]:
        raise errors.stale_escrow()
    if escrow["remote_signing_required"]:
        ref = data.get("remote_notarization_ref")
        if not isinstance(ref, str) or not ref.strip():
            raise errors.remote_signing()
    escrow["status"] = "SIGNED"
    escrow["signed_at"] = fmt_iso(store.clock)
    touch(escrow)
    return resp.ok(escrow)


@bp.post("/escrows/<eid>/fund")
def escrow_fund(eid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "Buyer")
    escrow = store.escrows.get(eid)
    if not escrow:
        raise errors.not_found("Escrow not found")
    offer = store.offers[escrow["offer_id"]]
    mw.require_owner(ctx, offer["buyer_id"])
    if escrow["status"] != "SIGNED":
        raise errors.invalid_state(f"fund not defined from {escrow['status']}")
    data = body()
    funded = data.get("funded_amount_cents")
    if isinstance(funded, bool) or not isinstance(funded, int):
        raise errors.validation("funded_amount_cents must be an integer")
    if funded != offer["amount_cents"]:
        raise errors.insufficient_funds("funded_amount_cents must equal the offer amount exactly")
    escrow["status"] = "FUNDED"
    escrow["funded_amount_cents"] = funded
    touch(escrow)
    return resp.ok(escrow)


@bp.post("/escrows/<eid>/transition")
def escrow_transition(eid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "EscrowOfficer")
    data = body()
    action = data.get("action")
    escrow = store.escrows.get(eid)
    if not escrow:
        raise errors.not_found("Escrow not found")
    cur = escrow["status"]

    if action == "SEND_DOCS":
        if cur != "OPENED":
            raise errors.invalid_state(f"SEND_DOCS not defined from {cur}")
        name = data.get("escrow_officer_name")
        if not isinstance(name, str) or not name.strip():
            raise errors.validation("escrow_officer_name is required")
        escrow["escrow_officer_name"] = name
        escrow["status"] = "DOCS_SENT"
        touch(escrow)
    elif action == "CLOSE":
        if cur != "FUNDED":
            raise errors.invalid_state(f"CLOSE not defined from {cur}")
        escrow["status"] = "CLOSED"
        touch(escrow)
        svc.escrow_close_cascade(escrow)
    elif action == "CANCEL":
        if cur not in ("OPENED", "DOCS_SENT", "SIGNED"):
            raise errors.invalid_state(f"CANCEL not defined from {cur}")
        escrow["status"] = "CANCELLED"
        touch(escrow)
        svc.escrow_cancel_cascade(escrow)
    else:
        raise errors.invalid_state(f"Unknown or inapplicable action {action!r}")
    return resp.ok(escrow)
