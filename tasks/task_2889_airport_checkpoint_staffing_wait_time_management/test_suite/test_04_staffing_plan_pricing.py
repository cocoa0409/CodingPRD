"""The eight-step staffing plan cost and its administrative fee tiers.

Covers PRD section 3.3: per-officer rounding before summation, the fee tier
keyed on the subtotal alone, and the two inclusive tier breakpoints.
"""

from test_helpers import (
    DUTY_MANAGER_HEADERS,
    PLANNER_HEADERS,
    assert_admin_fee_rate,
    assert_cents,
    assert_plan_cost,
    validate_success,
)
from test_helpers.fixtures import BAND_1000, BAND_1030, FLIGHT_1030, Scenario

BAND_1100_START = "2026-09-10T11:00:00Z"
BAND_1200_START = "2026-09-10T12:00:00Z"
BAND_1300_START = "2026-09-10T13:00:00Z"
DETAIL_WINDOW_1200 = "2026-09-10T12:00:00Z"


def _tier_two_draft_plan(base: Scenario) -> Scenario:
    """A DRAFT plan holding four non-adjacent bands for one 160 c/min officer.

    Four 30-minute bands an hour apart clear the fifteen-minute rest buffer, so
    all 120 minutes land inside the officer's 120-minute regular cap.
    """
    base.lane = base.create_lane()
    base.officer = base.create_officer(
        badge_number="B-2001",
        full_name="Ben Tier",
        certifications=["STANDARD_LANE"],
        base_rate_cents_per_minute=160,
        weekly_regular_minutes_cap=120,
        weekly_overtime_minutes_cap=600,
    )
    base.extras["bands"] = [
        base.create_band(start, expedited_share_pct=0, seasonal_multiplier=1.00)
        for start in (BAND_1000, BAND_1100_START, BAND_1200_START, BAND_1300_START)
    ]
    base.plan = base.create_plan()
    return base


class TestAdminFeeTierKeyedOnSubtotal:
    """PRD 3.3 step eight - the tier lookup reads subtotal_cents and nothing else."""

    def test_a_subtotal_inside_the_middle_tier_prices_at_the_middle_rate(
        self, base: Scenario
    ):
        """Subtotal 19200 sits in tier two even though the total lands in tier three.

        Design: Difficulty/combinatorial_formula/plan_cost_admin_fee_tier_keyed_on_subtotal_not_total
        """
        plan = _tier_two_draft_plan(base)
        bands = plan.extras["bands"]
        for band in bands[:3]:
            plan.create_assignment(band_id=band["id"])

        last = plan.create_assignment(band_id=bands[3]["id"])
        assert last["planned_minutes"] == 30

        summary = validate_success(
            plan.api.get_plan_cost_summary(plan.plan_id, PLANNER_HEADERS)
        )
        # 120 regular minutes at 160 cents each, no overtime and no details.
        assert_plan_cost(
            summary,
            subtotal_cents=19200,
            admin_fee_rate="0.045",
            admin_fee_cents=864,
            total_cost_cents=20064,
            planned_regular_minutes=120,
            planned_overtime_minutes=0,
            base_cost_cents=19200,
            overtime_cost_cents=0,
            detail_cost_cents=0,
        )
        assert summary["total_cost_cents"] != 19776, (
            "19776 is the answer produced by reading the tier off the total: "
            "20064 >= 20000 would give 0.030 and a 576-cent fee"
        )

    def test_a_draft_plan_reprices_itself_on_every_assignment_write(self, base: Scenario):
        """The cost fields track assignment writes without waiting for a submit.

        Design: Difficulty/combinatorial_formula/plan_cost_admin_fee_tier_keyed_on_subtotal_not_total
        """
        plan = _tier_two_draft_plan(base)
        bands = plan.extras["bands"]
        for band in bands:
            plan.create_assignment(band_id=band["id"])

        stored = validate_success(plan.api.get_staffing_plan(plan.plan_id, PLANNER_HEADERS))
        assert stored["state"] == "DRAFT", "no submit was ever issued"
        assert_admin_fee_rate(stored["admin_fee_rate"], "0.045")
        assert_cents(stored["subtotal_cents"], 19200, "subtotal_cents")
        assert_cents(stored["total_cost_cents"], 20064, "total_cost_cents")


