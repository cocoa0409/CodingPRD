"""Derived data, ledgers and the five named cascades -- PRD 2.10, 2.12, 3.x.

PRD section 1: "derived data is never entered by hand ... every one of them is
re-derived when an input beneath it changes."
"""

from datetime import timedelta
from decimal import Decimal

from calc import (
    ACTIVATION_WINDOW_HOURS,
    MISSED_CHECK_IN_THRESHOLD,
    REQUIRED_COVERAGE_CENTS,
    band_check_in_interval_hours,
    band_for_composite,
    band_rank,
    check_in_interval_hours,
    destination_composite,
    detail_cost_cents,
    engagement_cost_cents,
    engagement_hours,
    exposure_score,
    leg_adjusted_score,
    level_rank,
    required_advance_items,
    required_approval_level,
)
from errors import ApiError
from store import (
    assignments_of_leg,
    assignments_of_trip,
    checkins_of_trip,
    engagements_of_incident,
    engagements_of_trip,
    engagements_of_vendor,
    executive_of_trip,
    incidents_of_trip,
    legs_of_trip,
    rating_for_country,
    signals_of_executive,
    store,
    touch,
    trip_of_leg,
)

# ---------------------------------------------------------------------------
# Existence resolution -- PRD 2.6
# ---------------------------------------------------------------------------


def get_executive(executive_id):
    row = store.executives.get(executive_id)
    if row is None:
        raise ApiError("ERR_EXECUTIVE_NOT_FOUND")
    return row


def get_staff(staff_id):
    row = store.staff.get(staff_id)
    if row is None:
        raise ApiError("ERR_STAFF_NOT_FOUND")
    return row


def get_assessment(assessment_id):
    row = store.assessments.get(assessment_id)
    if row is None:
        raise ApiError("ERR_ASSESSMENT_NOT_FOUND")
    return row


def get_rating(country_code):
    row = rating_for_country(country_code)
    if row is None:
        raise ApiError("ERR_DESTINATION_RATING_NOT_FOUND")
    return row


def get_policy(policy_id):
    row = store.policies.get(policy_id)
    if row is None:
        raise ApiError("ERR_POLICY_NOT_FOUND")
    return row


def get_trip(trip_id):
    row = store.trips.get(trip_id)
    if row is None:
        raise ApiError("ERR_TRIP_NOT_FOUND")
    return row


def get_leg(leg_id):
    row = store.legs.get(leg_id)
    if row is None:
        raise ApiError("ERR_TRIP_LEG_NOT_FOUND")
    return row


def get_assignment(assignment_id):
    row = store.assignments.get(assignment_id)
    if row is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND")
    return row


def get_vendor(vendor_id):
    row = store.vendors.get(vendor_id)
    if row is None:
        raise ApiError("ERR_VENDOR_NOT_FOUND")
    return row


def get_engagement(engagement_id):
    row = store.engagements.get(engagement_id)
    if row is None:
        raise ApiError("ERR_ENGAGEMENT_NOT_FOUND")
    return row


def get_incident(incident_id):
    row = store.incidents.get(incident_id)
    if row is None:
        raise ApiError("ERR_INCIDENT_NOT_FOUND")
    return row


# ---------------------------------------------------------------------------
# Executive-level derivations
# ---------------------------------------------------------------------------


def recompute_public_exposure_score(executive):
    """PRD 3.2: every appended signal immediately re-derives the score using the
    decay-weighted reading."""
    executive["public_exposure_score"] = exposure_score(
        signals_of_executive(executive["id"]), store.now(), True)


def remaining_budget(executive):
    """PRD 2.10: annual less committed less spent."""
    return (executive["annual_security_budget_cents"]
            - executive["committed_budget_cents"]
            - executive["spent_budget_cents"])


# ---------------------------------------------------------------------------
# Destination rating derivations -- PRD 3.3
# ---------------------------------------------------------------------------


def recompute_rating_derived(rating):
    rating["composite_destination_score"] = destination_composite(
        rating["crime_index"],
        rating["political_instability_index"],
        rating["medical_infrastructure_index"],
        rating["natural_hazard_index"],
    )
    rating["rating_band"] = band_for_composite(rating["composite_destination_score"])
    rating["insurance_required_coverage_cents"] = REQUIRED_COVERAGE_CENTS[
        rating["rating_band"]]


