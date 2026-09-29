"""The community posture gate and the aggregate counters that feed it (PRD section 2.6)."""
from __future__ import annotations

from decimal import Decimal

import repo
from calc import ratio4
from db import set_field, store
from errors import ApiError

AMENITY_GATE_RATIO = Decimal("0.5000")
STABILIZATION_OCCUPANCY_RATIO = Decimal("0.7500")
PM_TRANSITION_OCCUPANCY_RATIO = Decimal("0.5000")
CONSTRUCTION_IMPACT_CREDIT_CENTS = 7500
OCCUPIED_STATUSES = ("LEASED", "NOTICE_GIVEN")
COMMITTED_CONCESSION_STATUSES = ("APPROVED", "AMORTIZING")
OPEN_LEASE_STATUSES = ("DRAFT", "PENDING_SIGNATURE", "EXECUTED", "ACTIVE", "ENDING")


def as_decimal(ratio):
    return Decimal(str(ratio))


def recompute_phase_counters(phase):
    homesites = repo.homesites_of_phase(phase)
    set_field(phase, "released_homesite_count",
              sum(1 for h in homesites if h["released_at"] is not None))
    set_field(phase, "leased_homesite_count",
              sum(1 for h in homesites if h["status"] in OCCUPIED_STATUSES))


def recompute_household(household):
    leases = repo.leases_of_household(household)
    set_field(household, "active_lease_count",
              sum(1 for l in leases if l["lease_status"] in OPEN_LEASE_STATUSES))


def recompute_household_of_lease(lease):
    household = store.households.get(lease["household_id"])
    if household is not None:
        recompute_household(household)


def recompute_programs(community):
    """Program committed_cents is the sum of concession_remaining_cents over its
    APPROVED or AMORTIZING leases (PRD section 2.11)."""
    leases = repo.leases_of_community(community)
    for program in repo.programs_of_community(community):
        committed = sum(
            l["concession_remaining_cents"] for l in leases
            if l["concession_program_id"] == program["id"]
            and l["concession_status"] in COMMITTED_CONCESSION_STATUSES
        )
        set_field(program, "committed_cents", committed)


def amenity_delivery_ratio(community):
    amenity_phases = [p for p in repo.phases_of_community(community) if p["kind"] == "AMENITY"]
    if not amenity_phases:
        return 1.0
    planned = sum(p["amenity_weight"] for p in amenity_phases)
    delivered = sum(p["amenity_weight"] for p in amenity_phases if p["status"] == "COMPLETE")
    if planned == 0:
        return 1.0
    return ratio4(delivered, planned)


def recompute_community(community):
    """Recompute the five aggregate counters, the two ratios and the derived posture."""
    for phase in repo.phases_of_community(community):
        recompute_phase_counters(phase)

    homesites = repo.homesites_of_community(community)
    released = sum(1 for h in homesites if h["released_at"] is not None)
    available = sum(1 for h in homesites if h["status"] == "AVAILABLE")
    leased = sum(1 for h in homesites if h["status"] in OCCUPIED_STATUSES)
    set_field(community, "released_unit_count", released)
    set_field(community, "available_unit_count", available)
    set_field(community, "leased_unit_count", leased)
    set_field(community, "occupancy_ratio", ratio4(leased, community["total_planned_units"]))
    set_field(community, "amenity_delivery_ratio", amenity_delivery_ratio(community))

    leases = repo.leases_of_community(community)
    set_field(community, "committed_concession_cents", sum(
        l["concession_remaining_cents"] for l in leases
        if l["concession_status"] in COMMITTED_CONCESSION_STATUSES))
    recompute_programs(community)

    phases = repo.phases_of_community(community)
    housing_halted = any(p["kind"] == "HOUSING" and p["status"] == "CONSTRUCTION_HALTED"
                         for p in phases)
    amenity_halted = any(p["kind"] == "AMENITY" and p["status"] == "CONSTRUCTION_HALTED"
                         for p in phases)
    if (community["plat_status"] != "APPROVED"
            or community["single_ownership_covenant"] is False
            or housing_halted):
        posture = "FROZEN"
    elif ((community["released_unit_count"] >= 1
           and as_decimal(community["amenity_delivery_ratio"]) < AMENITY_GATE_RATIO)
          or amenity_halted):
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    set_field(community, "posture", posture)
    return posture


# ---------------------------------------------------------------- posture gate
def require_not_frozen(community):
    if community["posture"] == "FROZEN":
        raise ApiError("ERR_COMMUNITY_POSTURE_FROZEN")


def require_open(community):
    """Frozen is checked first, then restricted (PRD section 2.6 and 2.10 step 10)."""
    require_not_frozen(community)
    if community["posture"] == "RESTRICTED":
        raise ApiError("ERR_COMMUNITY_POSTURE_RESTRICTED")


# ---------------------------------------------------------------- lifecycle cascade
def apply_stabilization(community):
    """Signature cascade hops 3 and 4."""
    ratio = as_decimal(community["occupancy_ratio"])
    if (community["lifecycle_status"] == "LEASE_UP"
            and ratio >= STABILIZATION_OCCUPANCY_RATIO):
        set_field(community, "lifecycle_status", "STABILIZED")
        if community["facility_status"] == "ADVANCE_ELIGIBLE":
            set_field(community, "facility_status", "CONVERSION_PENDING")


def apply_stabilization_revert(community):
    """The STABILIZED -> LEASE_UP revert, taking CONVERSION_PENDING back with it."""
    ratio = as_decimal(community["occupancy_ratio"])
    if (community["lifecycle_status"] == "STABILIZED"
            and ratio < STABILIZATION_OCCUPANCY_RATIO):
        set_field(community, "lifecycle_status", "LEASE_UP")
        if community["facility_status"] == "CONVERSION_PENDING":
            set_field(community, "facility_status", "ADVANCE_ELIGIBLE")


def accrue_construction_impact_credit(community, lease):
    set_field(lease, "construction_impact_credit_cents",
              lease["construction_impact_credit_cents"] + CONSTRUCTION_IMPACT_CREDIT_CENTS)
    set_field(community, "construction_impact_credit_cents",
              community["construction_impact_credit_cents"] + CONSTRUCTION_IMPACT_CREDIT_CENTS)
