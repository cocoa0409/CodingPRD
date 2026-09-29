"""Community registration, platting, reviews, management transition and financing."""
from __future__ import annotations

from decimal import Decimal
from flask import Blueprint

import repo
import serializers
from calc import iso
from db import PRODUCT_TYPES, mark_created, new_record, set_field, set_instant, store
from errors import ApiError
from middleware import acting_user_id, endpoint
from response import created, ok
from services import absorption, community as community_service, valuation as valuation_service
from validation import (body, opt_int, opt_str, req_bool, req_enum, req_instant, req_int,
                        req_str, bad)

bp = Blueprint("communities", __name__)

MARKET_CODE_MIN = 2
MARKET_CODE_MAX = 8
NAME_MAX = 120
DEFAULT_MAINTENANCE_TECH_HEADCOUNT = 2
MAX_PLAT_REVISION_ROUND = 2
REVIEW_WINDOW_MULTIPLE_DAYS = 7


def _product_mix(payload, total_planned_units):
    """Exactly three keys, none negative, reconciling to the planned total."""
    mix = payload.get("product_mix")
    if "product_mix" not in payload or mix is None:
        raise bad("product_mix is required")
    if not isinstance(mix, dict):
        raise bad("product_mix must be an object")
    if set(mix.keys()) != set(PRODUCT_TYPES):
        raise bad("product_mix must carry exactly the keys %s" % ", ".join(PRODUCT_TYPES))
    resolved = {}
    for product_type in PRODUCT_TYPES:
        value = mix[product_type]
        if not isinstance(value, int) or isinstance(value, bool):
            raise bad("product_mix.%s must be an integer" % product_type)
        if value < 0:
            raise bad("product_mix.%s may not be negative" % product_type)
        resolved[product_type] = value
    if sum(resolved.values()) != total_planned_units:
        raise bad("product_mix must sum to total_planned_units")
    return resolved


@bp.post("/communities")
@endpoint("DeveloperPrincipal")
def create_community():
    payload = body()
    name = req_str(payload, "name", 1, NAME_MAX)
    market_code = req_str(payload, "market_code", MARKET_CODE_MIN, MARKET_CODE_MAX)
    if market_code != market_code.upper():
        raise bad("market_code must be uppercase")
    total_planned_units = req_int(payload, "total_planned_units", minimum=1)
    product_mix = _product_mix(payload, total_planned_units)
    concession_budget_cents = req_int(payload, "concession_budget_cents", minimum=0)
    facility_commitment_cents = req_int(payload, "facility_commitment_cents", minimum=0)
    maintenance_tech_headcount = opt_int(
        payload, "maintenance_tech_headcount", DEFAULT_MAINTENANCE_TECH_HEADCOUNT, minimum=1)
    single_ownership_covenant = req_bool(payload, "single_ownership_covenant", True)

    for existing in store.communities.values():
        if existing["name"] == name and existing["market_code"] == market_code:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "A community with this name and market_code already exists")

    community = new_record("Community", {
        "name": name,
        "market_code": market_code,
        "total_planned_units": total_planned_units,
        "product_mix": product_mix,
        "single_ownership_covenant": single_ownership_covenant,
        "concession_budget_cents": concession_budget_cents,
        "facility_commitment_cents": facility_commitment_cents,
        "maintenance_tech_headcount": maintenance_tech_headcount,
        "plat_status": "DRAFT",
        "plat_revision_round": 0,
        "plat_submitted_by_user_id": None,
        "plat_package_reference": None,
        "lifecycle_status": "PLANNING",
        "management_mode": "DEVELOPER_SELF_MANAGED",
        "pm_company_name": None,
        "pm_effective_from": None,
        "_pm_effective_from": None,
        "facility_status": "CONSTRUCTION_DRAW",
        "posture": "FROZEN",
        "released_unit_count": 0,
        "available_unit_count": 0,
        "leased_unit_count": 0,
        "occupancy_ratio": 0.0,
        "amenity_delivery_ratio": 1.0,
        "committed_concession_cents": 0,
        "construction_impact_credit_cents": 0,
    })
    store.communities[community["id"]] = community
    mark_created(community)
    return created(serializers.community, community)


@bp.post("/communities/<identifier>/plat-submissions")
@endpoint("DeveloperPrincipal")
def submit_plat(identifier):
    community = repo.get_community(identifier)
    payload = body()
    reference = req_str(payload, "plat_package_reference", 1)
    if community["plat_status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_PLAT_STATE")
    if community["plat_revision_round"] > MAX_PLAT_REVISION_ROUND:
        raise ApiError("ERR_PLAT_REVISION_LIMIT")
    set_field(community, "plat_status", "SUBMITTED")
    set_field(community, "plat_package_reference", reference)
    set_field(community, "plat_submitted_by_user_id", acting_user_id())
    community_service.recompute_community(community)
    return created(serializers.community, community)


@bp.post("/communities/<identifier>/plat-decisions")
@endpoint("EntitlementOfficer")
def decide_plat(identifier):
    community = repo.get_community(identifier)
    submitter = community["plat_submitted_by_user_id"]
    if submitter is not None and submitter == acting_user_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The plat submitter may not decide the plat")
    payload = body()
    decision = req_enum(payload, "decision", ("APPROVE", "REQUEST_REVISION", "REJECT"))
    opt_str(payload, "decision_note", None, 1, None)
    if community["plat_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_PLAT_STATE")
    if decision == "APPROVE":
        if community["single_ownership_covenant"] is not True:
            raise ApiError("ERR_SINGLE_OWNERSHIP_COVENANT_REQUIRED")
        set_field(community, "plat_status", "APPROVED")
    elif decision == "REQUEST_REVISION":
        if community["plat_revision_round"] >= MAX_PLAT_REVISION_ROUND:
            raise ApiError("ERR_PLAT_REVISION_LIMIT")
        set_field(community, "plat_status", "REVISION_REQUESTED")
        set_field(community, "plat_revision_round", community["plat_revision_round"] + 1)
    else:
        set_field(community, "plat_status", "REJECTED")
    community_service.recompute_community(community)
    return created(serializers.community, community)


