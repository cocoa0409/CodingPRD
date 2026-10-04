"""Auction runs routes: create, open, seal, clear."""
from flask import Blueprint, request

from db import db
from middleware import require_roles, require_any
from response import success_object, success_list
from util import (base_entity, touch, dec, require_fields, get_body,
                  strip_internal, paginate, sort_created, stamp)
from errors import (err_not_found, err_invalid_request, err_invalid_state,
                    err_mitigation_pending)
from services.calcs import seller_offer_cap, auction_clearing

bp = Blueprint("auction_runs", __name__)


def _serialize(r):
    return strip_internal(r)


@bp.route("/capacity-market/auction-runs", methods=["POST"])
def create_run():
    require_roles("MarketAdmin")
    body = get_body()
    require_fields(body, ["delivery_year_id", "run_label"])
    dy = db.delivery_years.get(body["delivery_year_id"])
    if dy is None:
        raise err_not_found("delivery year not found")
    label = body["run_label"]
    if not isinstance(label, str) or not label.strip():
        raise err_invalid_request("run_label must be a non-empty string")
    for r in db.auction_runs.values():
        if r["delivery_year_id"] == dy["id"] and r["run_label"] == label:
            raise err_invalid_request("run_label must be unique within the delivery year")
    run = base_entity()
    run.update({
        "delivery_year_id": dy["id"],
        "run_label": label,
        "status": "DRAFT",
        "sealed_at": None,
        "cleared_at": None,
        "_sealed_dt": None,
    })
    db.auction_runs[run["id"]] = run
    return success_object(_serialize(run), 201)


@bp.route("/capacity-market/auction-runs", methods=["GET"])
def list_runs():
    require_any()
    items = list(db.auction_runs.values())
    for key in ("delivery_year_id", "status"):
        v = request.args.get(key)
        if v:
            items = [r for r in items if r.get(key) == v]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize(r) for r in page], limit, offset, total)


@bp.route("/capacity-market/auction-runs/<run_id>", methods=["GET"])
def get_run(run_id):
    require_any()
    r = db.auction_runs.get(run_id)
    if r is None:
        raise err_not_found("auction run not found")
    return success_object(_serialize(r))


@bp.route("/capacity-market/auction-runs/<run_id>/open", methods=["POST"])
def open_run(run_id):
    require_roles("MarketAdmin")
    run = db.auction_runs.get(run_id)
    if run is None:
        raise err_not_found("auction run not found")
    dy = db.delivery_years.get(run["delivery_year_id"])
    if dy is None:
        raise err_not_found("delivery year not found")
    if run["status"] != "DRAFT":
        raise err_invalid_state("auction run is not DRAFT")
    if dy["status"] != "FORECAST_LOCKED":
        raise err_invalid_state("delivery year is not FORECAST_LOCKED")
    for other in db.auction_runs.values():
        if (other["id"] != run_id and other["delivery_year_id"] == dy["id"]
                and other["status"] in ("OPEN", "SEALED")):
            raise err_invalid_state("another run for this delivery year is OPEN or SEALED")
    run["status"] = "OPEN"
    touch(run)
    dy["status"] = "AUCTION_OPEN"
    touch(dy)
    return success_object(_serialize(run))


def _pivotal_supplier_screen(offer):
    """Three-pivotal-supplier screen for the offer's LDA.

    With remaining supply inside the LDA, an owner is pivotal if removing its
    offers leaves the LDA requirement unmet AND fewer than two other owners
    could cover the shortfall. Simplified deterministic screen: the owner is
    pivotal when the zone is a constrained LDA (has import_limit_mw) and the
    total supply from OTHER owners inside that LDA is below the zone's
    zonal requirement.
    """
    resource = db.resources.get(offer["resource_id"])
    if resource is None:
        return False
    zone = db.zones.get(resource["zone_id"])
    if zone is None or zone.get("parent_zone_id") is None:
        return False  # RTO-wide: never pivotal by default screen
    owner_id = resource["owner_id"]
    others_supply = 0
    for o in db.offers.values():
        if o["auction_run_id"] != offer["auction_run_id"] or o["status"] != "SEALED":
            continue
        r = db.resources.get(o["resource_id"])
        if r is None or r["zone_id"] != zone["id"] or r["owner_id"] == owner_id:
            continue
        others_supply += float(dec(o["offer_mw"]))
    req = float(dec(zone["zonal_requirement_mw"]))
    return others_supply < req


