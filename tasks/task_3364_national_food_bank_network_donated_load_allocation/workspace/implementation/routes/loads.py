"""DonatedLoad lifecycle: creation, posting, award, freight, dispatch, delivery,
cancellation, and bid submission."""

import re

from flask import Blueprint, request

import auth
import clock
import envelope
import serializers
import store
from errors import (
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_CATEGORY_MISMATCH,
    ERR_DELIVERY_WINDOW_INVALID,
    ERR_DELIVERY_WINDOW_OVERLAP,
    ERR_DUPLICATE_BID,
    ERR_FREIGHT_DECISION_ALREADY_MADE,
    ERR_INSUFFICIENT_SHARES,
    ERR_INVALID_REQUEST,
    ERR_LOAD_NOT_AWARDED,
    ERR_LOAD_NOT_BIDDING,
    ERR_LOAD_NOT_FOUND,
    ERR_LOAD_NOT_IN_TRANSIT,
    ERR_LOAD_NOT_POSTED,
    ERR_LOAD_RECALLED,
    ERR_LOAD_SAFETY_HOLD,
    ERR_MEMBER_NOT_CERTIFIED,
    ERR_MEMBER_NOT_FOUND,
    ERR_MEMBER_SUSPENDED,
    ERR_NO_ELIGIBLE_BIDS,
    ERR_STALE_VERSION,
    ERR_STORAGE_CAPACITY_EXCEEDED,
    fail,
)
from services import freight as freight_svc
from services import loads as load_svc

bp = Blueprint("loads", __name__)

PRODUCT_CATEGORIES = ("DRY_GOODS", "PRODUCE", "DAIRY", "FROZEN_PROTEIN", "BAKERY")
STORAGE_TYPES = ("DRY", "REFRIGERATED", "FROZEN")
DESTINATION_REGIONS = ("NORTHEAST", "SOUTHEAST", "MIDWEST", "SOUTHWEST", "WEST")
ZIP_RE = re.compile(r"^\d{5}$")
FREIGHT_DECISIONS = ("COVERED", "DECLINED")


def get_load_or_404(load_id):
    load = store.loads.get(load_id)
    if load is None:
        fail(ERR_LOAD_NOT_FOUND, "no donated load matches id %s" % load_id)
    return load


@bp.route("/network/loads", methods=["POST"])
def create_load():
    auth.require_roles("NetworkAdmin")
    data = auth.json_body()

    agreement_id = auth.req_str(data, "donor_agreement_id")
    category = auth.req_enum(data, "product_category", PRODUCT_CATEGORIES)
    storage_type = auth.req_enum(data, "storage_type", STORAGE_TYPES)
    weight = auth.req_int(data, "weight_lbs")
    if weight <= 0:
        fail(ERR_INVALID_REQUEST, "weight_lbs must be strictly positive")
    lot_code = auth.req_str(data, "lot_code")
    origin_zip = auth.req_str(data, "origin_zip")
    if not ZIP_RE.match(origin_zip):
        fail(ERR_INVALID_REQUEST, "origin_zip must be exactly five digits")
    region = auth.req_enum(data, "destination_region", DESTINATION_REGIONS)
    distance = auth.req_int(data, "distance_miles")
    if distance <= 0:
        fail(ERR_INVALID_REQUEST, "distance_miles must be strictly positive")

    agreement = store.agreements.get(agreement_id)
    if agreement is None:
        fail(ERR_AGREEMENT_NOT_FOUND,
             "no donor agreement matches id %s" % agreement_id)
    if agreement["status"] != "ACTIVE":
        fail(ERR_AGREEMENT_NOT_ACTIVE, "the donor agreement is not ACTIVE")
    if agreement["product_category"] != category:
        fail(ERR_CATEGORY_MISMATCH,
             "the load category must equal the agreement's product category")

    load = store.new_record(
        donor_agreement_id=agreement["id"],
        product_category=category,
        storage_type=storage_type,
        weight_lbs=weight,
        lot_code=lot_code,
        origin_zip=origin_zip,
        destination_region=region,
        distance_miles=distance,
        status="POSTED",
        safety_status="CLEAR",
        awarded_bid_id=None,
        awarded_member_id=None,
        freight_estimate_cents=0,
        freight_subsidy_cents=0,
        member_freight_due_cents=0,
        freight_decision="PENDING",
        delivery_window_start=None,
        delivery_window_end=None,
        delivered_lbs=0,
        meal_equivalent=0,
        awarded_at=None,
        dispatched_at=None,
        delivered_at=None,
    )
    store.insert("loads", load)
    return envelope.ok_object(serializers.load(load), 201)


