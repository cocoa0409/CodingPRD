"""Homesite creation and municipal certificates of occupancy (PRD sections 3.1, 3.3)."""
from __future__ import annotations

from flask import Blueprint

import repo
import serializers
from db import PRODUCT_TYPES, mark_created, new_record, set_field, set_instant, store
from errors import ApiError
from middleware import endpoint
from response import created
from services import community as community_service
from validation import MISSING, bad, body, raw_id, req_enum, req_instant, req_int, req_str

bp = Blueprint("homesites", __name__)

LOT_NUMBER_MAX = 12
MIN_BEDROOMS = 1
MAX_BEDROOMS = 5
MIN_SQUARE_FEET = 400
MAX_SQUARE_FEET = 4000


@bp.post("/homesites")
@endpoint("DeveloperPrincipal", "ConstructionManager")
def create_homesite():
    payload = body()
    phase_ref = raw_id(payload, "phase_id")
    phase = repo.get_phase(phase_ref) if phase_ref is not MISSING else None
    if phase is None:
        raise bad("phase_id is required")
    community = repo.community_of_phase(phase)

    lot_number = req_str(payload, "lot_number", 1, LOT_NUMBER_MAX)
    product_type = req_enum(payload, "product_type", PRODUCT_TYPES)
    bedrooms = req_int(payload, "bedrooms", MIN_BEDROOMS, MAX_BEDROOMS)
    square_feet = req_int(payload, "square_feet", MIN_SQUARE_FEET, MAX_SQUARE_FEET)

    siblings = repo.homesites_of_phase(phase)
    for existing in siblings:
        if existing["lot_number"] == lot_number:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "lot_number must be unique within the phase")

    # Three counting rules apply together, all reported as ERR_PRODUCT_MIX_EXCEEDED.
    planned_for_type = community["product_mix"].get(product_type, 0)
    if planned_for_type < 1:
        raise ApiError("ERR_PRODUCT_MIX_EXCEEDED",
                       "The community plans no homes of this product type")
    existing_of_type = sum(1 for h in repo.homesites_of_community(community)
                           if h["product_type"] == product_type)
    if existing_of_type + 1 > planned_for_type:
        raise ApiError("ERR_PRODUCT_MIX_EXCEEDED",
                       "The planned count for this product type is already met")
    if len(siblings) + 1 > phase["planned_unit_count"]:
        raise ApiError("ERR_PRODUCT_MIX_EXCEEDED",
                       "The phase's planned unit count is already met")

    homesite = new_record("Homesite", {
        "phase_id": phase["id"],
        "lot_number": lot_number,
        "product_type": product_type,
        "bedrooms": bedrooms,
        "square_feet": square_feet,
        "status": "PLANNED",
        "off_market_reason": None,
        "occupancy_certificate_number": None,
        "occupancy_certificate_issued_at": None,
        "_occupancy_certificate_issued_at": None,
        "released_at": None,
        "_released_at": None,
        "turn_cycle_count": 0,
        "last_turn_ready_at": None,
        "_last_turn_ready_at": None,
    })
    store.homesites[homesite["id"]] = homesite
    mark_created(homesite)
    community_service.recompute_community(community)
    return created(serializers.homesite, homesite)


@bp.post("/homesites/<identifier>/occupancy-certificates")
@endpoint("ConstructionManager")
def record_occupancy_certificate(identifier):
    homesite = repo.get_homesite(identifier)
    community = repo.community_of_homesite(homesite)
    payload = body()
    number = req_str(payload, "occupancy_certificate_number", 1)
    issued_at = req_instant(payload, "issued_at")
    if homesite["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_HOMESITE_STATE")
    set_field(homesite, "occupancy_certificate_number", number)
    set_instant(homesite, "occupancy_certificate_issued_at", issued_at)
    community_service.recompute_community(community)
    return created(serializers.homesite, homesite)