# ---------------------------------------------------------------------------
# Leg derivations -- PRD 3.4, 3.5
# ---------------------------------------------------------------------------


def recompute_advance_complete(leg):
    """PRD 3.4: true exactly when the union of the two arrays covers the set."""
    covered = set(leg["completed_advance_items"]) | set(leg["waived_advance_items"])
    leg["advance_complete"] = all(item in covered for item in leg["required_advance_items"])


def recompute_lead_agent_covered(leg):
    """PRD 3.5: a lead agent who arrives late or leaves early does not cover."""
    result = False
    for assignment in assignments_of_leg(leg["id"]):
        if (assignment["status"] == "CONFIRMED"
                and assignment["role_on_detail"] == "LEAD_AGENT"
                and assignment["starts_at"] <= leg["arrive_at"]
                and assignment["ends_at"] >= leg["depart_at"]):
            result = True
            break
    leg["lead_agent_covered"] = result


def recompute_leg_band(leg, trip=None, executive=None):
    """PRD 3.4: destination composite plus the protectee's threat uplift."""
    if trip is None:
        trip = trip_of_leg(leg)
    if executive is None:
        executive = executive_of_trip(trip)
    rating = rating_for_country(leg["destination_country_code"])
    adjusted = leg_adjusted_score(rating["composite_destination_score"],
                                  executive["threat_level"])
    leg["leg_risk_band"] = band_for_composite(adjusted)
    leg["required_advance_items"] = required_advance_items(leg["leg_risk_band"],
                                                          trip["trip_purpose"])
    recompute_advance_complete(leg)


def max_leg_risk_band(trip):
    """PRD 3.4: the highest band across the trip's legs, null with no legs."""
    band = None
    for leg in legs_of_trip(trip["id"]):
        if band_rank(leg["leg_risk_band"]) > band_rank(band):
            band = leg["leg_risk_band"]
    return band


def recompute_trip_band_and_level(trip):
    trip["max_leg_risk_band"] = max_leg_risk_band(trip)
    executive = executive_of_trip(trip)
    trip["required_approval_level"] = required_approval_level(
        trip["max_leg_risk_band"], trip["trip_purpose"], executive["tier"])


def any_advance_recorded(trip):
    for leg in legs_of_trip(trip["id"]):
        if leg["completed_advance_items"] or leg["waived_advance_items"]:
            return True
    return False


def all_legs_advance_complete(trip):
    legs = legs_of_trip(trip["id"])
    return all(leg["advance_complete"] for leg in legs)


def any_leg_advance_incomplete(trip):
    for leg in legs_of_trip(trip["id"]):
        if not leg["advance_complete"]:
            return True
    return False


def recompute_advance_readiness(trip):
    """PRD 3.4: NOT_READY <-> ADVANCE_IN_PROGRESS is re-derived from the world,
    not ratcheted forward."""
    recorded = any_advance_recorded(trip)
    if trip["readiness_state"] == "NOT_READY" and recorded:
        trip["readiness_state"] = "ADVANCE_IN_PROGRESS"
        return True
    if trip["readiness_state"] == "ADVANCE_IN_PROGRESS" and not recorded:
        trip["readiness_state"] = "NOT_READY"
        return True
    return False


# ---------------------------------------------------------------------------
# Degradation and recovery -- PRD 3.7
# ---------------------------------------------------------------------------


def degrade_trip(trip):
    """The READY -> DEGRADED edge and its fixed side-effect set (PRD 3.7)."""
    if trip["readiness_state"] != "READY":
        return False
    trip["readiness_state"] = "DEGRADED"
    interval = check_in_interval_hours(trip["duress_active"], "DEGRADED",
                                       trip["max_leg_risk_band"])
    trip["check_in_interval_hours"] = interval
    candidate = store.now() + timedelta(hours=interval)
    current = trip["next_check_in_due_at"]
    if current is None or candidate < current:
        trip["next_check_in_due_at"] = candidate
    executive = executive_of_trip(trip)
    executive["open_degraded_trip_count"] += 1
    touch(executive)
    touch(trip)
    return True


