"""Derivation breadth: the retention selection rule, the lot waterfall's shelf-life
constant and its ranking keys, the empty-candidate branch, the placement standard,
the half-open outcome windows and the band repropagation a re-assessment forces."""

from typing import Any, Dict

from test_helpers import factories as f
from test_helpers import get_success_data, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_calendar_date, assert_number_equals
from test_helpers.constants import (
    AssessmentBasis,
    AssessmentStatus,
    ContactMethod,
    DeviceType,
    FollowUpOutcome,
    HouseholdStatus,
    InstallStatus,
    InstallationStatus,
    PlacementLocation,
    PriorityBand,
    RiskTier,
)
from test_helpers.fixtures import (
    arrive,
    assess_zone,
    book_visit,
    create_assessed_zone,
    create_crew,
    create_household,
    create_lot,
    create_published_route,
    defer_visit,
    deliver_education,
    funded_arrived_visit,
    log_follow_up,
    pin_clock,
    read_grant,
    read_household,
    read_installation,
    read_lot,
    read_visit,
    read_zone,
    record_fire_incident,
    reserve_installation,
)
from test_helpers.test_users import ANALYST, COORDINATOR, make_crr_technician_headers

# The zone Ashgrove scores 40.00 + 10.00 + 9.00 + 4.40 on its statistical inputs, so
# its tier turns entirely on which alarm-gap variant the assessment basis selects.
ASHGROVE = {
    "zone_code": "Z-A66",
    "name": "Ashgrove Leaf",
    "occupied_units": 2000,
    "structure_fire_count_5yr": 20,
    "fire_injury_count_5yr": 2,
    "pre_1980_unit_pct": 60.0,
    "senior_household_pct": 25.0,
    "under5_household_pct": 10.0,
    "disability_household_pct": 5.0,
    "assumed_alarm_absence_pct": 30.0,
    "daily_visit_cap": 12,
}


def _deferred_household(
    api,
    zone_id: str,
    crew_id: str,
    route_id: str,
    address_line: str,
    scheduled_start_utc: str = "2026-08-03T14:00:00Z",
    pre_existing_working_smoke_alarms: int = 2,
    **household_overrides: Any,
) -> Dict[str, Any]:
    """Take one household to VISIT_COMPLETED through the deferred close-out branch."""
    household = create_household(
        api, zone_id, address_line=address_line, **household_overrides
    )
    visit = book_visit(
        api, household["id"], route_id, scheduled_start_utc=scheduled_start_utc
    )
    arrive(
        api,
        visit["id"],
        crew_id,
        pre_existing_working_smoke_alarms=pre_existing_working_smoke_alarms,
    )
    deliver_education(api, visit["id"], crew_id)
    defer_visit(api, visit["id"], crew_id)
    return household