def _two_officer_overtime_plan(base: Scenario) -> Scenario:
    """Two 101 c/min officers, two lanes, two adjacent bands, four assignments.

    Each officer holds 60 planned minutes against a 45-minute regular cap, so
    each carries exactly 15 overtime minutes: 15 * 101 * 1.5 = 2272.5 cents.
    """
    base.build_equipped_lane(position_index=1, serial_prefix="R1")
    base.build_equipped_lane(position_index=2, serial_prefix="R2", secondary_positions=0)
    lane_one, lane_two = base.extras["lanes"]
    officers = [
        base.create_officer(
            badge_number=badge,
            full_name=name,
            certifications=["STANDARD_LANE", "ADVANCED_IMAGING"],
            base_rate_cents_per_minute=101,
            weekly_regular_minutes_cap=45,
            weekly_overtime_minutes_cap=600,
        )
        for badge, name in (("B-3001", "Rho One"), ("B-3002", "Rho Two"))
    ]
    base.extras["officers"] = officers
    band_one = base.create_band(BAND_1000, expedited_share_pct=0, seasonal_multiplier=1.00)
    band_two = base.create_band(BAND_1030, expedited_share_pct=0, seasonal_multiplier=1.00)
    base.create_flight(FLIGHT_1030, flight_number="AA100", seats_sold=10, load_factor_pct=100)
    base.create_flight(BAND_1100_START, flight_number="AA300", seats_sold=10, load_factor_pct=100)
    base.forecast(band_one["id"], "CURVE_BLENDED")
    base.forecast(band_two["id"], "CURVE_BLENDED")
    base.plan = base.create_plan()
    for lane, officer in ((lane_one, officers[0]), (lane_two, officers[1])):
        for band in (band_one, band_two):
            base.create_assignment(
                lane_id=lane["id"], officer_id=officer["id"], band_id=band["id"]
            )
    base.band = band_one
    return base


class TestOvertimeRoundedPerOfficer:
    """PRD 3.3 step five - overtime is rounded half up per officer, then summed."""

    def test_two_half_cent_overtime_components_each_round_up_before_the_sum(
        self, base: Scenario
    ):
        """4546 is round-then-sum; 4545 is the sum-then-round answer and is wrong.

        Design: Corner/calculations/plan_cost_rounds_overtime_per_officer_before_summing
        """
        plan = _two_officer_overtime_plan(base)

        submitted = plan.submit_plan()
        assert submitted["state"] == "SUBMITTED"
        assert_plan_cost(
            submitted,
            subtotal_cents=13636,
            admin_fee_rate="0.045",
            admin_fee_cents=614,
            total_cost_cents=14250,
            planned_regular_minutes=90,
            planned_overtime_minutes=30,
            base_cost_cents=9090,
            overtime_cost_cents=4546,
        )
        assert submitted["overtime_cost_cents"] != 4545, (
            "4545 is round_half_up(2272.5 + 2272.5) computed once over the sum"
        )

    def test_the_computed_cost_summary_agrees_with_the_stored_plan_fields(
        self, base: Scenario
    ):
        """The per-officer breakdown makes the rounding order externally observable.

        Design: Corner/calculations/plan_cost_rounds_overtime_per_officer_before_summing
        """
        plan = _two_officer_overtime_plan(base)
        submitted = plan.submit_plan()

        summary = validate_success(
            plan.api.get_plan_cost_summary(plan.plan_id, PLANNER_HEADERS)
        )
        assert_cents(summary["base_cost_cents"], submitted["base_cost_cents"], "base_cost_cents")
        assert_cents(
            summary["overtime_cost_cents"],
            submitted["overtime_cost_cents"],
            "overtime_cost_cents",
        )
        assert_cents(
            summary["total_cost_cents"], submitted["total_cost_cents"], "total_cost_cents"
        )

        breakdown = summary["officer_breakdown"]
        assert isinstance(breakdown, list)
        assert len(breakdown) == 2, "one row per distinct officer appearing in the plan"
        for row in breakdown:
            minutes = [value for value in row.values() if isinstance(value, int)]
            assert 45 in minutes, f"the per-officer regular split of 45 is missing: {row!r}"
            assert 15 in minutes, f"the per-officer overtime split of 15 is missing: {row!r}"


