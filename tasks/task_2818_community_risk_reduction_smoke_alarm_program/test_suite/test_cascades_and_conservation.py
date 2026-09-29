"""Multi-hop cascades and the two conserved ledgers.

A failed effectiveness follow-up walks the household, the escape plan, the zone's
survey counters and the parent district's rollup. A cancellation walks the device
and money ledgers in the opposite direction. Voiding either kind of installation
returns both ledgers exactly to where they stood.
"""

from typing import Any, Dict

from test_helpers import factories as f
from test_helpers import get_success_data
from test_helpers.assertions import (
    assert_grant_money_balanced,
    assert_instant_equals,
    assert_lot_status_derived,
    assert_lot_units_conserved,
    assert_null_not_zero,
    assert_number_equals,
)
from test_helpers.constants import (
    CancelReason,
    ContactMethod,
    FollowUpOutcome,
    HouseholdStatus,
    InstallStatus,
    InstallationStatus,
    LapseReason,
    LotStatus,
    PlanStatus,
    RiskTier,
    VisitStatus,
    VoidedReason,
)
from test_helpers.fixtures import (
    arrive,
    assess_zone,
    book_visit,
    complete_visit,
    create_active_grant,
    create_assessed_zone,
    create_crew,
    create_district_with_children,
    create_escape_plan,
    create_household,
    create_lot,
    create_partner,
    create_published_route,
    deliver_education,
    issue_escape_plan,
    log_follow_up,
    pin_clock,
    read_escape_plan,
    read_grant,
    read_household,
    read_installation,
    read_lot,
    read_route,
    read_visit,
    read_zone,
    reserve_installation,
)
from test_helpers.test_users import ANALYST, COORDINATOR, OFFICER

CEDARHILL = {
    "zone_code": "Z-C38",
    "name": "Cedarhill Leaf",
    "occupied_units": 1000,
    "structure_fire_count_5yr": 5,
    "fire_injury_count_5yr": 1,
    "pre_1980_unit_pct": 20.0,
    "senior_household_pct": 10.0,
    "under5_household_pct": 5.0,
    "disability_household_pct": 0.0,
    "assumed_alarm_absence_pct": 40.0,
    "daily_visit_cap": 5,
}


def _validated_district_tree(api) -> Dict[str, Any]:
    """A district over two leaves where the larger leaf is scored on field data.

    The larger leaf holds a served household with a verified escape plan and a
    second, still-queued household, so the leaf sits at `SERVICE_ACTIVE` while its
    effective basis is the validated one.
    """
    pin_clock(api)
    tree = create_district_with_children(api, child_overrides=[{}, dict(CEDARHILL)])
    birchwood, cedarhill = tree["children"]

    assess_zone(api, cedarhill["id"], cedarhill["version"])
    assess_zone(api, birchwood["id"], birchwood["version"])

    crew = create_crew(api)
    served = create_household(
        api, birchwood["id"], address_line="5 Cedar Court", adults_65plus=1
    )
    create_household(api, birchwood["id"], address_line="6 Cedar Court")
    route = create_published_route(api, birchwood["id"], crew["id"], planned_slots=2)
    visit = book_visit(api, served["id"], route["id"])
    arrive(api, visit["id"], crew["id"], pre_existing_working_smoke_alarms=2)
    deliver_education(api, visit["id"], crew["id"])
    complete_visit(api, visit["id"], crew["id"], occupant_signature_name="D. Farkas")

    scored = read_zone(api, birchwood["id"])
    validated = assess_zone(api, birchwood["id"], scored["version"], basis="VALIDATED")

    household = read_household(api, served["id"])
    plan = create_escape_plan(
        api,
        household["id"],
        household["version"],
        meeting_point_description="Mailbox at 5 Cedar Court",
    )
    issue_escape_plan(api, plan["id"])

    pin_clock(api, "2026-09-05T00:00:00Z")
    log_follow_up(
        api,
        household["id"],
        outcome=FollowUpOutcome.REACHED_ALARM_PRESENT,
        alarms_present_count=2,
        plan_practiced=True,
    )

    return {
        "district": tree["parent"],
        "birchwood": read_zone(api, birchwood["id"]),
        "cedarhill": read_zone(api, cedarhill["id"]),
        "household": read_household(api, household["id"]),
        "plan": read_escape_plan(api, plan["id"]),
        "validated_assessment": validated,
    }


