"""Marketing commitments, approval and recoupability (PRD section 3.4)."""

from flask import Blueprint, request

import db
import response
import serializers
import validation as v
from errors import ApiError
from middleware import authenticate, pagination, paginate, parse_body
from routes.common import (BUSINESS_AFFAIRS, LABEL_ADMIN, ROYALTY_ANALYST,
                           find_release, find_spend, require_separation)
from services import calculations, ledger, lookups

bp = Blueprint("marketing", __name__)

CATEGORIES = ("DIGITAL_ADS", "RADIO_PROMO", "VIDEO_PRODUCTION", "TOUR_SUPPORT",
              "PUBLICITY")
RECOUPABILITIES = ("FULLY_RECOUPABLE", "HALF_RECOUPABLE", "NON_RECOUPABLE")
PROMOTABLE = ("PLANNED", "RELEASED")


@bp.route("/marketing-spends", methods=["POST"])
def create_spend():
    authenticate([LABEL_ADMIN])
    body = parse_body()
    release_id = v.identifier(body, "release_id", required=True)
    category = v.enum(body, "category", CATEGORIES, required=True)
    amount_cents = v.integer(body, "amount_cents", required=True, minimum=1)
    vendor = v.text(body, "vendor", required=True, min_len=1, max_len=120)

    release = find_release(release_id)
    if release["status"] not in PROMOTABLE:
        raise ApiError("ERR_RELEASE_NOT_PROMOTABLE")

    record = db.base_record()
    record.update({
        "release_id": release_id,
        "category": category,
        "amount_cents": amount_cents,
        "vendor": vendor,
        "recoupability": calculations.RECOUPABILITY_BY_CATEGORY[category],
        "status": "DRAFT",
        "requested_by_user_id": None,
        "decided_by_user_id": None,
        "approved_at": None,
        "settled_amount_cents": None,
        "revision_note": None,
    })
    db.store.spends[record["id"]] = record
    return response.created(serializers.spend(record))


@bp.route("/marketing-spends/<record_id>", methods=["GET"])
def get_spend(record_id):
    authenticate([LABEL_ADMIN, ROYALTY_ANALYST, BUSINESS_AFFAIRS])
    return response.ok(serializers.spend(find_spend(record_id)))


@bp.route("/marketing-spends", methods=["GET"])
def list_spends():
    authenticate([LABEL_ADMIN, ROYALTY_ANALYST, BUSINESS_AFFAIRS])
    limit, offset = pagination()
    records = db.ordered(list(db.store.spends.values()))
    for key in ("release_id", "category", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            records = [r for r in records if r[key] == wanted]
    page, total = paginate(records, limit, offset)
    return response.collection(
        [serializers.spend(r) for r in page], limit, offset, total)


@bp.route("/marketing-spends/<record_id>/submit", methods=["POST"])
def submit_spend(record_id):
    caller = authenticate([LABEL_ADMIN])
    spend = find_spend(record_id)
    body = parse_body()
    amount_cents = v.integer(body, "amount_cents", required=False, minimum=1)
    category = v.enum(body, "category", CATEGORIES, required=False)
    if spend["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_SPEND_STATE")
    release = db.store.releases.get(spend["release_id"])
    if release is None or release["status"] not in PROMOTABLE:
        raise ApiError("ERR_RELEASE_NOT_PROMOTABLE")

    from_revision = spend["status"] == "REVISION_REQUESTED"
    if amount_cents is not None:
        spend["amount_cents"] = amount_cents
    if category is not None:
        spend["category"] = category
    if amount_cents is not None or category is not None:
        spend["recoupability"] = \
            calculations.RECOUPABILITY_BY_CATEGORY[spend["category"]]
    spend["status"] = "SUBMITTED"
    spend["requested_by_user_id"] = caller.user_id
    if from_revision:
        spend["revision_note"] = None
    db.touch(spend)
    return response.ok(serializers.spend(spend))


@bp.route("/marketing-spends/<record_id>/decide", methods=["POST"])
def decide_spend(record_id):
    caller = authenticate([BUSINESS_AFFAIRS])
    spend = find_spend(record_id)
    body = parse_body()
    decision = v.enum(body, "decision", ("APPROVE", "REJECT", "REQUEST_REVISION"),
                      required=True)
    override = v.enum(body, "recoupability_override", RECOUPABILITIES,
                      required=False)
    revision_note = v.text(body, "revision_note",
                           required=(decision == "REQUEST_REVISION"),
                           min_len=1, max_len=None)

    if spend["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_SPEND_STATE")

    release = db.store.releases.get(spend["release_id"])
    deal = lookups.deal_of_spend(spend) if release is not None else None
    if decision == "APPROVE":
        if deal is None or deal["status"] != "EXECUTED":
            raise ApiError("ERR_INVALID_DEAL_STATE")
        if release["status"] not in PROMOTABLE:
            raise ApiError("ERR_RELEASE_NOT_PROMOTABLE")

    require_separation(caller, spend.get("requested_by_user_id"))

    if decision == "APPROVE":
        committed = ledger.committed_marketing(deal)
        if committed + (spend["amount_cents"] or 0) > \
                (deal["marketing_budget_cents"] or 0):
            raise ApiError("ERR_MARKETING_BUDGET_EXCEEDED")
        spend["status"] = "APPROVED"
        spend["approved_at"] = db.iso_instant(db.store.now())
        if override is not None:
            spend["recoupability"] = override
        spend["decided_by_user_id"] = caller.user_id
        db.touch(spend)
        ledger.recompute_marketing_committed(deal)
        db.touch(deal)
    elif decision == "REJECT":
        spend["status"] = "REJECTED"
        spend["decided_by_user_id"] = caller.user_id
        db.touch(spend)
    else:
        spend["status"] = "REVISION_REQUESTED"
        spend["revision_note"] = revision_note
        spend["decided_by_user_id"] = caller.user_id
        db.touch(spend)
    return response.ok(serializers.spend(spend))


@bp.route("/marketing-spends/<record_id>/settle", methods=["POST"])
def settle_spend(record_id):
    authenticate([LABEL_ADMIN])
    spend = find_spend(record_id)
    body = parse_body()
    settled = v.integer(body, "settled_amount_cents", required=True, minimum=0)
    if spend["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_SPEND_STATE")
    if settled > (spend["amount_cents"] or 0):
        v.bad("settled_amount_cents", "may not exceed the approved amount.")
    deal = lookups.deal_of_spend(spend)
    if deal is not None:
        projected = ledger.committed_marketing(
            deal, exclude_spend_id=spend["id"], override=settled)
        if projected > (deal["marketing_budget_cents"] or 0):
            raise ApiError("ERR_MARKETING_BUDGET_EXCEEDED")
    spend["status"] = "SETTLED"
    spend["settled_amount_cents"] = settled
    db.touch(spend)
    if deal is not None:
        ledger.recompute_marketing_committed(deal)
        db.touch(deal)
    return response.ok(serializers.spend(spend))