@bp.route("/network/loads/<load_id>", methods=["GET"])
def read_load(load_id):
    auth.require_roles("NetworkAdmin", "MemberFoodBank")
    return envelope.ok_object(serializers.load(get_load_or_404(load_id)))


@bp.route("/network/loads/<load_id>/post", methods=["POST"])
def post_load(load_id):
    auth.require_roles("NetworkAdmin")
    load = get_load_or_404(load_id)
    if load["status"] != "POSTED":
        fail(ERR_LOAD_NOT_POSTED, "the load is not in POSTED status")
    if load["safety_status"] != "CLEAR":
        fail(ERR_LOAD_SAFETY_HOLD, "the load is not CLEAR for posting")
    agreement = store.agreements.get(load["donor_agreement_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        fail(ERR_AGREEMENT_NOT_ACTIVE, "the donor agreement is not ACTIVE")
    if int(load["weight_lbs"]) <= 0:
        fail(ERR_INVALID_REQUEST, "weight_lbs must be strictly positive")
    load["status"] = "BIDDING"
    store.touch(load)
    return envelope.ok_object(serializers.load(load))


@bp.route("/network/loads/<load_id>/award", methods=["POST"])
def award_load(load_id):
    auth.require_roles("NetworkAdmin")
    data = request.get_json(silent=True)
    ranking_basis = None
    if data is not None:
        if not isinstance(data, dict):
            fail(ERR_INVALID_REQUEST, "the request body must be a JSON object")
        ranking_basis = auth.opt_str(data, "ranking_basis")

    load = get_load_or_404(load_id)
    if load["status"] != "BIDDING":
        fail(ERR_LOAD_NOT_BIDDING, "the load is not in BIDDING status")
    if load["safety_status"] != "CLEAR":
        fail(ERR_LOAD_SAFETY_HOLD, "the load is under a safety hold")
    if not load_svc.candidates(load):
        fail(ERR_NO_ELIGIBLE_BIDS, "the selector has no eligible bid for this load")

    load_svc.award_load(load, ranking_basis)
    return envelope.ok_object(serializers.load(load))


@bp.route("/network/loads/<load_id>/freight-decision", methods=["POST"])
def freight_decision(load_id):
    auth.require_roles("NetworkAdmin")
    data = auth.json_body()
    decision = auth.req_enum(data, "decision", FREIGHT_DECISIONS)
    detour = auth.opt_int(data, "detour_miles", 0)
    if detour < 0:
        fail(ERR_INVALID_REQUEST, "detour_miles must be zero or greater")

    load = get_load_or_404(load_id)
    if load["status"] != "AWARDED":
        fail(ERR_LOAD_NOT_AWARDED, "the load is not in AWARDED status")
    if load["freight_decision"] != "PENDING":
        fail(ERR_FREIGHT_DECISION_ALREADY_MADE,
             "a freight decision has already been recorded for this award")

    load_svc.record_freight_decision(load, decision, detour)
    return envelope.ok_object(serializers.load(load))


@bp.route("/network/loads/<load_id>/dispatch", methods=["POST"])
def dispatch_load(load_id):
    auth.require_roles("NetworkAdmin")
    data = auth.json_body()
    start = clock.parse_iso(auth.req_str(data, "delivery_window_start"))
    end = clock.parse_iso(auth.req_str(data, "delivery_window_end"))

    load = get_load_or_404(load_id)
    if load["status"] != "AWARDED":
        fail(ERR_LOAD_NOT_AWARDED, "the load is not in AWARDED status")
    if load["safety_status"] == "RECALLED":
        fail(ERR_LOAD_RECALLED, "a recalled load may not be dispatched")
    if load["safety_status"] != "CLEAR":
        fail(ERR_LOAD_SAFETY_HOLD, "the load is under a safety hold")
    if load["freight_decision"] not in ("COVERED", "DECLINED"):
        fail(ERR_LOAD_NOT_AWARDED,
             "the load's freight decision has not been recorded")

    member = store.members.get(load.get("awarded_member_id"))
    if member is None or member["certification_status"] not in ("CERTIFIED", "PROBATION"):
        fail(ERR_MEMBER_NOT_CERTIFIED,
             "the awarded member is not in a certified posture")

    if start >= end:
        fail(ERR_DELIVERY_WINDOW_INVALID,
             "delivery_window_start must be strictly before delivery_window_end")
    now = clock.now()
    if start < now or end < now:
        fail(ERR_DELIVERY_WINDOW_INVALID,
             "the delivery window must be at or after the current logical clock time")

    for other in store.loads.values():
        if other["id"] == load["id"] or other["status"] != "IN_TRANSIT":
            continue
        if other.get("awarded_member_id") != member["id"]:
            continue
        other_start = other.get("delivery_window_start")
        other_end = other.get("delivery_window_end")
        if other_start is None or other_end is None:
            continue
        if start < other_end and other_start < end:
            fail(ERR_DELIVERY_WINDOW_OVERLAP,
                 "the delivery window overlaps another in-transit load of this member")

    load_svc.dispatch_load(load, start, end)
    return envelope.ok_object(serializers.load(load))


@bp.route("/network/loads/<load_id>/deliver", methods=["POST"])
def deliver_load(load_id):
    auth.require_roles("NetworkAdmin")
    load = get_load_or_404(load_id)
    if load["status"] != "IN_TRANSIT":
        fail(ERR_LOAD_NOT_IN_TRANSIT, "the load is not in IN_TRANSIT status")
    if load["safety_status"] == "RECALLED":
        fail(ERR_LOAD_RECALLED, "a recalled load may not be delivered")
    load_svc.deliver_load(load)
    return envelope.ok_object(serializers.load(load))


@bp.route("/network/loads/<load_id>/cancel", methods=["POST"])
def cancel_load(load_id):
    auth.require_roles("NetworkAdmin")
    load = get_load_or_404(load_id)
    if load["status"] not in ("POSTED", "BIDDING"):
        fail(ERR_LOAD_NOT_POSTED, "only a POSTED or BIDDING load may be cancelled")
    load_svc.cancel_load(load)
    return envelope.ok_object(serializers.load(load))


@bp.route("/network/loads/<load_id>/bids", methods=["POST"])
def create_bid(load_id):
    user_id, role = auth.require_roles("MemberFoodBank")
    data = auth.json_body()

    member_id = auth.req_str(data, "member_id")
    shares = auth.req_int(data, "shares_offered")
    if shares <= 0:
        fail(ERR_INVALID_REQUEST, "shares_offered must be strictly positive")
    preference_rank = auth.req_int(data, "preference_rank")
    if preference_rank < 1:
        fail(ERR_INVALID_REQUEST, "preference_rank must be at least 1")
    can_self_transport = auth.req_bool(data, "can_self_transport")
    expected_version = auth.req_int(data, "expected_load_version")

    auth.require_owning_member(user_id, role, member_id)
    member = store.members.get(member_id)
    if member is None:
        fail(ERR_MEMBER_NOT_FOUND, "no member food bank matches id %s" % member_id)
    load = get_load_or_404(load_id)

    if expected_version != load["version"]:
        fail(ERR_STALE_VERSION,
             "expected_load_version does not match the load's current version")
    if load["status"] != "BIDDING":
        fail(ERR_LOAD_NOT_BIDDING, "the load is not in BIDDING status")
    if load["safety_status"] != "CLEAR":
        fail(ERR_LOAD_SAFETY_HOLD, "the load is under a safety hold")

    for other in store.bids.values():
        if (other["load_id"] == load["id"] and other["member_id"] == member["id"]
                and other["bid_status"] == "SUBMITTED"):
            fail(ERR_DUPLICATE_BID,
                 "this member already holds a SUBMITTED bid on this load")

    if not load_svc.storage_fits(member, load):
        fail(ERR_STORAGE_CAPACITY_EXCEEDED,
             "the load does not fit the member's storage capacity")

    posture = member["certification_status"]
    if posture == "SUSPENDED":
        fail(ERR_MEMBER_SUSPENDED, "a suspended member may not bid")
    if posture not in ("CERTIFIED", "PROBATION"):
        fail(ERR_MEMBER_NOT_CERTIFIED, "the member is not certified to bid")

    if int(member["share_balance"]) < shares:
        fail(ERR_INSUFFICIENT_SHARES,
             "the member's share balance is below the shares offered")

    bid = load_svc.create_bid(member, load, shares, preference_rank, can_self_transport)
    return envelope.ok_object(serializers.bid(bid), 201)
