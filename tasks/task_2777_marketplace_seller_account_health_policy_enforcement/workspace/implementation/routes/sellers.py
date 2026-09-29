"""Seller registration, reads and funds credits (PRD 3.1, 3.9)."""

from flask import Blueprint

import clock
import constants as C
import db
import guards
import middleware as mw
import response
import serializers as ser
import validators as v
from errors import ApiError
from services import calc, notify, posture

bp = Blueprint("sellers", __name__)


def _detect_related_accounts(candidate):
    """PRD 3.1: score the candidate against every pre-existing seller."""
    minted = []
    for incumbent in db.sorted_rows(db.SELLERS):
        score, signals = calc.confidence(candidate, incumbent)
        if score < C.RELATED_LINK_MIN_SCORE:
            continue
        link = db.new_row(
            "link",
            candidate_seller_id=candidate["id"],
            matched_seller_id=incumbent["id"],
            matched_signals=signals,
            confidence_score=score,
            matched_seller_state_at_detection=incumbent["enforcement_state"],
            state="DETECTED",
            detected_at=clock.now(),
            adjudicated_by_user_id=None,
            adjudication_note=None,
        )
        db.RELATED_ACCOUNT_LINKS[link["id"]] = link
        minted.append((link, incumbent))
    return minted


def _top_link(minted):
    """Rank by confidence_score descending, ties by the incumbent's created_at."""
    ranked = sorted(
        minted,
        key=lambda pair: (-pair[0]["confidence_score"], pair[1]["created_at"],
                          pair[1]["_seq"]),
    )
    return ranked[0][0] if ranked else None


@bp.post("/sellers")
@mw.require(C.ROLE_ANONYMOUS)
def register_seller():
    data = v.body()
    legal_name = v.req_str(data, "legal_name", 1, 200)
    if legal_name.strip() == "":
        v.bad("'legal_name' must be non-empty after trimming.")
    email = v.req_str(data, "email", 1, None)
    if email.count("@") != 1:
        v.bad("'email' must contain exactly one at-sign.")
    tax_id_hash = v.req_str(data, "tax_id_hash", 4, 64)
    payout_bank_token = v.req_str(data, "payout_bank_token", 4, 64)
    address_fingerprint = v.req_str(data, "address_fingerprint", 4, 64)
    device_fingerprint = v.opt_str(data, "device_fingerprint", 4, 64)

    lowered = email.lower()
    for existing in db.SELLERS.values():
        if existing["email"].lower() == lowered:
            raise ApiError("ERR_DUPLICATE_SELLER_EMAIL")

    seller = db.new_row(
        "seller",
        legal_name=legal_name,
        email=email,
        email_domain=email.split("@", 1)[1].lower(),
        tax_id_hash=tax_id_hash,
        payout_bank_token=payout_bank_token,
        address_fingerprint=address_fingerprint,
        device_fingerprint=device_fingerprint,
        root_seller_id=None,
        registration_risk_flag=False,
        enforcement_state="ACTIVE",
        disbursement_state="NORMAL",
        ban_reason=None,
        severity_points_balance=calc.ZERO2,
        health_score=None,
        metric_tier=None,
        available_balance_cents=0,
        held_balance_cents=0,
        lifetime_credited_cents=0,
        lifetime_debited_cents=0,
        open_defect_claim_units=0,
        reinstated_count=0,
    )

    minted = _detect_related_accounts(seller)
    db.SELLERS[seller["id"]] = seller

    top = _top_link(minted)
    if top is not None:
        seller["root_seller_id"] = top["matched_seller_id"]
        if (top["confidence_score"] >= C.RELATED_LINK_WATCH_SCORE
                and top["matched_seller_state_at_detection"] in ("BANNED", "SUSPENDED")):
            seller["registration_risk_flag"] = True

    posture.recompute(seller)

    if seller["registration_risk_flag"]:
        notify.emit(seller["id"], "REGISTRATION_FLAGGED", "RELATED_ACCOUNT_LINK",
                    top["id"])

    return response.one(seller, ser.seller, 201)