def try_recover_trip(trip):
    """PRD 3.7: DEGRADED -> READY only when all five conditions hold."""
    if trip["readiness_state"] != "DEGRADED":
        return False
    if trip["approval_state"] != "APPROVED":
        return False
    if trip["duress_active"]:
        return False
    if trip["missed_check_in_count"] >= MISSED_CHECK_IN_THRESHOLD:
        return False
    legs = legs_of_trip(trip["id"])
    for leg in legs:
        if not (leg["advance_complete"] and leg["lead_agent_covered"]):
            return False
    trip["readiness_state"] = "READY"
    trip["check_in_interval_hours"] = band_check_in_interval_hours(
        trip["max_leg_risk_band"])
    executive = executive_of_trip(trip)
    executive["open_degraded_trip_count"] -= 1
    touch(executive)
    touch(trip)
    return True


# ---------------------------------------------------------------------------
# Cost aggregation -- PRD 3.6, 3.8, 3.9
# ---------------------------------------------------------------------------


def provisional_cost_cents(trip):
    """PRD 3.6: confirmed assignments plus active non-incident engagements."""
    total = 0
    for assignment in assignments_of_trip(trip["id"]):
        if assignment["status"] == "CONFIRMED":
            total += assignment["cost_cents"]
    for engagement in engagements_of_trip(trip["id"]):
        if engagement["incident_id"] is None and engagement["status"] == "ACTIVE":
            total += engagement["engagement_cost_cents"]
    return total


def final_cost_cents(trip):
    """PRD 3.9: released assignments, completed non-incident engagements and
    closed incidents' response costs."""
    total = 0
    for assignment in assignments_of_trip(trip["id"]):
        if assignment["status"] == "RELEASED":
            total += assignment["cost_cents"]
    for engagement in engagements_of_trip(trip["id"]):
        if engagement["incident_id"] is None and engagement["status"] == "COMPLETED":
            total += engagement["engagement_cost_cents"]
    for incident in incidents_of_trip(trip["id"]):
        if incident["status"] == "CLOSED":
            total += incident["response_cost_cents"]
    return total


def incident_response_cost_cents(incident):
    """PRD 3.8: completed engagements plus the MEDEVAC surcharge."""
    from calc import MEDEVAC_SURCHARGE_CENTS
    total = 0
    for engagement in engagements_of_incident(incident["id"]):
        if engagement["status"] == "COMPLETED":
            total += engagement["engagement_cost_cents"]
    if incident["response_track"] == "MEDEVAC":
        total += MEDEVAC_SURCHARGE_CENTS
    return total


def max_required_coverage_cents(trip):
    """PRD 3.6: the largest floor demanded by the ratings of the trip's legs."""
    largest = 0
    for leg in legs_of_trip(trip["id"]):
        rating = rating_for_country(leg["destination_country_code"])
        if rating is not None:
            largest = max(largest, rating["insurance_required_coverage_cents"])
    return largest


# ---------------------------------------------------------------------------
# Vendor capacity and selection -- PRD 3.5, 3.8
# ---------------------------------------------------------------------------


def active_overlapping_engagements(vendor_id, starts_at, ends_at):
    """Half-open window intersection: starts before the end, ends after the start."""
    count = 0
    for engagement in engagements_of_vendor(vendor_id):
        if engagement["status"] != "ACTIVE":
            continue
        if engagement["starts_at"] < ends_at and engagement["ends_at"] > starts_at:
            count += 1
    return count