@bp.route("/capacity-market/auction-runs/<run_id>/seal", methods=["POST"])
def seal_run(run_id):
    require_roles("MarketAdmin")
    run = db.auction_runs.get(run_id)
    if run is None:
        raise err_not_found("auction run not found")
    if run["status"] != "OPEN":
        raise err_invalid_state("auction run is not OPEN")
    submitted = [o for o in db.offers.values()
                 if o["auction_run_id"] == run_id and o["status"] == "SUBMITTED"]
    if not submitted:
        raise err_invalid_state("no SUBMITTED offers exist for this run")

    sealed_dt, sealed_iso = stamp()
    run["sealed_at"] = sealed_iso
    run["_sealed_dt"] = sealed_dt

    # First pass: re-validate MW and seal or reject.
    # Headroom check: total offer_mw per resource within this run (SUBMITTED+SEALED)
    # must fit accredited_ucap_mw. Offers processed in created order; once cumulative
    # exceeds accredited UCAP, the offer is REJECTED.
    by_created = sort_created(submitted)
    cum_by_resource = {}
    sealed_now = []
    for o in by_created:
        res = db.resources.get(o["resource_id"])
        accredited = dec(res["accredited_ucap_mw"]) if res else dec(0)
        prior = cum_by_resource.get(o["resource_id"], dec(0))
        if q3ok(prior + dec(o["offer_mw"]), accredited):
            cum_by_resource[o["resource_id"]] = prior + dec(o["offer_mw"])
            owner = db.owners.get(res["owner_id"]) if res else None
            cap = seller_offer_cap(owner) if owner else dec("390.00")
            o["mitigated_cap_per_mw_day"] = cap
            o["effective_price_per_mw_day"] = dec(o["offer_price_per_mw_day"])
            o["status"] = "SEALED"
            touch(o)
            sealed_now.append(o)
        else:
            o["status"] = "REJECTED"
            touch(o)

    # Second pass: auto-create MitigationReview per sealed offer
    for o in sealed_now:
        res = db.resources.get(o["resource_id"])
        owner = db.owners.get(res["owner_id"]) if res else None
        cap = dec(o["mitigated_cap_per_mw_day"])
        pivotal = _pivotal_supplier_screen(o)
        under_cap = dec(o["offer_price_per_mw_day"]) <= cap
        review = base_entity()
        if (not pivotal) and under_cap:
            review.update({
                "offer_id": o["id"],
                "reviewer_note": None,
                "pivotal_supplier_flag": False,
                "outcome": "EXEMPT",
                "resolved_at": sealed_iso,
            })
            o["mitigation_status"] = "EXEMPT"
        else:
            review.update({
                "offer_id": o["id"],
                "reviewer_note": None,
                "pivotal_supplier_flag": pivotal,
                "outcome": "PENDING",
                "resolved_at": None,
            })
            o["mitigation_status"] = "UNREVIEWED"
        db.mitigation_reviews[review["id"]] = review
        touch(o)

    run["status"] = "SEALED"
    touch(run)
    return success_object(_serialize(run))


def q3ok(value, limit):
    return value <= limit


@bp.route("/capacity-market/auction-runs/<run_id>/clear", methods=["POST"])
def clear_run(run_id):
    require_roles("MarketAdmin")
    run = db.auction_runs.get(run_id)
    if run is None:
        raise err_not_found("auction run not found")
    dy = db.delivery_years.get(run["delivery_year_id"])
    if dy is None:
        raise err_not_found("delivery year not found")
    if run["status"] != "SEALED":
        raise err_invalid_state("auction run is not SEALED")
    # mitigation gate
    offer_ids = {o["id"] for o in db.offers.values() if o["auction_run_id"] == run_id}
    for rev in db.mitigation_reviews.values():
        if rev["offer_id"] in offer_ids and rev["outcome"] == "PENDING":
            raise err_mitigation_pending()

    auction_clearing(run)

    cleared_dt, cleared_iso = stamp()
    run["cleared_at"] = cleared_iso
    run["status"] = "CLEARED"
    touch(run)
    dy["status"] = "CLEARED"
    touch(dy)
    return success_object(_serialize(run))
