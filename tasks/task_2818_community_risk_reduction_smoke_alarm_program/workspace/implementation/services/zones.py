"""Zone scoring, district rollup, priority banding and the zone lifecycle."""

from decimal import Decimal

import db
import util
from db import store, touch
from errors import ApiError

TIER_1_FLOOR = Decimal("70.00")
TIER_2_FLOOR = Decimal("45.00")


def tier_for(score):
    """PRD 3.2: lower bound inclusive, upper bound exclusive."""
    if score is None:
        return None
    if score >= TIER_1_FLOOR:
        return "TIER_1"
    if score >= TIER_2_FLOOR:
        return "TIER_2"
    return "TIER_3"


def children_of(zone_id):
    kids = [z for z in store.zones.values() if z["parent_zone_id"] == zone_id]
    return db.by_created_at(kids)


def households_of(zone_id):
    rows = [h for h in store.households.values() if h["zone_id"] == zone_id]
    return db.by_created_at(rows)


def alarm_gap_pct(zone, basis):
    """The single field that differs between the two bases (PRD 3.2)."""
    if basis == "PROVISIONAL":
        return util.to_decimal(zone["assumed_alarm_absence_pct"])
    numerator = (
        util.to_decimal(zone["surveyed_units_without_alarm"])
        + util.to_decimal(zone["post_service_alarm_loss_units"])
    )
    surveyed = util.to_decimal(zone["surveyed_units"])
    raw = util.round_half_up(Decimal(100) * numerator / surveyed, 2)
    return min(Decimal("100.00"), raw)


def score_components(zone, basis):
    """The five-component weighted sum of PRD 3.2, rounded exactly where the
    specification says and nowhere else."""
    occupied = util.to_decimal(zone["occupied_units"])
    incident_density = util.round_half_up(
        util.to_decimal(zone["structure_fire_count_5yr"]) * Decimal(1000) / occupied, 4
    )
    injury_density = util.round_half_up(
        util.to_decimal(zone["fire_injury_count_5yr"]) * Decimal(1000) / occupied, 4
    )
    incident_points = min(
        Decimal("40.00"), util.round_half_up(incident_density * Decimal("4.0"), 2)
    )
    injury_points = min(
        Decimal("15.00"), util.round_half_up(injury_density * Decimal("10.0"), 2)
    )
    building_points = util.round_half_up(
        util.to_decimal(zone["pre_1980_unit_pct"]) * Decimal("0.15"), 2
    )
    vulnerability_raw = (
        Decimal("0.12") * util.to_decimal(zone["senior_household_pct"])
        + Decimal("0.10") * util.to_decimal(zone["under5_household_pct"])
        + Decimal("0.08") * util.to_decimal(zone["disability_household_pct"])
    )
    vulnerability_points = min(
        Decimal("20.00"), util.round_half_up(vulnerability_raw, 2)
    )
    gap = alarm_gap_pct(zone, basis)
    alarm_points = min(Decimal("10.00"), util.round_half_up(gap * Decimal("0.10"), 2))
    risk_score = util.round_half_up(
        incident_points
        + injury_points
        + building_points
        + vulnerability_points
        + alarm_points,
        2,
    )
    return {
        "incident_density_per_1000": incident_density,
        "injury_density_per_1000": injury_density,
        "incident_points": incident_points,
        "injury_points": injury_points,
        "building_points": building_points,
        "vulnerability_points": vulnerability_points,
        "alarm_points": alarm_points,
        "alarm_gap_pct": gap,
        "risk_score": risk_score,
        "risk_tier": tier_for(risk_score),
    }


def priority_band(household, zone):
    """PRD 3.3, read off the household's own zone's tier."""
    vulnerable = (
        household["adults_65plus"] > 0
        or household["children_under5"] > 0
        or household["mobility_impaired_occupants"] > 0
        or household["hearing_impaired_occupants"] > 0
    )
    tier = zone["risk_tier"] if zone else None
    if vulnerable and tier == "TIER_1":
        return "P1_HIGH_RISK"
    if (vulnerable and tier == "TIER_2") or (not vulnerable and tier == "TIER_1"):
        return "P2_ELEVATED"
    return "P3_STANDARD"


def recompute_priority_bands(zone):
    """Recompute the band of every household in the zone; only rows that
    actually change are bumped (PRD 2.11)."""
    for household in households_of(zone["id"]):
        band = priority_band(household, zone)
        if band != household["priority_band"]:
            household["priority_band"] = band
            touch(household)


