"""Offer routes: register, get (lazy expiry), counter, reoffer, accept, reject, withdraw, list."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from store import db
from response import ok, ok_list, ApiError, err_not_found, err_invalid_request
from helpers import new_record, touch, paginate, sort_by_created, reevaluate
import views

bp = Blueprint("offers", __name__)


def get_offer_or_404(oid):
    o = db["offers"].get(oid)
    if not o:
        raise err_not_found("Offer not found")
    return o


def get_office_or_404(office_id):
    o = db["offices"].get(office_id)
    if not o:
        raise err_not_found("Office not found")
    return o


@bp.route("/offices/<officeId>/offers", methods=["POST"])
def create_offer(officeId):
    require_roles("Agent", "ManagingBroker")
    get_office_or_404(officeId)
    body = request.get_json(silent=True) or {}
    listing_reference = body.get("listing_reference")
    buyer_name = body.get("buyer_name")
    price = body.get("offer_price_cents")
    if not isinstance(listing_reference, str) or not listing_reference:
        raise err_invalid_request("listing_reference is required")
    if not isinstance(buyer_name, str) or not buyer_name:
        raise err_invalid_request("buyer_name is required")
    if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
        raise err_invalid_request("offer_price_cents must be a positive integer")
    rec = new_record()
    rec.update({
        "office_id": officeId,
        "listing_reference": listing_reference,
        "buyer_name": buyer_name,
        "offer_price_cents": price,
        "offer_round": 1,
        "status": "OFFERED",
    })
    db["offers"][rec["id"]] = rec
    return ok(views.offer_view(rec), 201)


@bp.route("/offers/<offerId>", methods=["GET"])
def get_offer(offerId):
    require_roles(*ALL_ROLES)
    reevaluate()
    o = get_offer_or_404(offerId)
    return ok(views.offer_view(o))


@bp.route("/offers", methods=["GET"])
def list_offers():
    require_roles(*ALL_ROLES)
    reevaluate()
    items = list(db["offers"].values())
    args = request.args
    if args.get("office_id") is not None:
        items = [o for o in items if o["office_id"] == args.get("office_id")]
    if args.get("status") is not None:
        items = [o for o in items if o["status"] == args.get("status")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.offer_view(o) for o in page], total, limit, offset)


@bp.route("/offers/<offerId>/counter", methods=["POST"])
def counter_offer(offerId):
    require_roles("Agent")
    o = get_offer_or_404(offerId)
    if o["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Offer is not OFFERED")
    o["status"] = "COUNTERED"
    touch(o)
    return ok(views.offer_view(o))


@bp.route("/offers/<offerId>/reoffer", methods=["POST"])
def reoffer(offerId):
    require_roles("Agent")
    o = get_offer_or_404(offerId)
    if o["status"] != "COUNTERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Offer is not COUNTERED")
    if o["offer_round"] >= 4:
        raise ApiError("ERR_NEGOTIATION_EXHAUSTED", 409, "Maximum negotiation rounds reached")
    o["offer_round"] += 1
    o["status"] = "OFFERED"
    touch(o)
    return ok(views.offer_view(o))


@bp.route("/offers/<offerId>/accept", methods=["POST"])
def accept_offer(offerId):
    uid, _role = require_roles("Agent")
    reevaluate()  # may expire the offer first
    o = get_offer_or_404(offerId)
    if o["status"] == "EXPIRED":
        raise ApiError("ERR_OFFER_EXPIRED", 409, "Offer TTL has elapsed")
    if o["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Offer is not OFFERED")
    body = request.get_json(silent=True) or {}
    # PRD §3.5: gross_commission_cents is the acceptance-time input; the
    # accepting agent (X-User-ID) is the agent on the seeded transaction.
    gci = body.get("gross_commission_cents")
    if not isinstance(gci, int) or isinstance(gci, bool) or gci <= 0:
        raise err_invalid_request("gross_commission_cents must be a positive integer")
    o["status"] = "ACCEPTED"
    touch(o)
    txn = new_record()
    txn.update({
        "office_id": o["office_id"],
        "listing_agent_id": uid,
        "selling_agent_id": uid,
        "offer_id": o["id"],
        "sale_price_cents": o["offer_price_cents"],
        "gross_commission_cents": gci,
        "status": "UNDER_CONTRACT",
        "closed_at": None,
        "request_close_at": None,
    })
    db["transactions"][txn["id"]] = txn
    return ok(views.offer_view(o))


@bp.route("/offers/<offerId>/reject", methods=["POST"])
def reject_offer(offerId):
    require_roles("Agent")
    o = get_offer_or_404(offerId)
    if o["status"] not in ("OFFERED", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Offer cannot be rejected from its state")
    o["status"] = "REJECTED"
    touch(o)
    return ok(views.offer_view(o))


@bp.route("/offers/<offerId>/withdraw", methods=["POST"])
def withdraw_offer(offerId):
    require_roles("Agent")
    o = get_offer_or_404(offerId)
    if o["status"] != "COUNTERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Offer is not COUNTERED")
    o["status"] = "WITHDRAWN"
    touch(o)
    return ok(views.offer_view(o))
