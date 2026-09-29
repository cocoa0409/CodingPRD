"""Phase creation, construction phasing, section releases and the halt cascade."""
from __future__ import annotations

from datetime import timedelta
from flask import Blueprint

import repo
import serializers
from db import mark_created, new_record, set_field, set_instant, store
from errors import ApiError
from middleware import endpoint
from response import created
from services import community as community_service, concession as concession_service, pricing
from validation import (MISSING, bad, body, opt_int, raw_id, req_enum, req_instant, req_int,
                        req_str)

bp = Blueprint("phases", __name__)

PHASE_KINDS = ("HOUSING", "AMENITY")
IN_FLIGHT_PHASE_STATUSES = ("UNDER_CONSTRUCTION", "SECTIONS_RELEASED", "CONSTRUCTION_HALTED")
MIN_PHASE_GAP = timedelta(hours=48)
MAX_OTHER_OVERLAPPING_PHASES = 1
POSTURE_FREEZE = "POSTURE_FREEZE"


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Construction windows are closed intervals."""
    return a_start <= b_end and b_start <= a_end


def _window_gap(a_start, a_end, b_start, b_end):
    if b_start > a_end:
        return b_start - a_end
    return a_start - b_end


@bp.post("/phases")
@endpoint("DeveloperPrincipal")
def create_phase():
    payload = body()
    community_ref = raw_id(payload, "community_id")
    community = repo.get_community(community_ref) if community_ref is not MISSING else None
    predecessor = None
    if "predecessor_phase_id" in payload and payload["predecessor_phase_id"] is not None:
        predecessor_ref = raw_id(payload, "predecessor_phase_id")
        if predecessor_ref is MISSING:
            raise bad("predecessor_phase_id must be an identifier string")
        predecessor = repo.get_phase(predecessor_ref)
    if community is None:
        raise bad("community_id is required")

    sequence_index = req_int(payload, "sequence_index", minimum=1)
    kind = req_enum(payload, "kind", PHASE_KINDS)
    planned_unit_count = opt_int(payload, "planned_unit_count", 0, minimum=0)
    amenity_weight = opt_int(payload, "amenity_weight", 0, minimum=0)
    window_start = req_instant(payload, "construction_window_start")
    window_end = req_instant(payload, "construction_window_end")
    if window_end <= window_start:
        raise bad("construction_window_end must fall strictly after construction_window_start")
    if kind == "HOUSING":
        if planned_unit_count < 1 or amenity_weight != 0:
            raise bad("a HOUSING phase needs planned_unit_count >= 1 and amenity_weight 0")
    else:
        if amenity_weight < 1 or planned_unit_count != 0:
            raise bad("an AMENITY phase needs amenity_weight >= 1 and planned_unit_count 0")

    for existing in repo.phases_of_community(community):
        if existing["sequence_index"] == sequence_index:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "sequence_index must be unique within the community")
    if predecessor is not None and predecessor["community_id"] != community["id"]:
        raise ApiError("ERR_INVALID_PHASE_PREDECESSOR",
                       "The predecessor phase must belong to the same community")

    phase = new_record("Phase", {
        "community_id": community["id"],
        "predecessor_phase_id": predecessor["id"] if predecessor is not None else None,
        "sequence_index": sequence_index,
        "kind": kind,
        "planned_unit_count": planned_unit_count,
        "amenity_weight": amenity_weight,
        "construction_window_start": None,
        "construction_window_end": None,
        "status": "PLANNED",
        "halt_count": 0,
        "pre_halt_status": None,
        "released_homesite_count": 0,
        "leased_homesite_count": 0,
    })
    store.phases[phase["id"]] = phase
    mark_created(phase)
    set_instant(phase, "construction_window_start", window_start)
    set_instant(phase, "construction_window_end", window_end)
    community_service.recompute_community(community)
    return created(serializers.phase, phase)


@bp.post("/phases/<identifier>/construction-start")
@endpoint("ConstructionManager")
def start_construction(identifier):
    phase = repo.get_phase(identifier)
    community = repo.community_of_phase(phase)
    if phase["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_PHASE_STATE")
    # plat_status APPROVED and a non-frozen posture are the same gate: an unapproved
    # plat freezes the community (PRD sections 2.6 and 3.3).
    community_service.require_not_frozen(community)

    start = phase["_construction_window_start"]
    end = phase["_construction_window_end"]
    siblings = [p for p in repo.phases_of_community(community) if p["id"] != phase["id"]]
    if phase["predecessor_phase_id"] is not None:
        predecessor = store.phases[phase["predecessor_phase_id"]]
        if predecessor["status"] not in ("SECTIONS_RELEASED", "COMPLETE"):
            raise ApiError("ERR_PHASE_CONCURRENCY_LIMIT",
                           "The predecessor phase has not released sections yet")
    overlapping = [p for p in siblings
                   if p["status"] in IN_FLIGHT_PHASE_STATUSES
                   and _windows_overlap(start, end, p["_construction_window_start"],
                                        p["_construction_window_end"])]
    if len(overlapping) > MAX_OTHER_OVERLAPPING_PHASES:
        raise ApiError("ERR_PHASE_CONCURRENCY_LIMIT",
                       "Too many phases with overlapping construction windows are in flight")
    for sibling in siblings:
        if sibling["kind"] != phase["kind"]:
            continue
        sibling_start = sibling["_construction_window_start"]
        sibling_end = sibling["_construction_window_end"]
        if _windows_overlap(start, end, sibling_start, sibling_end):
            continue
        if _window_gap(start, end, sibling_start, sibling_end) < MIN_PHASE_GAP:
            raise ApiError("ERR_PHASE_GAP_VIOLATION")

    set_field(phase, "status", "UNDER_CONSTRUCTION")
    if community["lifecycle_status"] == "PLANNING":
        set_field(community, "lifecycle_status", "CONSTRUCTION")
    community_service.recompute_community(community)
    return created(serializers.phase, phase)


@bp.post("/phases/<identifier>/section-releases")
@endpoint("ConstructionManager")
def release_section(identifier):
    phase = repo.get_phase(identifier)
    community = repo.community_of_phase(phase)
    payload = body()
    listed = payload.get("homesite_ids")
    if "homesite_ids" not in payload or listed is None or not isinstance(listed, list):
        raise bad("homesite_ids must be an array of homesite identifiers")
    # Body references resolve before any state reasoning (PRD section 2.10 step 6).
    homesites = [repo.get_homesite(item) for item in listed]

    if phase["kind"] != "HOUSING" or phase["status"] not in ("UNDER_CONSTRUCTION",
                                                             "SECTIONS_RELEASED"):
        raise ApiError("ERR_INVALID_PHASE_STATE")
    for homesite in homesites:
        if homesite["phase_id"] != phase["id"] or homesite["status"] != "PLANNED":
            raise ApiError("ERR_INVALID_HOMESITE_STATE")
    community_service.require_open(community)
    for homesite in homesites:
        if homesite["occupancy_certificate_issued_at"] is None:
            raise ApiError("ERR_OCCUPANCY_CERTIFICATE_REQUIRED")
    for product_type in {h["product_type"] for h in homesites}:
        if pricing.published_schedule(community, product_type) is None:
            raise ApiError("ERR_NO_PUBLISHED_RENT_SCHEDULE")

    first_release_anywhere = community["released_unit_count"] == 0
    moment = store.now()
    # The listed homes are walked in the order the client supplied them.
    for homesite in homesites:
        set_field(homesite, "status", "AVAILABLE")
        set_instant(homesite, "released_at", moment)
    set_field(phase, "status", "SECTIONS_RELEASED")
    community_service.recompute_community(community)
    if first_release_anywhere and community["released_unit_count"] > 0:
        if community["lifecycle_status"] == "CONSTRUCTION":
            set_field(community, "lifecycle_status", "LEASE_UP")
        if community["facility_status"] == "CONSTRUCTION_DRAW":
            set_field(community, "facility_status", "ADVANCE_ELIGIBLE")
    return created(serializers.phase, phase)


@bp.post("/phases/<identifier>/completion")
@endpoint("ConstructionManager")
def complete_phase(identifier):
    phase = repo.get_phase(identifier)
    community = repo.community_of_phase(phase)
    if phase["kind"] == "HOUSING":
        if (phase["status"] != "SECTIONS_RELEASED"
                or phase["released_homesite_count"] != phase["planned_unit_count"]):
            raise ApiError("ERR_INVALID_PHASE_STATE")
    else:
        if phase["status"] != "UNDER_CONSTRUCTION":
            raise ApiError("ERR_INVALID_PHASE_STATE")
    set_field(phase, "status", "COMPLETE")
    community_service.recompute_community(community)
    return created(serializers.phase, phase)


@bp.post("/phases/<identifier>/halt")
@endpoint("ConstructionManager")
def halt_phase(identifier):
    phase = repo.get_phase(identifier)
    community = repo.community_of_phase(phase)
    payload = body()
    req_str(payload, "halt_reason", 1)
    if phase["status"] not in ("UNDER_CONSTRUCTION", "SECTIONS_RELEASED"):
        raise ApiError("ERR_INVALID_PHASE_STATE")

    # Hop zero: the phase itself.
    set_field(phase, "pre_halt_status", phase["status"])
    set_field(phase, "status", "CONSTRUCTION_HALTED")
    set_field(phase, "halt_count", phase["halt_count"] + 1)

    # Hop one: the community posture, and the resident-experience compensation.
    community_service.recompute_community(community)
    for lease in repo.leases_of_community(community):
        if lease["lease_status"] == "ACTIVE":
            community_service.accrue_construction_impact_credit(community, lease)

    # Hop two fires only because hop one produced a FROZEN posture.
    delisted = []
    if community["posture"] == "FROZEN":
        for homesite in repo.homesites_of_community(community):
            if homesite["status"] == "AVAILABLE":
                set_field(homesite, "status", "OFF_MARKET")
                set_field(homesite, "off_market_reason", POSTURE_FREEZE)
                delisted.append(homesite)

    # Hop three: the unsigned leases standing on the homes that just came off market.
    touched_households = []
    for homesite in delisted:
        for lease in repo.leases_of_homesite(homesite):
            if lease["lease_status"] not in ("DRAFT", "PENDING_SIGNATURE"):
                continue
            set_field(lease, "lease_status", "CANCELLED")
            set_field(lease, "cancellation_reason", POSTURE_FREEZE)
            concession_service.revoke(lease)
            touched_households.append(lease)

    # Hop four: the program-level ledger, plus the community counters and totals.
    for lease in touched_households:
        community_service.recompute_household_of_lease(lease)
    community_service.recompute_community(community)
    return created(serializers.phase, phase)


@bp.post("/phases/<identifier>/resume")
@endpoint("ConstructionManager")
def resume_phase(identifier):
    phase = repo.get_phase(identifier)
    community = repo.community_of_phase(phase)
    if phase["status"] != "CONSTRUCTION_HALTED":
        raise ApiError("ERR_INVALID_PHASE_STATE")
    if community["plat_status"] != "APPROVED":
        raise ApiError("ERR_INVALID_PLAT_STATE")

    set_field(phase, "status", phase["pre_halt_status"])
    set_field(phase, "pre_halt_status", None)
    community_service.recompute_community(community)
    # The compensating relist runs only once the freeze has actually cleared.
    if community["posture"] != "FROZEN":
        for homesite in repo.homesites_of_community(community):
            if (homesite["status"] == "OFF_MARKET"
                    and homesite["off_market_reason"] == POSTURE_FREEZE):
                set_field(homesite, "status", "AVAILABLE")
                set_field(homesite, "off_market_reason", None)
        community_service.recompute_community(community)
    return created(serializers.phase, phase)