def test_01_a_missing_alarm_reopens_the_household_and_lapses_its_plan(api):
    """The contact row flips the household, and that flip lapses the live plan.

    PRD: "The household moves `VISIT_COMPLETED → REVISIT_REQUIRED` and its
    `alarm_retention_flag` is set to false ... At hop two, the household's live escape
    plan - the one in `ISSUED` or `VERIFIED` - moves to `LAPSED` with `lapse_reason`
    `ALARM_MISSING_AT_FOLLOW_UP`..."

    Design: Difficulty/transitive_cascade/follow_up_alarm_missing_cascades_household_then_zone_then_district
    """
    ctx = _validated_district_tree(api)
    assert ctx["plan"]["status"] == PlanStatus.VERIFIED
    assert_number_equals(ctx["birchwood"]["risk_score"], 49.52, "risk_score")

    contact = log_follow_up(
        api,
        ctx["household"]["id"],
        contact_method=ContactMethod.DOOR_KNOCK,
        outcome=FollowUpOutcome.REACHED_ALARM_MISSING,
        alarms_present_count=0,
    )
    assert contact["attempt_no"] == 2
    assert contact["days_since_visit"] == 35

    household = read_household(api, ctx["household"]["id"])
    assert household["status"] == HouseholdStatus.REVISIT_REQUIRED
    assert household["alarm_retention_flag"] is False

    plan = read_escape_plan(api, ctx["plan"]["id"])
    assert plan["status"] == PlanStatus.LAPSED
    assert plan["lapse_reason"] == LapseReason.ALARM_MISSING_AT_FOLLOW_UP


def test_02_the_alarm_loss_rescores_the_zone_and_rolls_up_to_the_district(api):
    """The zone counter re-runs the validated score, which re-runs the rollup.

    PRD: "...and the zone's `post_service_alarm_loss_units` increments by 1, which,
    **when the zone's `assessment_basis` is `VALIDATED`**, re-runs the zone's risk
    score under the validated variant ... At hop three, if that re-run actually changed
    the zone's `risk_score` and the zone has a parent, the parent district re-runs its
    unit-weighted rollup..."

    Design: Difficulty/transitive_cascade/follow_up_alarm_missing_cascades_household_then_zone_then_district
    """
    ctx = _validated_district_tree(api)
    assert_number_equals(read_zone(api, ctx["district"]["id"])["risk_score"], 45.91)

    log_follow_up(
        api,
        ctx["household"]["id"],
        contact_method=ContactMethod.DOOR_KNOCK,
        outcome=FollowUpOutcome.REACHED_ALARM_MISSING,
        alarms_present_count=0,
    )

    zone = read_zone(api, ctx["birchwood"]["id"])
    assert zone["post_service_alarm_loss_units"] == 1
    assert_number_equals(zone["risk_score"], 59.52, "risk_score")
    assert zone["risk_tier"] == RiskTier.TIER_2
    assert zone["assessment_status"] == "SERVICE_ACTIVE"

    district = read_zone(api, ctx["district"]["id"])
    assert district["zone_kind"] == "DISTRICT"
    assert_number_equals(district["risk_score"], 52.58, "district risk_score")
    assert_number_equals(
        read_zone(api, ctx["cedarhill"]["id"])["risk_score"], 38.70, "sibling risk_score"
    )


