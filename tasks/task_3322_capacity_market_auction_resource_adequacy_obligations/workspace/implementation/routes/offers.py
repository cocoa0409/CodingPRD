"""Offers and mitigation reviews routes."""
from flask import Blueprint, request

from db import db
from middleware import require_roles, require_any
from response import success_object, success_list
from util import (base_entity, touch, dec, require_fields, is_number, get_body,
                  strip_internal, paginate, sort_created, stamp)
from errors import (err_not_found, err_invalid_request, err_invalid_state,
                    err_ownership, err_owner_suspended, err_offer_exceeds_ucap,
                    err_stale_version)

bp = Blueprint("offers", __name__)


def _serialize(o):
    return strip_internal(o)


def _serialize_review(r):
    return strip_internal(r)


@bp.route("/capacity-market/offers", methods=["POST"])
def create_offer():
    user_id, role = require_roles("ResourceOwner")
    body = get_body()
    require_fields(body, ["resource_id", "auction_run_id", "offer_mw", "offer_price_per_mw_day"])
    resource = db.resources.get(body["resource_id"])
    if resource is None:
        raise err_not_found("resource not found")
    run = db.auction_runs.get(body["auction_run_id"])
    if run is None:
        raise err_not_found("auction run not found")
    # state gates
    if run["status"] != "OPEN":
        raise err_invalid_state("auction run is not OPEN")
    if resource["status"] != "ACCREDITED":
        raise err_invalid_state("resource is not ACCREDITED")
    # ownership
    if user_id != resource["owner_id"]:
        raise err_ownership()
    # owner standing
    owner = db.owners.get(resource["owner_id"])
    if owner and owner["status"] == "SUSPENDED":
        raise err_owner_suspended()
    # business: headroom
    offer_mw = body["offer_mw"]
    price = body["offer_price_per_mw_day"]
    if not is_number(offer_mw) or dec(offer_mw) <= 0:
        raise err_invalid_request("offer_mw must be > 0")
    if not is_number(price) or dec(price) < 0:
        raise err_invalid_request("offer_price_per_mw_day must be >= 0")
    already = dec(0)
    for o in db.offers.values():
        if (o["resource_id"] == resource["id"] and o["auction_run_id"] == run["id"]
                and o["status"] in ("SUBMITTED", "SEALED")):
            already += dec(o["offer_mw"])
    if dec(offer_mw) > dec(resource["accredited_ucap_mw"]) - already:
        raise err_offer_exceeds_ucap()

    o = base_entity()
    o.update({
        "resource_id": resource["id"],
        "auction_run_id": run["id"],
        "offer_mw": dec(offer_mw),
        "offer_price_per_mw_day": dec(price),
        "mitigated_cap_per_mw_day": None,
        "mitigation_status": "UNREVIEWED",
        "effective_price_per_mw_day": None,
        "cleared_mw": 0,
        "status": "SUBMITTED",
    })
    db.offers[o["id"]] = o
    return success_object(_serialize(o), 201)


@bp.route("/capacity-market/offers", methods=["GET"])
def list_offers():
    require_any()
    items = list(db.offers.values())
    for key in ("resource_id", "auction_run_id", "status"):
        v = request.args.get(key)
        if v:
            items = [o for o in items if o.get(key) == v]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize(o) for o in page], limit, offset, total)


@bp.route("/capacity-market/offers/<offer_id>", methods=["GET"])
def get_offer(offer_id):
    require_any()
    o = db.offers.get(offer_id)
    if o is None:
        raise err_not_found("offer not found")
    return success_object(_serialize(o))


@bp.route("/capacity-market/offers/<offer_id>/withdraw", methods=["POST"])
def withdraw_offer(offer_id):
    user_id, role = require_roles("ResourceOwner")
    o = db.offers.get(offer_id)
    if o is None:
        raise err_not_found("offer not found")
    run = db.auction_runs.get(o["auction_run_id"])
    if run is None:
        raise err_not_found("auction run not found")
    body = get_body()
    require_fields(body, ["expected_auction_run_version"])
    expected = body["expected_auction_run_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_auction_run_version must be an integer")
    # OCC before state gate
    if expected != run["version"]:
        raise err_stale_version()
    if o["status"] != "SUBMITTED":
        raise err_invalid_state("offer is not SUBMITTED")
    if run["status"] != "OPEN":
        raise err_invalid_state("auction run is not OPEN")
    resource = db.resources.get(o["resource_id"])
    if resource is None or user_id != resource["owner_id"]:
        raise err_ownership()
    o["status"] = "WITHDRAWN"
    touch(o)
    touch(run)
    return success_object(_serialize(o))


@bp.route("/capacity-market/offers/<offer_id>/mitigation-review", methods=["GET"])
def get_offer_review(offer_id):
    require_roles("MarketAdmin", "SettlementOps")
    o = db.offers.get(offer_id)
    if o is None:
        raise err_not_found("offer not found")
    reviews = [r for r in db.mitigation_reviews.values() if r["offer_id"] == offer_id]
    reviews = sort_created(reviews)
    return success_list([_serialize_review(r) for r in reviews],
                        len(reviews) if reviews else 10, 0, len(reviews))


@bp.route("/capacity-market/mitigation-reviews", methods=["GET"])
def list_reviews():
    require_roles("MarketAdmin", "SettlementOps")
    items = list(db.mitigation_reviews.values())
    for key in ("offer_id", "outcome"):
        v = request.args.get(key)
        if v:
            items = [r for r in items if r.get(key) == v]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize_review(r) for r in page], limit, offset, total)


@bp.route("/capacity-market/mitigation-reviews/<rev_id>/resolve", methods=["POST"])
def resolve_review(rev_id):
    require_roles("MarketAdmin")
    rev = db.mitigation_reviews.get(rev_id)
    if rev is None:
        raise err_not_found("mitigation review not found")
    body = get_body()
    require_fields(body, ["outcome"])
    outcome = body["outcome"]
    if outcome not in ("PASS", "MITIGATE"):
        raise err_invalid_request("outcome must be PASS or MITIGATE")
    if rev["outcome"] != "PENDING":
        raise err_invalid_state("mitigation review is not PENDING")
    if outcome == "MITIGATE" and not rev["pivotal_supplier_flag"]:
        raise err_invalid_state("MITIGATE requires pivotal_supplier_flag true")
    note = body.get("reviewer_note")
    offer = db.offers.get(rev["offer_id"])
    if offer is None:
        raise err_not_found("offer not found")

    dt, iso = stamp()
    rev["outcome"] = outcome
    rev["resolved_at"] = iso
    if note is not None:
        rev["reviewer_note"] = note
    touch(rev)
    if outcome == "PASS":
        offer["mitigation_status"] = "PASSED"
        offer["effective_price_per_mw_day"] = dec(offer["offer_price_per_mw_day"])
    else:
        offer["mitigation_status"] = "MITIGATED"
        offer["effective_price_per_mw_day"] = min(dec(offer["offer_price_per_mw_day"]),
                                                  dec(offer["mitigated_cap_per_mw_day"]))
    touch(offer)
    return success_object(_serialize_review(rev))