@bp.post("/communities/<identifier>/absorption-reviews")
@endpoint("AssetManager")
def create_absorption_review(identifier):
    community = repo.get_community(identifier)
    payload = body()
    product_type = req_enum(payload, "product_type", PRODUCT_TYPES)
    window_start = req_instant(payload, "window_start")
    window_end = req_instant(payload, "window_end")
    planned_units = req_int(payload, "planned_absorption_units", minimum=1)

    # A half-open window: start inclusive, end exclusive, a whole number of weeks,
    # and already finished against the logical clock (PRD section 3.5).
    if window_start >= window_end:
        raise ApiError("ERR_INVALID_REVIEW_WINDOW")
    span_seconds = (window_end - window_start).total_seconds()
    week_seconds = REVIEW_WINDOW_MULTIPLE_DAYS * 24 * 3600
    if span_seconds % week_seconds != 0:
        raise ApiError("ERR_INVALID_REVIEW_WINDOW")
    if window_end > store.now():
        raise ApiError("ERR_INVALID_REVIEW_WINDOW")

    homesites = repo.homesites_of_community(community)
    of_type = {h["id"] for h in homesites if h["product_type"] == product_type}
    actual_units = 0
    for lease in repo.leases_of_community(community):
        if lease["homesite_id"] not in of_type:
            continue
        if lease["lease_status"] not in ("EXECUTED", "ACTIVE", "ENDING"):
            continue
        executed = lease["_executed_at"]
        if executed is None or executed < window_start or executed >= window_end:
            continue
        actual_units += 1
    available_supply = sum(1 for h in homesites
                          if h["product_type"] == product_type and h["status"] == "AVAILABLE")
    posture_at_review = community["posture"]
    index = absorption.pacing_index(actual_units, planned_units, available_supply,
                                    posture_at_review)
    tier, growth_bps = absorption.tier_for(index)

    review = new_record("AbsorptionReview", {
        "community_id": community["id"],
        "product_type": product_type,
        "window_start": iso(window_start),
        "_window_start": window_start,
        "window_end": iso(window_end),
        "_window_end": window_end,
        "planned_absorption_units": planned_units,
        "actual_absorption_units": actual_units,
        "available_supply_units": available_supply,
        "posture_at_review": posture_at_review,
        "pacing_index": float(index),
        "concession_tier": tier,
        "recommended_growth_bps": growth_bps,
        "created_by_user_id": acting_user_id(),
    })
    store.reviews[review["id"]] = review
    mark_created(review)
    return created(serializers.review, review)


@bp.post("/communities/<identifier>/pm-transitions")
@endpoint("DeveloperPrincipal")
def pm_transition(identifier):
    community = repo.get_community(identifier)
    payload = body()
    pm_company_name = req_str(payload, "pm_company_name", 1, NAME_MAX)
    effective_from = req_instant(payload, "effective_from")
    if community["management_mode"] != "DEVELOPER_SELF_MANAGED":
        raise ApiError("ERR_INVALID_MANAGEMENT_STATE")
    community_service.require_not_frozen(community)
    if (community["lifecycle_status"] not in ("LEASE_UP", "STABILIZED")
            or community["maintenance_tech_headcount"] < 1):
        raise ApiError("ERR_MAINTENANCE_STAFFING_REQUIRED")
    if (community_service.as_decimal(community["occupancy_ratio"])
            < community_service.PM_TRANSITION_OCCUPANCY_RATIO):
        raise ApiError("ERR_LEASE_UP_THRESHOLD_NOT_MET")
    set_field(community, "pm_company_name", pm_company_name)
    set_instant(community, "pm_effective_from", effective_from)
    if effective_from > store.now():
        set_field(community, "management_mode", "PM_TRANSITION_PENDING")
    else:
        set_field(community, "management_mode", "PM_MANAGED")
    community_service.recompute_community(community)
    return created(serializers.community, community)


@bp.post("/communities/<identifier>/facility-commitments")
@endpoint("AssetManager")
def resize_facility(identifier):
    community = repo.get_community(identifier)
    payload = body()
    commitment = req_int(payload, "facility_commitment_cents", minimum=0)
    if community["facility_status"] == "PERM_CONVERTED":
        raise ApiError("ERR_INVALID_FACILITY_STATE")
    if valuation_service.trailing_ltv_bps(community, commitment) > valuation_service.MAX_LTV_BPS:
        raise ApiError("ERR_LTV_COVENANT_BREACH")
    set_field(community, "facility_commitment_cents", commitment)
    community_service.recompute_community(community)
    return created(serializers.community, community)


@bp.post("/communities/<identifier>/facility-conversions")
@endpoint("AssetManager")
def convert_facility(identifier):
    community = repo.get_community(identifier)
    if community["lifecycle_status"] != "STABILIZED":
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE")
    if community["facility_status"] != "CONVERSION_PENDING":
        raise ApiError("ERR_INVALID_FACILITY_STATE")
    if community["management_mode"] != "PM_MANAGED":
        raise ApiError("ERR_INVALID_MANAGEMENT_STATE")
    if (valuation_service.trailing_ltv_bps(community, community["facility_commitment_cents"])
            > valuation_service.MAX_LTV_BPS):
        raise ApiError("ERR_LTV_COVENANT_BREACH")
    set_field(community, "facility_status", "PERM_CONVERTED")
    community_service.recompute_community(community)
    return created(serializers.community, community)