def _reserved_installation(api) -> Dict[str, Any]:
    """One SMOKE_10YR device held against an active grant on a mid-flight visit."""
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api)
    partner = create_partner(api)
    grant = create_active_grant(api, partner["id"])
    lot = create_lot(api, grant["id"])
    household = create_household(api, zone["id"], address_line="8 Cedar Way")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=2)
    visit = book_visit(api, household["id"], route["id"])
    arrive(api, visit["id"], crew["id"])
    installation = reserve_installation(
        api, visit["id"], crew["id"], device_lot_id=lot["id"]
    )
    return {
        "zone": zone,
        "crew": crew,
        "grant": grant,
        "lot": lot,
        "household": household,
        "route": route,
        "visit": visit,
        "installation": installation,
    }


def test_03_cancelling_a_visit_voids_the_device_reservation_it_was_holding(api):
    """The cancellation walks down to the installation and back up to the lot.

    PRD: "Cancellation stamps `cancelled_at` from the logical clock, stores the
    `cancel_reason`, sets `occupies_crew_calendar` to false so the slot on the crew's
    calendar is genuinely released, decrements the route's `booked_slot_count` by 1 ...
    voids every device reservation the visit was holding (returning each unit to its lot
    and each held amount to its grant, per §3.6)..."

    Design: Difficulty/transitive_cascade/visit_cancel_cascades_installation_then_lot_then_grant
    """
    ctx = _reserved_installation(api)
    held = read_lot(api, ctx["lot"]["id"])
    assert held["reserved_qty"] == 1
    assert held["on_hand_qty"] == 10

    cancelled = get_success_data(
        api.cancel_visit(
            ctx["visit"]["id"],
            f.cancel_payload(CancelReason.RESCHEDULE_REQUESTED),
            COORDINATOR,
        )
    )
    assert cancelled["visit_status"] == VisitStatus.CANCELLED
    assert_instant_equals(cancelled["cancelled_at"], "2026-08-01T00:00:00Z", "cancelled_at")

    installation = read_installation(api, ctx["installation"]["id"])
    assert installation["status"] == InstallationStatus.VOIDED

    lot = read_lot(api, ctx["lot"]["id"])
    assert (lot["on_hand_qty"], lot["reserved_qty"], lot["consumed_qty"]) == (10, 0, 0)
    assert lot["status"] == LotStatus.AVAILABLE
    assert_lot_units_conserved(lot)


def test_04_cancelling_a_visit_returns_the_held_money_and_the_slot(api):
    """Hop three of the same spine: the lot movement releases the grant's hold.

    PRD: "`RESCHEDULE_REQUESTED` and `ROUTE_CLOSED` both return the household from
    `APPOINTMENT_SCHEDULED` to `INTAKE_QUEUED`, leaving it eligible for another
    booking."

    Design: Difficulty/transitive_cascade/visit_cancel_cascades_installation_then_lot_then_grant
    """
    ctx = _reserved_installation(api)
    assert read_grant(api, ctx["grant"]["id"])["reserved_cents"] == 1921

    get_success_data(
        api.cancel_visit(
            ctx["visit"]["id"],
            f.cancel_payload(CancelReason.RESCHEDULE_REQUESTED),
            COORDINATOR,
        )
    )

    grant = read_grant(api, ctx["grant"]["id"])
    assert grant["reserved_cents"] == 0
    assert grant["committed_cents"] == 0
    assert grant["available_cents"] == 500000
    assert_grant_money_balanced(grant)

    assert read_route(api, ctx["route"]["id"])["booked_slot_count"] == 0
    assert read_household(api, ctx["household"]["id"])["status"] == HouseholdStatus.INTAKE_QUEUED


def test_05_voiding_a_reserved_device_returns_the_unit_to_its_lot(api):
    """The reserved unit never left on_hand, and the hold on it disappears.

    PRD: "Voiding from `RESERVED` decrements the lot's `reserved_qty` by 1 while
    leaving `on_hand_qty` untouched, re-derives the lot's `status`..."

    Design: Difficulty/compensating_invariant/device_units_conserved_when_a_reserved_installation_is_voided
    """
    ctx = _reserved_installation(api)

    voided = get_success_data(
        api.void_installation(
            ctx["installation"]["id"], f.void_payload(VoidedReason.DEVICE_DEFECT), OFFICER
        )
    )
    assert voided["status"] == InstallationStatus.VOIDED
    assert voided["voided_reason"] == VoidedReason.DEVICE_DEFECT
    assert_instant_equals(voided["voided_at"], "2026-08-01T00:00:00Z", "voided_at")

    lot = read_lot(api, ctx["lot"]["id"])
    assert (lot["on_hand_qty"], lot["reserved_qty"], lot["consumed_qty"]) == (10, 0, 0)
    assert_lot_units_conserved(lot)
    assert_lot_status_derived(lot)
    assert read_visit(api, ctx["visit"]["id"])["install_status"] == InstallStatus.SURVEYED