def _ms(instant):
    """Millisecond-precision view of an instant (PRD 3.8 tie-break)."""
    return instant.replace(microsecond=(instant.microsecond // 1000) * 1000)


def select_vendor(capability, country_code, window_start, window_end):
    """PRD 3.8: rank by sla_response_minutes, hourly_rate_cents, retainer_cents,
    then earlier created_at at millisecond precision; id is never consulted."""
    candidates = []
    for vendor in store.vendors.values():
        if vendor["vendor_type"] != capability:
            continue
        if vendor["activation_status"] != "AVAILABLE":
            continue
        if vendor["country_code"] != country_code:
            continue
        overlapping = active_overlapping_engagements(vendor["id"], window_start,
                                                     window_end)
        if overlapping >= vendor["max_concurrent_engagements"]:
            continue
        candidates.append(vendor)
    candidates.sort(key=lambda v: (v["sla_response_minutes"], v["hourly_rate_cents"],
                                   v["retainer_cents"], _ms(v["created_at"]),
                                   v["_seq"]))
    return candidates[0] if candidates else None


def activation_window():
    start = store.now()
    return start, start + timedelta(hours=ACTIVATION_WINDOW_HOURS)


def create_engagement_row(vendor, leg, purpose, starts_at, ends_at, incident_id):
    """Shared engagement construction for manual and triage-created engagements."""
    from store import audit_row
    hours = engagement_hours(starts_at, ends_at)
    row = audit_row({
        "vendor_id": vendor["id"],
        "trip_leg_id": leg["id"],
        "incident_id": incident_id,
        "engagement_purpose": purpose,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "ACTIVE",
        "engagement_hours": hours,
        "engagement_cost_cents": engagement_cost_cents(
            vendor["retainer_cents"], hours, vendor["hourly_rate_cents"]),
        "cancelled_reason": None,
    })
    store.engagements[row["id"]] = row
    vendor["committed_engagement_hours"] += hours
    touch(vendor)
    return row


def cancel_assignment(assignment, reason):
    """PRD 3.5: cost forced to 0, basis VOID, committed hours restored exactly."""
    assignment["status"] = "CANCELLED"
    assignment["cost_cents"] = 0
    assignment["cost_basis"] = "VOID"
    assignment["cancelled_reason"] = reason
    staff_row = store.staff.get(assignment["staff_id"])
    if staff_row is not None:
        staff_row["committed_detail_hours"] -= assignment["planned_billable_hours"]
        touch(staff_row)
    touch(assignment)


def leg_of_trip_by_sequence(trip_id, sequence_no):
    for leg in legs_of_trip(trip_id):
        if leg["sequence_no"] == sequence_no:
            return leg
    return None


def duress_affected_sequence_no(trip):
    """PRD 3.7 hop three: the lowest-numbered leg whose on-ground window contains
    the clock reading, or simply the lowest sequence_no on the trip."""
    legs = legs_of_trip(trip["id"])
    if not legs:
        return None
    now = store.now()
    for leg in legs:
        if leg["arrive_at"] <= now < leg["depart_at"]:
            return leg["sequence_no"]
    return legs[0]["sequence_no"]


def recount_missed_check_ins(trip):
    """PRD 3.7: the number of that trip's check-in rows whose late is true."""
    trip["missed_check_in_count"] = sum(
        1 for row in checkins_of_trip(trip["id"]) if row["late"])


# ---------------------------------------------------------------------------
# Cascade B -- risk-assessment approval (PRD 2.12, 3.2)
# ---------------------------------------------------------------------------


def cascade_assessment_approval(assessment, approver_id):
    from calc import threat_level_for

    executive = get_executive(assessment["executive_id"])

    # Hop one.
    assessment["status"] = "APPROVED"
    assessment["approved_by_staff_id"] = approver_id
    assessment["approved_at"] = store.now()
    executive["threat_level"] = threat_level_for(assessment["composite_risk_score"])
    touch(executive)

    # Hop two: the unique other row with the same executive_id and APPROVED.
    prior = None
    candidates = [row for row in store.assessments.values()
                  if row["id"] != assessment["id"]
                  and row["executive_id"] == assessment["executive_id"]
                  and row["status"] == "APPROVED"]
    candidates.sort(key=lambda r: r["_seq"])
    if candidates:
        prior = candidates[0]
        prior["status"] = "SUPERSEDED"
        assessment["supersedes_assessment_id"] = prior["id"]
        touch(prior)
    touch(assessment)

    # Hop three: re-point the superseded assessment's non-closed trips.
    repointed = []
    if prior is not None:
        trips = [t for t in store.trips.values()
                 if t["risk_assessment_id"] == prior["id"]
                 and t["readiness_state"] != "CLOSED"]
        trips.sort(key=lambda t: t["_seq"])
        for trip in trips:
            trip["risk_assessment_id"] = assessment["id"]
            repointed.append(trip)

    # Hop four: re-derive everything beneath those re-pointed trips.
    for trip in repointed:
        prior_level = trip["required_approval_level"]
        for leg in legs_of_trip(trip["id"]):
            recompute_leg_band(leg, trip, executive)
            touch(leg)
        recompute_trip_band_and_level(trip)
        if (trip["approval_state"] == "APPROVED"
                and level_rank(trip["required_approval_level"]) > level_rank(prior_level)):
            trip["approval_state"] = "PENDING_REVIEW"
            trip["briefing_ack_at"] = None
        if trip["readiness_state"] == "READY" and any_leg_advance_incomplete(trip):
            degrade_trip(trip)
        trip["check_in_interval_hours"] = check_in_interval_hours(
            trip["duress_active"], trip["readiness_state"], trip["max_leg_risk_band"])
        touch(trip)


# ---------------------------------------------------------------------------
# Cascade C -- destination-rating revision (PRD 2.12, 3.3)
# ---------------------------------------------------------------------------


def cascade_destination_revision(rating):
    # Hop one.
    recompute_rating_derived(rating)
    touch(rating)

    # Hop two: every non-closed leg pointing at this country.
    affected_legs = []
    for leg in store.legs.values():
        if leg["destination_country_code"] != rating["country_code"]:
            continue
        trip = trip_of_leg(leg)
        if trip is None or trip["readiness_state"] == "CLOSED":
            continue
        affected_legs.append(leg)
    affected_legs.sort(key=lambda l: l["_seq"])

    trips = []
    seen = set()
    for leg in affected_legs:
        trip = trip_of_leg(leg)
        recompute_leg_band(leg, trip, executive_of_trip(trip))
        touch(leg)
        if trip["id"] not in seen:
            seen.add(trip["id"])
            trips.append(trip)
    trips.sort(key=lambda t: t["_seq"])

    # Hops three and four.
    for trip in trips:
        prior_level = trip["required_approval_level"]
        recompute_trip_band_and_level(trip)
        if trip["readiness_state"] == "READY" and any_leg_advance_incomplete(trip):
            degrade_trip(trip)
        else:
            recompute_advance_readiness(trip)
        if (trip["approval_state"] == "APPROVED"
                and level_rank(trip["required_approval_level"]) > level_rank(prior_level)):
            trip["approval_state"] = "PENDING_REVIEW"
            trip["briefing_ack_at"] = None
        touch(trip)


# ---------------------------------------------------------------------------
# Cascade D -- trip denial (PRD 2.12, 3.6)
# ---------------------------------------------------------------------------


def cascade_trip_denial(trip, denied_reason):
    # Hop one.
    trip["approval_state"] = "DENIED"
    trip["denied_reason"] = denied_reason
    # Hop two.
    for assignment in assignments_of_trip(trip["id"]):
        if assignment["status"] == "CONFIRMED":
            cancel_assignment(assignment, "TRIP_DENIED")
    # Hop three: restore the money ledger to its pre-submission value.
    executive = executive_of_trip(trip)
    executive["committed_budget_cents"] -= trip["provisional_security_cost_cents"]
    touch(executive)
    touch(trip)


# ---------------------------------------------------------------------------
# Cascade A -- vendor suspension (PRD 2.12, 3.5)
# ---------------------------------------------------------------------------


def cascade_vendor_suspension(vendor, suspension_reason):
    # Hop one.
    vendor["activation_status"] = "SUSPENDED"
    vendor["suspension_reason"] = suspension_reason
    touch(vendor)

    # Hop two.
    cancelled = []
    for engagement in engagements_of_vendor(vendor["id"]):
        if engagement["status"] != "ACTIVE":
            continue
        engagement["status"] = "CANCELLED"
        engagement["engagement_cost_cents"] = 0
        engagement["cancelled_reason"] = "VENDOR_SUSPENDED"
        vendor["committed_engagement_hours"] -= engagement["engagement_hours"]
        touch(engagement)
        cancelled.append(engagement)
    touch(vendor)

    # Hop three: the only mechanism that ever un-records an advance item.
    trips = []
    seen = set()
    for engagement in cancelled:
        if engagement["engagement_purpose"] != "LOCAL_LIAISON":
            continue
        leg = store.legs.get(engagement["trip_leg_id"])
        if leg is None:
            continue
        if "LOCAL_LIAISON" in leg["completed_advance_items"]:
            leg["completed_advance_items"] = [
                item for item in leg["completed_advance_items"]
                if item != "LOCAL_LIAISON"]
        recompute_advance_complete(leg)
        touch(leg)
        trip = trip_of_leg(leg)
        if (trip is not None and trip["readiness_state"] != "CLOSED"
                and trip["id"] not in seen):
            seen.add(trip["id"])
            trips.append(trip)
    trips.sort(key=lambda t: t["_seq"])

    # Hops four and five.
    for trip in trips:
        if trip["readiness_state"] == "READY" and any_leg_advance_incomplete(trip):
            degrade_trip(trip)
        elif recompute_advance_readiness(trip):
            touch(trip)