@bp.get("/sellers")
@mw.require(C.ROLE_INVESTIGATOR, C.ROLE_REVIEWER, C.ROLE_OFFICER)
def list_sellers():
    limit, offset = v.pagination()
    rows = db.sorted_rows(db.SELLERS)
    rows = _filter(rows, "root_seller_id")
    rows = _filter(rows, "enforcement_state")
    rows = _filter(rows, "disbursement_state")
    page, total = response.paginate(rows, limit, offset)
    return response.many(page, ser.seller, limit, offset, total)


def _filter(rows, field, query_name=None):
    from flask import request
    name = query_name or field
    if name not in request.args:
        return rows
    wanted = request.args.get(name)
    return [r for r in rows if r.get(field) == wanted]


@bp.get("/sellers/<seller_id>")
@mw.require(C.ROLE_SELLER, C.ROLE_INVESTIGATOR, C.ROLE_REVIEWER, C.ROLE_OFFICER)
def read_seller(seller_id):
    seller = guards.seller(seller_id)
    mw.ensure_owner(seller["id"])
    return response.one(seller, ser.seller, 200)


@bp.post("/sellers/<seller_id>/proceeds-credits")
@mw.require(C.ROLE_OFFICER)
def credit_proceeds(seller_id):
    seller = guards.seller(seller_id)
    data = v.body()
    amount = v.req_int(data, "amount_cents", minimum=1)
    v.opt_str(data, "external_reference")
    # PRD 2.5: crediting proceeds is one of the writes a ban does not block.
    db.set_field(seller, "available_balance_cents",
                 seller["available_balance_cents"] + amount)
    db.set_field(seller, "lifetime_credited_cents",
                 seller["lifetime_credited_cents"] + amount)
    db.mark_dirty(seller)
    return response.one(seller, ser.seller, 201)


@bp.get("/sellers/<seller_id>/metric-snapshots")
@mw.require(C.ROLE_SELLER, C.ROLE_INVESTIGATOR, C.ROLE_OFFICER)
def list_seller_snapshots(seller_id):
    seller = guards.seller(seller_id)
    mw.ensure_owner(seller["id"])
    limit, offset = v.pagination()
    rows = sorted(
        [r for r in db.METRIC_SNAPSHOTS.values() if r["seller_id"] == seller["id"]],
        key=lambda r: (_desc(r["window_end"]), r["created_at"], r["_seq"]),
    )
    page, total = response.paginate(rows, limit, offset)
    return response.many(page, ser.snapshot, limit, offset, total)


def _desc(value):
    """Sort key helper: descending on a datetime while keeping ascending ties."""
    return -value.timestamp()


@bp.get("/sellers/<seller_id>/listings")
@mw.require(C.ROLE_SELLER, C.ROLE_INVESTIGATOR, C.ROLE_OFFICER)
def list_seller_listings(seller_id):
    seller = guards.seller(seller_id)
    mw.ensure_owner(seller["id"])
    limit, offset = v.pagination()
    rows = _filter(db.listings_of(seller["id"]), "state")
    page, total = response.paginate(rows, limit, offset)
    return response.many(page, ser.listing, limit, offset, total)


@bp.get("/sellers/<seller_id>/notifications")
@mw.require(C.ROLE_SELLER, C.ROLE_REVIEWER, C.ROLE_OFFICER)
def list_seller_notifications(seller_id):
    seller = guards.seller(seller_id)
    mw.ensure_owner(seller["id"])
    limit, offset = v.pagination()
    rows = sorted(
        [r for r in db.NOTIFICATIONS.values() if r["seller_id"] == seller["id"]],
        key=lambda r: (_desc(r["sent_at"]), r["created_at"], r["_seq"]),
    )
    rows = _filter(rows, "template_code")
    rows = _filter(rows, "state")
    page, total = response.paginate(rows, limit, offset)
    return response.many(page, ser.notification, limit, offset, total)