def test_06_voiding_a_reserved_device_releases_exactly_what_it_held(api):
    """The grant's reserved money returns to available, cent for cent.

    PRD: "...decrements the grant's `reserved_cents` by the installation's
    `reimbursable_cents` and increases `available_cents` by the same amount."

    Design: Difficulty/compensating_invariant/device_units_conserved_when_a_reserved_installation_is_voided
    """
    ctx = _reserved_installation(api)
    before = read_grant(api, ctx["grant"]["id"])
    assert before["reserved_cents"] == 1921
    assert before["available_cents"] == 498079

    get_success_data(
        api.void_installation(
            ctx["installation"]["id"], f.void_payload(VoidedReason.DEVICE_DEFECT), OFFICER
        )
    )

    grant = read_grant(api, ctx["grant"]["id"])
    assert grant["reserved_cents"] == 0
    assert grant["available_cents"] == 500000
    assert_grant_money_balanced(grant)


def _committed_installation(api) -> Dict[str, Any]:
    """One SMOKE_10YR device committed by a closed-out visit, with no report yet."""
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api)
    partner = create_partner(api)
    grant = create_active_grant(api, partner["id"])
    lot = create_lot(api, grant["id"])
    household = create_household(api, zone["id"], address_line="8 Cedar Way")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=2)
    visit = book_visit(api, household["id"], route["id"])
    arrive(api, visit["id"], crew["id"], pre_existing_working_smoke_alarms=1)
    installation = reserve_installation(
        api, visit["id"], crew["id"], device_lot_id=lot["id"]
    )
    deliver_education(api, visit["id"], crew["id"])
    visit = complete_visit(api, visit["id"], crew["id"])
    return {
        "grant": grant,
        "lot": lot,
        "visit": visit,
        "installation": read_installation(api, installation["id"]),
    }


def test_07_voiding_a_committed_device_puts_the_unit_back_on_the_shelf(api):
    """The consumed unit is returned to on_hand, so nothing is lost or duplicated.

    PRD: "Voiding from `INSTALLED` decrements the lot's `consumed_qty` by 1 and
    increments its `on_hand_qty` by 1, again re-deriving `status`..."

    Design: Difficulty/compensating_invariant/grant_money_conserved_when_a_committed_installation_is_voided
    """
    ctx = _committed_installation(api)
    assert ctx["installation"]["status"] == InstallationStatus.INSTALLED
    committed_lot = read_lot(api, ctx["lot"]["id"])
    assert (committed_lot["on_hand_qty"], committed_lot["consumed_qty"]) == (9, 1)

    voided = get_success_data(
        api.void_installation(
            ctx["installation"]["id"], f.void_payload(VoidedReason.WRONG_PLACEMENT), OFFICER
        )
    )
    assert voided["status"] == InstallationStatus.VOIDED
    assert voided["voided_reason"] == VoidedReason.WRONG_PLACEMENT
    assert voided["reimbursable_cents"] == 1921

    lot = read_lot(api, ctx["lot"]["id"])
    assert (lot["on_hand_qty"], lot["reserved_qty"], lot["consumed_qty"]) == (10, 0, 0)
    assert_lot_units_conserved(lot)
    assert_lot_status_derived(lot)