def test_01_retention_counts_only_the_latest_eligible_contact_per_household(api):
    """Two eligible contacts on one household contribute one row; a NO_ANSWER-only
    household contributes none, so the rate is 100.00 over an eligible count of 1.

    PRD: "If a household has no such row it contributes to neither side of the ratio
    - a household whose only contacts went unanswered is not counted as a loss.
    Otherwise the household contributes exactly one row: the one with the greatest
    `attempt_no`, which is unique per household so no further tie-break is
    reachable."

    Design: Corner/calculations/retention_rate_counts_only_the_latest_eligible_contact_per_household
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-B1")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    first = _deferred_household(api, zone["id"], crew["id"], route["id"], "1 Birch Road")
    second = _deferred_household(
        api,
        zone["id"],
        crew["id"],
        route["id"],
        "2 Birch Road",
        scheduled_start_utc="2026-08-03T16:00:00Z",
    )
    pin_clock(api, "2026-09-05T00:00:00Z")

    missing = log_follow_up(
        api,
        first["id"],
        contact_method=ContactMethod.PHONE,
        outcome=FollowUpOutcome.REACHED_ALARM_MISSING,
    )
    present = get_success_data(
        api.create_follow_up(
            f.follow_up_reached_present_payload(
                first["id"],
                alarms_present_count=2,
                plan_practiced=True,
                contact_method=ContactMethod.DOOR_KNOCK,
            ),
            COORDINATOR,
        ),
        201,
    )
    unanswered = log_follow_up(
        api,
        second["id"],
        contact_method=ContactMethod.PHONE,
        outcome=FollowUpOutcome.NO_ANSWER,
    )
    assert missing["attempt_no"] == 1
    assert present["attempt_no"] == 2
    assert unanswered["attempt_no"] == 1

    summary = get_success_data(api.get_outcome_summary(zone["id"], ANALYST))
    assert summary["retention_eligible_count"] == 1
    assert_number_equals(summary["retention_rate_pct"], 100.00, "retention_rate_pct")
    assert summary["served_household_count"] == 2
    assert summary["baseline_fire_count"] == 0
    assert summary["post_fire_count"] == 0
    assert summary["rate_delta_pct"] is None

    assert read_household(api, first["id"])["status"] == HouseholdStatus.REVISIT_REQUIRED
    assert read_household(api, second["id"])["status"] == HouseholdStatus.VISIT_COMPLETED


def test_02_the_selector_skips_the_lot_inside_the_ninety_day_shelf_window(api):
    """A lot expiring 2026-09-15 would rank first on expiry, but at clock 2026-08-01
    it is inside the ninety-day shelf window, so the 2028 lot is selected instead.

    PRD: "its `expiry_date` is on or after the logical clock's calendar date advanced
    by 90 days, so that no device is fitted with under three months of sealed-battery
    shelf life remaining"

    Design: Corner/calculations/device_lot_selector_skips_the_lot_inside_the_minimum_shelf_window
    """
    ctx = funded_arrived_visit(
        api,
        pre_existing_working_smoke_alarms=1,
        lot_overrides={
            "sku": "SMK-NEAR",
            "unit_cost_cents": 1200,
            "received_qty": 10,
            "expiry_date": "2026-09-15",
        },
        household_overrides={"address_line": "9 Birch Road"},
        route_overrides={"planned_slots": 4},
    )
    near = ctx["lot"]
    far = create_lot(
        api,
        ctx["grant"]["id"],
        sku="SMK-FAR",
        unit_cost_cents=1850,
        received_qty=10,
        expiry_date="2028-06-30",
    )

    installation = reserve_installation(
        api,
        ctx["visit"]["id"],
        ctx["crew"]["id"],
        placement_location=PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
        storey=1,
    )
    assert installation["device_lot_id"] == far["id"]
    assert installation["device_lot_id"] != near["id"]
    assert installation["status"] == InstallationStatus.RESERVED
    assert read_lot(api, far["id"])["reserved_qty"] == 1
    assert read_lot(api, near["id"])["reserved_qty"] == 0


def test_03_the_selector_ranks_expiry_ahead_of_unit_cost(api):
    """Of three eligible lots the cheapest is not chosen: the earlier expiry date wins
    first, and cost only breaks the tie between the two lots sharing that date.

    PRD: "The surviving candidates are then ranked first-in-first-out on shelf life
    and then on price: ascending `expiry_date` first, and among lots sharing an expiry
    date, ascending `unit_cost_cents`."

    Design: Corner/calculations/device_lot_selector_ranks_expiry_before_unit_cost
    """
    ctx = funded_arrived_visit(
        api,
        pre_existing_working_smoke_alarms=1,
        lot_overrides={
            "sku": "SMK-A",
            "unit_cost_cents": 2100,
            "received_qty": 5,
            "expiry_date": "2027-06-30",
        },
        household_overrides={"address_line": "9 Birch Road"},
        route_overrides={"planned_slots": 4},
    )
    lot_a = ctx["lot"]
    lot_b = create_lot(
        api,
        ctx["grant"]["id"],
        sku="SMK-B",
        unit_cost_cents=1850,
        received_qty=5,
        expiry_date="2027-06-30",
    )
    lot_c = create_lot(
        api,
        ctx["grant"]["id"],
        sku="SMK-C",
        unit_cost_cents=1500,
        received_qty=5,
        expiry_date="2028-06-30",
    )

    installation = reserve_installation(
        api,
        ctx["visit"]["id"],
        ctx["crew"]["id"],
        placement_location=PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
        storey=1,
    )
    assert installation["device_lot_id"] == lot_b["id"]
    assert read_lot(api, lot_b["id"])["reserved_qty"] == 1
    assert read_lot(api, lot_a["id"])["reserved_qty"] == 0
    assert read_lot(api, lot_c["id"])["reserved_qty"] == 0


def test_04_an_empty_candidate_set_never_falls_back_to_a_wrong_type_lot(api):
    """The grant funds smoke alarms, but only a CO lot was ever received, so an
    omitted lot reference has nothing to resolve to.

    PRD: "If the candidate set is empty the request is rejected with
    `ERR_NO_ELIGIBLE_DEVICE_LOT` (HTTP 422)."

    Design: Corner/calculations/installation_with_no_matching_lot_returns_no_eligible_device_lot
    """
    ctx = funded_arrived_visit(
        api,
        pre_existing_working_smoke_alarms=1,
        lot_overrides={
            "sku": "CO-A",
            "device_type": DeviceType.CO_ALARM,
            "unit_cost_cents": 2990,
            "received_qty": 5,
            "expiry_date": "2028-06-30",
        },
        household_overrides={"address_line": "9 Birch Road"},
        route_overrides={"planned_slots": 4},
    )

    response = api.create_installation(
        f.installation_payload(
            ctx["visit"]["id"],
            device_type=DeviceType.SMOKE_10YR,
            placement_location=PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
            storey=1,
        ),
        make_crr_technician_headers(ctx["crew"]["id"]),
    )
    validate_error(response, ApiErrorId.NO_ELIGIBLE_DEVICE_LOT, 422)

    assert read_lot(api, ctx["lot"]["id"])["reserved_qty"] == 0
    assert read_grant(api, ctx["grant"]["id"])["reserved_cents"] == 0


def test_05_coverage_one_smoke_alarm_short_fails_the_placement_standard(api):
    """Two sleeping areas across two storeys need four smoke devices; two pre-existing
    alarms plus one reservation is three, so the COMPLETE branch is refused.

    PRD: "The standard is satisfied only when smoke coverage is at least the
    household's `required_smoke_devices`, carbon monoxide coverage is at least
    `required_co_devices`, and strobe coverage is at least `required_strobe_devices`;
    meeting a requirement exactly counts as meeting it."

    Design: Corner/calculations/visit_complete_one_smoke_alarm_short_returns_placement_standard_not_met
    """
    ctx = funded_arrived_visit(
        api,
        pre_existing_working_smoke_alarms=2,
        household_overrides={
            "address_line": "9 Birch Road",
            "occupant_count": 4,
            "sleeping_areas_count": 2,
            "storeys": 2,
        },
        route_overrides={"planned_slots": 4},
    )
    assert read_household(api, ctx["household"]["id"])["required_smoke_devices"] == 4

    installation = reserve_installation(
        api,
        ctx["visit"]["id"],
        ctx["crew"]["id"],
        device_lot_id=ctx["lot"]["id"],
        placement_location=PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
        storey=1,
    )
    deliver_education(api, ctx["visit"]["id"], ctx["crew"]["id"])

    response = api.complete_visit(
        ctx["visit"]["id"],
        f.complete_payload(occupant_signature_name="R. Vance"),
        make_crr_technician_headers(ctx["crew"]["id"]),
    )
    validate_error(response, ApiErrorId.PLACEMENT_STANDARD_NOT_MET, 422)

    assert read_visit(api, ctx["visit"]["id"])["install_status"] == InstallStatus.SURVEYED
    assert read_installation(api, installation["id"])["status"] == InstallationStatus.RESERVED
    lot = read_lot(api, ctx["lot"]["id"])
    assert lot["consumed_qty"] == 0
    assert lot["reserved_qty"] == 1
    assert read_grant(api, ctx["grant"]["id"])["committed_cents"] == 0


def test_06_an_incident_exactly_at_the_anchor_belongs_to_the_post_window(api):
    """One incident at the anchor instant and one a quarter earlier: the anchor
    incident is post, and the order the two were recorded in is irrelevant.

    PRD: "The boundary rule matters: an incident whose `occurred_at` equals the anchor
    exactly belongs to the **post** window, never to the baseline."

    Design: Corner/calculations/an_incident_exactly_at_the_service_anchor_counts_as_post_not_baseline
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-B1")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    _deferred_household(api, zone["id"], crew["id"], route["id"], "9 Birch Road")
    pin_clock(api, "2026-09-05T00:00:00Z")

    record_fire_incident(
        api,
        zone["id"],
        incident_number="INC-2026-POST",
        occurred_at="2026-08-01T00:00:00Z",
        working_alarm_present=True,
        injuries=1,
    )
    record_fire_incident(
        api,
        zone["id"],
        incident_number="INC-2026-BASE",
        occurred_at="2026-05-01T03:20:00Z",
        working_alarm_present=False,
        injuries=2,
    )

    summary = get_success_data(api.get_outcome_summary(zone["id"], ANALYST))
    assert_calendar_date(summary["service_start_date"], "service_start_date")
    assert summary["service_start_date"] == "2026-08-01"
    assert summary["baseline_fire_count"] == 1
    assert summary["post_fire_count"] == 1
    assert_number_equals(
        summary["baseline_fire_rate_per_1000"], 0.50, "baseline_fire_rate_per_1000"
    )
    assert_number_equals(summary["post_fire_rate_per_1000"], 0.50, "post_fire_rate_per_1000")
    assert_number_equals(summary["rate_delta_pct"], 0.00, "rate_delta_pct")
    assert summary["baseline_injuries"] == 2
    assert summary["post_injuries"] == 1
    assert summary["injury_delta"] == -1