def _priced(scenario: Scenario) -> dict:
    return validate_success(
        scenario.api.get_plan_cost_summary(scenario.plan_id, PLANNER_HEADERS)
    )


def _cancel_detail(scenario: Scenario, detail_id: str) -> dict:
    return validate_success(
        scenario.api.cancel_surge_detail(detail_id, DUTY_MANAGER_HEADERS)
    )


class TestAdminFeeTierBoundaries:
    """PRD 3.3 step eight - both breakpoints belong to the higher tier."""

    def test_the_first_breakpoint_at_5000_belongs_to_the_middle_tier(
        self, submitted_plan: Scenario
    ):
        """A 4900 subtotal is still 0.060; exactly 5000 has already moved to 0.045.

        Design: Corner/calculations/admin_fee_tier_boundaries_are_inclusive_at_5000_and_20000
        """
        below = submitted_plan.request_detail(
            detail_minutes=19, event_code="HOLIDAY_PEAK", window_start_utc=DETAIL_WINDOW_1200
        )
        approved_below = submitted_plan.approve_detail(below["id"])
        assert approved_below["state"] == "APPROVED"
        assert_cents(approved_below["detail_cost_cents"], 1900, "detail_cost_cents")
        assert_plan_cost(
            _priced(submitted_plan),
            subtotal_cents=4900,
            admin_fee_rate="0.060",
            admin_fee_cents=294,
            total_cost_cents=5194,
            detail_cost_cents=1900,
        )

        cancelled = _cancel_detail(submitted_plan, below["id"])
        assert cancelled["state"] == "CANCELLED"
        assert cancelled["detail_cost_cents"] is None
        assert _priced(submitted_plan)["detail_cost_cents"] == 0

        at_boundary = submitted_plan.request_detail(
            detail_minutes=20, event_code="HOLIDAY_PEAK", window_start_utc=DETAIL_WINDOW_1200
        )
        approved_at = submitted_plan.approve_detail(at_boundary["id"])
        assert_cents(approved_at["detail_cost_cents"], 2000, "detail_cost_cents")
        assert_plan_cost(
            _priced(submitted_plan),
            subtotal_cents=5000,
            admin_fee_rate="0.045",
            admin_fee_cents=225,
            total_cost_cents=5225,
            detail_cost_cents=2000,
        )

    def test_crossing_the_second_breakpoint_lowers_the_total(self, submitted_plan: Scenario):
        """A larger subtotal produces a smaller total across the 20000 boundary.

        Design: Corner/calculations/admin_fee_tier_boundaries_are_inclusive_at_5000_and_20000
        """
        below = submitted_plan.request_detail(
            detail_minutes=169, event_code="SPORTING_EVENT", window_start_utc=DETAIL_WINDOW_1200
        )
        approved_below = submitted_plan.approve_detail(below["id"])
        assert_cents(approved_below["detail_cost_cents"], 16900, "detail_cost_cents")
        below_boundary = _priced(submitted_plan)
        assert_plan_cost(
            below_boundary,
            subtotal_cents=19900,
            admin_fee_rate="0.045",
            admin_fee_cents=896,
            total_cost_cents=20796,
        )

        _cancel_detail(submitted_plan, below["id"])

        at_boundary_detail = submitted_plan.request_detail(
            detail_minutes=170, event_code="SPORTING_EVENT", window_start_utc=DETAIL_WINDOW_1200
        )
        approved_at = submitted_plan.approve_detail(at_boundary_detail["id"])
        assert_cents(approved_at["detail_cost_cents"], 17000, "detail_cost_cents")
        at_boundary = _priced(submitted_plan)
        assert_plan_cost(
            at_boundary,
            subtotal_cents=20000,
            admin_fee_rate="0.030",
            admin_fee_cents=600,
            total_cost_cents=20600,
        )

        assert at_boundary["total_cost_cents"] < below_boundary["total_cost_cents"], (
            "the tier-three rate makes the total fall as the subtotal rises past 20000"
        )
