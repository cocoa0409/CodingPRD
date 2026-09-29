"""Exact boundaries: the threshold day, the hundredth percent, the shared day."""

import pytest

from test_helpers import (
    FINANCE_CONTROLLER,
    RESOURCE_MANAGER,
    ApiErrorId,
    AssignmentStatus,
    AvailabilityStatus,
    BenchSpellState,
    PeriodStatus,
    Posture,
    StaffingStatus,
    assert_bench_ratio,
    assert_capacity_from_workdays,
    assert_hours_conserved,
    assert_utilization_period,
    fixtures,
    validate_error,
    validate_paginated,
)
from test_helpers.constants import INSTANT_AUG_03, INSTANT_AUG_31


class TestBenchLadderThresholdDay:
    @staticmethod
    def _never_staffed_consultant(api):
        """A CONSULTANT-level hire on 2026-08-03, so L1 is 14 days and L2 is 30."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        consultant = fixtures.create_consultant(
            api,
            world["group"]["id"],
            full_name="Ada Byron",
            level="CONSULTANT",
            cost_rate_usd_per_hour=120.00,
            standard_bill_rate_usd_per_hour=300.00,
        )
        spell = fixtures.open_spell_of(api, consultant["id"])
        assert spell["started_on"] == "2026-08-03"
        assert spell["age_reset_on"] is None
        assert spell["state"] == BenchSpellState.MONITORING
        return world, consultant, spell

    def test_day_thirteen_holds_and_day_fourteen_escalates(self, api):
        """PRD §3.8: "Both thresholds are inclusive, so the threshold day itself
        escalates."

        Design: Difficulty/boundary_precision_check/bench_l1_escalation_at_exact_threshold_day
        """
        _, consultant, spell = self._never_staffed_consultant(api)

        fixtures.advance_clock_and_run(api, "2026-08-16T00:00:00Z")

        one_day_short = fixtures.read_spell(api, spell["id"])
        assert one_day_short["age_days"] == 13
        assert one_day_short["state"] == BenchSpellState.MONITORING
        assert one_day_short["escalation_count"] == 0

        fixtures.advance_clock_and_run(api, "2026-08-17T00:00:00Z")

        on_the_day = fixtures.read_spell(api, spell["id"])
        # 14 is exactly the CONSULTANT bench_escalation_l1_days, and >= fires.
        assert on_the_day["age_days"] == 14
        assert on_the_day["state"] == BenchSpellState.ESCALATED_L1
        assert on_the_day["escalation_count"] == 1

        rows = fixtures.spells_of(api, consultant["id"])
        assert len(rows) == 1, "the ladder moves the existing row, it does not insert"

    def test_one_checkpoint_climbs_one_rung_so_the_count_arm_stays_quiet(self, api):
        """PRD §3.8: "Crucially, **a single checkpoint advances a spell by at most one
        rung**: a spell sitting in `MONITORING` with an age already past the level-two
        threshold still lands only in `ESCALATED_L1`, so reaching `ESCALATED_L2` always
        takes two separate checkpoints no matter how far the clock has been moved."

        Design: Difficulty/boundary_precision_check/bench_l1_escalation_at_exact_threshold_day
        """
        world, _, spell = self._never_staffed_consultant(api)

        # 2026-09-05 is 33 days on, comfortably past the 30-day L2 threshold.
        fixtures.advance_clock_and_run(api, "2026-09-05T00:00:00Z")

        after_one = fixtures.read_spell(api, spell["id"])
        assert after_one["age_days"] == 33
        assert after_one["state"] == BenchSpellState.ESCALATED_L1
        assert after_one["state"] != BenchSpellState.ESCALATED_L2
        assert after_one["escalation_count"] == 1

        group = fixtures.read_group(api, world["group"]["id"])
        assert group["total_headcount"] == 1
        assert group["bench_headcount"] == 1
        assert group["escalated_l2_count"] == 0
        # FROZEN here is the ratio arm on a single benched head, not the L2 arm.
        assert_bench_ratio(group, 1.0000, 1.0000, Posture.FROZEN)

        fixtures.bench_run(api)

        after_two = fixtures.read_spell(api, spell["id"])
        assert after_two["state"] == BenchSpellState.ESCALATED_L2
        assert after_two["escalation_count"] == 2
        assert fixtures.read_group(api, world["group"]["id"])["escalated_l2_count"] == 1


class TestAllocationSumExactlyOneHundred:
    @staticmethod
    def _sixty_confirmed_then_forty_and_one_proposed(api):
        """One consultant on a 3.00 FTE demand: 60.00 live, 40.00 and 1.00 waiting."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=4,
            cost_rate_usd_per_hour=120.00,
        )
        consultant_id = staff["consultant"]["id"]
        demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=3.00,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=240.00,
        )
        first = fixtures.confirmed_assignment(
            api,
            consultant_id,
            demand["id"],
            allocation_pct=60.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        second = fixtures.propose_assignment(
            api,
            consultant_id,
            demand["id"],
            allocation_pct=40.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        third = fixtures.propose_assignment(
            api,
            consultant_id,
            demand["id"],
            allocation_pct=1.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        return world, staff, demand, first, second, third

    def test_a_total_of_exactly_one_hundred_is_allowed(self, api):
        """PRD §2.9: "32. **Allocation capacity** — on every date of the assignment's
        half-open interval, the consultant's committed allocation from `CONFIRMED` and
        `ACTIVE` assignments plus this assignment's `allocation_pct` must be at most
        100.00; a total of exactly 100.00 is allowed. Applies to assignment
        confirmation. Failure: `ERR_ALLOCATION_CAPACITY_EXCEEDED` (409)."

        Design: Difficulty/boundary_precision_check/allocation_sum_exactly_100_confirms_then_next_percent_rejected
        """
        _, staff, demand, _, second, _ = self._sixty_confirmed_then_forty_and_one_proposed(
            api
        )
        consultant_id = staff["consultant"]["id"]

        before = fixtures.read_consultant(api, consultant_id)
        assert before["allocated_pct"] == pytest.approx(60.00, abs=0.005)

        topped_up = fixtures.confirm(api, second["id"])

        assert topped_up["status"] == AssignmentStatus.CONFIRMED
        assert topped_up["confirmed_on"] == "2026-08-03"

        after = fixtures.read_consultant(api, consultant_id)
        # 60.00 + 40.00 lands on the ceiling itself, with no epsilon slack needed.
        assert after["allocated_pct"] == pytest.approx(100.00, abs=0.005)
        assert after["availability_status"] == AvailabilityStatus.ASSIGNED

        covered = fixtures.read_demand(api, demand["id"])
        assert covered["covered_internal_fte"] == pytest.approx(1.00, abs=0.005)
        assert covered["open_fte"] == pytest.approx(2.00, abs=0.005)
        assert covered["staffing_status"] == StaffingStatus.PARTIALLY_COVERED

    def test_the_very_next_percentage_point_is_refused_and_changes_nothing(self, api):
        """PRD §2.9: "When a single request violates several rules, exactly one error is
        returned and **no mutation of any kind occurs**."

        Design: Difficulty/boundary_precision_check/allocation_sum_exactly_100_confirms_then_next_percent_rejected
        """
        _, staff, demand, _, second, third = (
            self._sixty_confirmed_then_forty_and_one_proposed(api)
        )
        consultant_id = staff["consultant"]["id"]
        fixtures.confirm(api, second["id"])

        response = api.confirm_assignment(third["id"], RESOURCE_MANAGER)

        validate_error(response, ApiErrorId.ERR_ALLOCATION_CAPACITY_EXCEEDED, 409)

        refused = fixtures.read_assignment(api, third["id"])
        assert refused["status"] == AssignmentStatus.PROPOSED
        assert refused["confirmed_on"] is None

        unchanged = fixtures.read_consultant(api, consultant_id)
        assert unchanged["allocated_pct"] == pytest.approx(100.00, abs=0.005)
        assert unchanged["availability_status"] == AvailabilityStatus.ASSIGNED

        still = fixtures.read_demand(api, demand["id"])
        assert still["covered_internal_fte"] == pytest.approx(1.00, abs=0.005)
        assert still["open_fte"] == pytest.approx(2.00, abs=0.005)
        assert still["staffing_status"] == StaffingStatus.PARTIALLY_COVERED


class TestPeriodAdjacencyOnTheSharedDay:
    @staticmethod
    def _one_closed_period_behind_the_clock(api):
        """P1 covering the inclusive range 2026-08-03..2026-08-14, clock at 08-31."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_31)
        consultant = fixtures.create_consultant(
            api,
            world["group"]["id"],
            full_name="Ada Byron",
            level="CONSULTANT",
            cost_rate_usd_per_hour=120.00,
            standard_bill_rate_usd_per_hour=300.00,
        )
        first = fixtures.create_period(
            api, consultant["id"], "2026-08-03", "2026-08-14"
        )
        return world, consultant, first

    def test_the_shared_boundary_day_is_an_overlap_but_the_next_day_is_not(self, api):
        """PRD §3.9: "Periods of a single consultant may not overlap on their
        **inclusive** ranges, and because both ends are inclusive a period starting on
        the very day a previous one ends *is* an overlap — that shared boundary day is
        `ERR_PERIOD_OVERLAP`."

        Design: Difficulty/boundary_precision_check/utilization_period_adjacent_start_day_is_an_overlap
        """
        _, consultant, first = self._one_closed_period_behind_the_clock(api)
        assert first["period_end_on"] == "2026-08-14"

        collision = api.create_utilization_period(
            consultant["id"],
            {"period_start_on": "2026-08-14", "period_end_on": "2026-08-28"},
            FINANCE_CONTROLLER,
        )
        validate_error(collision, ApiErrorId.ERR_PERIOD_OVERLAP, 409)

        # One day later shares nothing, and the same request now succeeds.
        second = fixtures.create_period(
            api, consultant["id"], "2026-08-15", "2026-08-28"
        )
        assert second["status"] == PeriodStatus.OPEN
        assert second["period_start_on"] == "2026-08-15"

        rows, meta = validate_paginated(
            api.list_utilization_periods(consultant["id"], FINANCE_CONTROLLER)
        )
        assert meta["total_count"] == 2, "the rejected request created nothing"
        assert {row["id"] for row in rows} == {first["id"], second["id"]}

    def test_the_accepted_period_counts_only_its_own_ten_workdays(self, api):
        """PRD §3.9: "The period's arithmetic starts from `period_workdays`, the count
        of Monday-to-Friday dates in the inclusive range, from which `capacity_hours` is
        that count multiplied by eight, and `net_available_hours` is `capacity_hours`
        less `holiday_hours`."

        Design: Difficulty/boundary_precision_check/utilization_period_adjacent_start_day_is_an_overlap
        """
        _, consultant, first = self._one_closed_period_behind_the_clock(api)

        second = fixtures.create_period(
            api, consultant["id"], "2026-08-15", "2026-08-28"
        )
        assert_utilization_period(second)

        assert first["period_workdays"] == 10
        assert first["capacity_hours"] == pytest.approx(80.00, abs=0.01)

        # 2026-08-15 and 2026-08-16 are a weekend and contribute nothing.
        assert second["period_workdays"] == 10
        assert second["capacity_hours"] == pytest.approx(80.00, abs=0.01)
        assert second["net_available_hours"] == pytest.approx(80.00, abs=0.01)
        assert_capacity_from_workdays(second)

        assert second["billable_hours"] == pytest.approx(0.00, abs=0.01)
        assert second["investment_hours"] == pytest.approx(0.00, abs=0.01)
        assert second["bench_hours"] == pytest.approx(80.00, abs=0.01)
        assert second["hour_overallocated"] is False
        assert_hours_conserved(second)

        assert second["utilization_pct_available_basis"] == pytest.approx(0.00, abs=0.01)
        assert second["target_utilization_pct"] == pytest.approx(75.00, abs=0.01)
        assert second["variance_pp"] == pytest.approx(-75.00, abs=0.01)