def test_07_a_validated_re_assessment_repropagates_every_household_band(api):
    """The same zone row scores 66.40 / TIER_2 on the assumed gap and 73.40 / TIER_1 on
    the field gap, and the re-run rebands the vulnerable household in the same request.

    PRD: "A completed run writes `risk_score`, `risk_tier` and `assessment_basis` back
    onto the zone, points `current_assessment_id` at the new row, recomputes the
    priority band of every household in the zone (§3.3), and increments the zone's
    `version` by 1."

    Design: Corner/calculations/re_assessment_on_field_data_repropagates_every_household_priority_band
    """
    pin_clock(api)
    zone = create_assessed_zone(api, **ASHGROVE)
    assert_number_equals(zone["risk_score"], 66.40, "risk_score")
    assert zone["risk_tier"] == RiskTier.TIER_2
    assert zone["assessment_basis"] == AssessmentBasis.PROVISIONAL

    vulnerable = create_household(
        api, zone["id"], address_line="9 Ash Lane", occupant_count=2, adults_65plus=1
    )
    other = create_household(api, zone["id"], address_line="10 Ash Lane")
    assert vulnerable["priority_band"] == PriorityBand.P2_ELEVATED
    assert other["priority_band"] == PriorityBand.P3_STANDARD

    crew = create_crew(api, crew_code="CREW-A1")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    visit = book_visit(api, vulnerable["id"], route["id"])
    arrive(api, visit["id"], crew["id"], pre_existing_working_smoke_alarms=0)
    deliver_education(api, visit["id"], crew["id"])
    defer_visit(api, visit["id"], crew["id"])

    surveyed = read_zone(api, zone["id"])
    assert surveyed["surveyed_units"] == 1
    assert surveyed["surveyed_units_without_alarm"] == 1
    assert surveyed["assessment_status"] == AssessmentStatus.SERVICE_ACTIVE

    assessment = assess_zone(
        api, zone["id"], surveyed["version"], basis=AssessmentBasis.VALIDATED
    )
    assert assessment["sequence_no"] == 2
    assert assessment["basis"] == AssessmentBasis.VALIDATED

    rescored = read_zone(api, zone["id"])
    assert_number_equals(rescored["risk_score"], 73.40, "risk_score")
    assert rescored["risk_tier"] == RiskTier.TIER_1
    assert rescored["assessment_basis"] == AssessmentBasis.VALIDATED
    assert rescored["current_assessment_id"] == assessment["id"]
    assert rescored["assessment_status"] == AssessmentStatus.SERVICE_ACTIVE

    assert read_household(api, vulnerable["id"])["priority_band"] == PriorityBand.P1_HIGH_RISK
    assert read_household(api, other["id"])["priority_band"] == PriorityBand.P2_ELEVATED