def rollup_values(district):
    """Unit-weighted rollup over direct children with a non-null score (PRD 2.5)."""
    scored = [c for c in children_of(district["id"]) if c["risk_score"] is not None]
    if not scored:
        return None, None
    numerator = Decimal(0)
    denominator = Decimal(0)
    for child in scored:
        numerator += util.to_decimal(child["risk_score"]) * util.to_decimal(
            child["occupied_units"]
        )
        denominator += util.to_decimal(child["occupied_units"])
    if denominator == 0:
        return None, None
    score = util.round_half_up(numerator / denominator, 2)
    return score, tier_for(score)


def apply_rollup(district):
    """Write the rollup onto the district.  Returns True when anything moved."""
    score, tier = rollup_values(district)
    changed = district["risk_score"] != score or district["risk_tier"] != tier
    tier_changed = district["risk_tier"] != tier
    district["risk_score"] = score
    district["risk_tier"] = tier
    if tier_changed:
        recompute_priority_bands(district)
    return changed


def parent_of(zone):
    if zone["parent_zone_id"] is None:
        return None
    return store.zones.get(zone["parent_zone_id"])


def reevaluate_service_state(zone):
    """PRD 3.1: evaluated after every household status change in the zone."""
    if zone is None:
        return
    households = households_of(zone["id"])
    if zone["assessment_status"] == "SERVICE_ACTIVE":
        if households and all(
            h["status"] in ("VISIT_COMPLETED", "REFUSED", "NO_CONTACT")
            for h in households
        ):
            zone["assessment_status"] = "SERVICE_COMPLETE"
            touch(zone)
        return
    if zone["assessment_status"] == "SERVICE_COMPLETE":
        if any(h["status"] == "REVISIT_REQUIRED" for h in households):
            zone["assessment_status"] = "SERVICE_ACTIVE"
            touch(zone)


def run_assessment(zone, basis, analyst_note, actor_id):
    """Execute one immutable assessment run and its side-effect set (PRD 3.2)."""
    components = score_components(zone, basis)
    sequence_no = len(assessments_of(zone["id"])) + 1
    row = {}
    db.stamp_event(row)
    ordered = {
        "id": row["id"],
        "zone_id": zone["id"],
        "sequence_no": sequence_no,
        "basis": basis,
        "analyst_note": analyst_note,
        "incident_density_per_1000": components["incident_density_per_1000"],
        "injury_density_per_1000": components["injury_density_per_1000"],
        "incident_points": components["incident_points"],
        "injury_points": components["injury_points"],
        "building_points": components["building_points"],
        "vulnerability_points": components["vulnerability_points"],
        "alarm_points": components["alarm_points"],
        "alarm_gap_pct": components["alarm_gap_pct"],
        "surveyed_units_at_assessment": zone["surveyed_units"],
        "risk_score": components["risk_score"],
        "risk_tier": components["risk_tier"],
        "assessed_by_user_id": actor_id,
        "created_at": row["created_at"],
        "_seq": row["_seq"],
    }
    store.zone_assessments[ordered["id"]] = ordered

    zone["risk_score"] = components["risk_score"]
    zone["risk_tier"] = components["risk_tier"]
    zone["assessment_basis"] = basis
    zone["current_assessment_id"] = ordered["id"]
    if zone["assessment_status"] == "UNASSESSED":
        zone["assessment_status"] = "ASSESSED"
    recompute_priority_bands(zone)
    touch(zone)

    parent = parent_of(zone)
    if parent is not None:
        apply_rollup(parent)
        touch(parent)
    return ordered


def assessments_of(zone_id):
    rows = [a for a in store.zone_assessments.values() if a["zone_id"] == zone_id]
    return sorted(rows, key=lambda r: r["sequence_no"])


def rescore_after_alarm_loss(zone):
    """Hop two/three of the follow-up cascade (PRD 3.7).  The counter always
    moves; the re-score only runs under the VALIDATED basis."""
    zone["post_service_alarm_loss_units"] = zone["post_service_alarm_loss_units"] + 1
    previous_score = zone["risk_score"]
    if zone["assessment_basis"] == "VALIDATED" and zone["surveyed_units"] >= 1:
        components = score_components(zone, "VALIDATED")
        tier_changed = zone["risk_tier"] != components["risk_tier"]
        zone["risk_score"] = components["risk_score"]
        zone["risk_tier"] = components["risk_tier"]
        if tier_changed:
            recompute_priority_bands(zone)
    touch(zone)
    if zone["risk_score"] != previous_score:
        parent = parent_of(zone)
        if parent is not None:
            apply_rollup(parent)
            touch(parent)