def test_08_voiding_a_committed_device_rebalances_the_grant_ledger(api):
    """Committed money returns to available and the three buckets still sum.

    PRD: "...decrements the grant's `committed_cents` by `reimbursable_cents` and
    increases `available_cents` by the same amount ... Either way both conserved
    quantities land exactly where they stood before the reservation was ever made."

    Design: Difficulty/compensating_invariant/grant_money_conserved_when_a_committed_installation_is_voided
    """
    ctx = _committed_installation(api)
    before = read_grant(api, ctx["grant"]["id"])
    assert before["committed_cents"] == 1921
    assert before["reserved_cents"] == 0
    assert before["available_cents"] == 498079

    get_success_data(
        api.void_installation(
            ctx["installation"]["id"], f.void_payload(VoidedReason.WRONG_PLACEMENT), OFFICER
        )
    )

    grant = read_grant(api, ctx["grant"]["id"])
    assert grant["reserved_cents"] == 0
    assert grant["committed_cents"] == 0
    assert grant["available_cents"] == 500000
    assert_grant_money_balanced(grant)

    visit = read_visit(api, ctx["visit"]["id"])
    assert visit["install_status"] == InstallStatus.INSTALL_COMPLETE
    assert visit["visit_status"] == VisitStatus.COMPLETED


def _served_household_with_unanswered_contact(api) -> Dict[str, Any]:
    """One served household whose only follow-up went unanswered."""
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api)
    household = create_household(api, zone["id"], address_line="8 Cedar Way")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=2)
    visit = book_visit(api, household["id"], route["id"])
    arrive(api, visit["id"], crew["id"], pre_existing_working_smoke_alarms=2)
    deliver_education(api, visit["id"], crew["id"])
    complete_visit(api, visit["id"], crew["id"], occupant_signature_name="L. Osei")

    pin_clock(api, "2026-09-05T00:00:00Z")
    contact = log_follow_up(
        api, household["id"], contact_method=ContactMethod.PHONE,
        outcome=FollowUpOutcome.NO_ANSWER,
    )
    return {"zone": zone, "household": household, "contact": contact}


def test_09_retention_is_null_when_every_contact_was_unanswered(api):
    """An unanswered call is not a loss, so the eligible set is empty and the rate null.

    PRD: "If a household has no such row it contributes to neither side of the ratio -
    a household whose only contacts went unanswered is not counted as a loss ... When
    the eligible count is zero the result is **null**, never `0.00`."

    Design: Difficulty/boundary_precision_check/retention_rate_is_null_not_zero_when_no_eligible_contact_exists
    """
    ctx = _served_household_with_unanswered_contact(api)
    assert ctx["contact"]["days_since_visit"] == 35
    assert read_household(api, ctx["household"]["id"])["status"] == HouseholdStatus.VISIT_COMPLETED

    summary = get_success_data(api.get_outcome_summary(ctx["zone"]["id"], ANALYST))
    assert summary["service_start_date"] == "2026-08-01"
    assert summary["served_household_count"] == 1
    assert summary["retention_eligible_count"] == 0
    assert_null_not_zero(summary["retention_rate_pct"], "retention_rate_pct")


def test_10_a_zero_baseline_rate_makes_the_delta_null_but_not_the_rates(api):
    """With no incidents at all the two rates are 0.00 while the delta is null.

    PRD: "A percentage rate delta is also derived: it is null whenever
    `baseline_fire_rate_per_1000` is `0.00` - division by a zero baseline is
    meaningless..."

    Design: Difficulty/boundary_precision_check/retention_rate_is_null_not_zero_when_no_eligible_contact_exists
    """
    ctx = _served_household_with_unanswered_contact(api)

    summary = get_success_data(api.get_outcome_summary(ctx["zone"]["id"], ANALYST))
    assert summary["baseline_fire_count"] == 0
    assert summary["post_fire_count"] == 0
    assert_number_equals(summary["baseline_fire_rate_per_1000"], 0.00, "baseline rate")
    assert_number_equals(summary["post_fire_rate_per_1000"], 0.00, "post rate")
    assert_null_not_zero(summary["rate_delta_pct"], "rate_delta_pct")
    assert summary["injury_delta"] == 0
