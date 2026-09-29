"""Dual-variant measurements: utilization bases, rate realization, forecast basis."""

import pytest

from test_helpers import (
    ApiErrorId,
    AssignmentCategory,
    ForecastBasis,
    PeriodStatus,
    StaffingStatus,
    assert_capacity_from_workdays,
    assert_hiring_forecast,
    assert_hours_conserved,
    assert_utilization_period,
    fixtures,
)
from test_helpers.constants import (
    INSTANT_AUG_03,
    INSTANT_AUG_17,
    INSTANT_AUG_31,
)


class TestUtilizationDualBasis:
    def test_holiday_hours_split_the_two_utilization_denominators(self, api):
        """PRD §3.9: "The **available-basis** figure, `utilization_pct_available_basis`,
        is one hundred multiplied by `billable_hours` divided by `net_available_hours`,
        rounded half-up to two decimals, and is absent when `net_available_hours` is
        0.00; it removes holiday from the denominator, which is right for managing a
        period in flight. The **target-basis** figure, `utilization_pct_target_basis`,
        is one hundred multiplied by `billable_hours` divided by `capacity_hours`,
        rounded half-up to two decimals; holiday and paid leave stay in the
        denominator and dilute the number, which is right for reporting against a
        firm-wide target."

        Design: Difficulty/dual_variant_calc/utilization_dual_basis_diverges_on_holiday_period
        """
        world = fixtures.staffed_world(
            api,
            clock=INSTANT_AUG_03,
            allocation_pct=60.00,
            assignment_start="2026-08-03",
            assignment_end="2026-08-29",
        )
        period = fixtures.create_period(
            api,
            world["consultant"]["id"],
            "2026-08-03",
            "2026-08-28",
            holiday_hours=8.00,
        )
        assert_utilization_period(period)

        assert period["period_workdays"] == 20
        assert period["capacity_hours"] == pytest.approx(160.00, abs=0.01)
        assert period["net_available_hours"] == pytest.approx(152.00, abs=0.01)
        assert period["billable_hours"] == pytest.approx(96.00, abs=0.01)
        assert period["investment_hours"] == pytest.approx(0.00, abs=0.01)
        assert period["bench_hours"] == pytest.approx(56.00, abs=0.01)
        assert period["hour_overallocated"] is False
        assert_capacity_from_workdays(period)
        assert_hours_conserved(period)

        # The same 96.00 billable hours read differently under the two denominators.
        assert period["utilization_pct_target_basis"] == pytest.approx(60.00, abs=0.01)
        assert period["utilization_pct_available_basis"] == pytest.approx(63.16, abs=0.01)
        assert period["target_utilization_pct"] == pytest.approx(75.00, abs=0.01)

    def test_closing_switches_the_of_record_basis_without_moving_an_hour(self, api):
        """PRD §3.9: "Both are persisted side by side, and `utilization_pct_of_record`
        is the available-basis figure while the period is `OPEN` and the target-basis
        figure once it is `CLOSED`. The `variance_pp` field is
        `utilization_pct_of_record` less the frozen `target_utilization_pct`, in
        percentage points, rounded half-up to two decimals."

        Design: Difficulty/dual_variant_calc/utilization_dual_basis_diverges_on_holiday_period
        """
        world = fixtures.staffed_world(
            api,
            clock=INSTANT_AUG_03,
            allocation_pct=60.00,
            assignment_start="2026-08-03",
            assignment_end="2026-08-29",
        )
        consultant_id = world["consultant"]["id"]
        opened = fixtures.create_period(
            api, consultant_id, "2026-08-03", "2026-08-28", holiday_hours=8.00
        )

        assert opened["status"] == PeriodStatus.OPEN
        assert opened["utilization_pct_of_record"] == pytest.approx(63.16, abs=0.01)
        assert opened["variance_pp"] == pytest.approx(-11.84, abs=0.01)

        fixtures.set_clock(api, INSTANT_AUG_31)
        closed = fixtures.close_period(api, consultant_id, opened["id"])

        assert closed["status"] == PeriodStatus.CLOSED
        assert closed["utilization_pct_of_record"] == pytest.approx(60.00, abs=0.01)
        assert closed["variance_pp"] == pytest.approx(-15.00, abs=0.01)

        # Not a single hour changed across the close.
        assert closed["billable_hours"] == pytest.approx(96.00, abs=0.01)
        assert closed["bench_hours"] == pytest.approx(56.00, abs=0.01)
        assert closed["capacity_hours"] == pytest.approx(160.00, abs=0.01)
        assert closed["net_available_hours"] == pytest.approx(152.00, abs=0.01)
        assert closed["utilization_pct_available_basis"] == pytest.approx(63.16, abs=0.01)
        assert closed["utilization_pct_target_basis"] == pytest.approx(60.00, abs=0.01)


class TestRealizationBookedVersusEarned:
    @staticmethod
    def _mixed_category_demand(api):
        """One BILLABLE and one INVESTMENT assignment, equal hours, fully delivered."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_17)
        # PRD §3.5 refuses an INVESTMENT confirmation when the demand's practice
        # group posture is FROZEN, and PRD §2.10 freezes any group whose whole
        # headcount is on the bench, so the two consultants are hired elsewhere.
        fixtures.add_bench_group(api, world)
        ada = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=4,
            group_key="bench_group",
            cost_rate_usd_per_hour=120.00,
        )
        grace = fixtures.hire(
            api,
            world,
            full_name="Grace Hopper",
            proficiency_level=3,
            group_key="bench_group",
            cost_rate_usd_per_hour=140.00,
        )
        demand = fixtures.qualified_demand(
            api,
            world,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=240.00,
        )
        billable = fixtures.confirmed_assignment(
            api,
            ada["consultant"]["id"],
            demand["id"],
            allocation_pct=50.00,
            start_date="2026-08-03",
            end_date="2026-08-17",
            category=AssignmentCategory.BILLABLE,
        )
        investment = fixtures.confirmed_assignment(
            api,
            grace["consultant"]["id"],
            demand["id"],
            allocation_pct=50.00,
            start_date="2026-08-03",
            end_date="2026-08-17",
            category=AssignmentCategory.INVESTMENT,
        )
        return world, demand, billable, investment

    def test_investment_hours_halve_earned_while_booked_holds_the_price_ratio(self, api):
        """PRD §3.6: "Because `INVESTMENT` assignments carry a
        `bill_rate_usd_per_hour` of 0.00 while still contributing their hours to the
        denominator, every investment hour drags the earned figure down while leaving
        the booked figure untouched."

        Design: Difficulty/dual_variant_calc/realization_booked_vs_earned_diverges_on_investment_mix
        """
        _, demand, billable, investment = self._mixed_category_demand(api)

        assert billable["bill_rate_usd_per_hour"] == pytest.approx(240.00, abs=0.01)
        assert billable["cost_rate_usd_per_hour"] == pytest.approx(120.00, abs=0.01)
        assert investment["bill_rate_usd_per_hour"] == pytest.approx(0.00, abs=0.01)
        assert investment["cost_rate_usd_per_hour"] == pytest.approx(140.00, abs=0.01)

        after = fixtures.read_demand(api, demand["id"])
        assert after["effective_rate_usd_per_hour"] == pytest.approx(240.00, abs=0.01)
        assert after["booked_realization_pct"] == pytest.approx(96.00, abs=0.01)
        assert after["earned_realization_pct"] == pytest.approx(48.00, abs=0.01)

    def test_blended_cost_and_margin_follow_the_same_delivered_hour_weighting(self, api):
        """PRD §3.6: "The `blended_cost_rate_usd_per_hour` is 0.00 when no committed
        hours exist, and otherwise the sum over those assignments of
        `cost_rate_usd_per_hour` times delivered hours divided by the total delivered
        hours, rounded half-up to two decimals."

        Design: Difficulty/dual_variant_calc/realization_booked_vs_earned_diverges_on_investment_mix
        """
        _, demand, _, _ = self._mixed_category_demand(api)

        after = fixtures.read_demand(api, demand["id"])
        assert after["blended_cost_rate_usd_per_hour"] == pytest.approx(130.00, abs=0.01)
        assert after["blended_margin_pct"] == pytest.approx(45.83, abs=0.01)
        assert after["margin_breach"] is False
        assert after["covered_internal_fte"] == pytest.approx(1.00, abs=0.01)
        assert after["open_fte"] == pytest.approx(0.00, abs=0.01)
        assert after["staffing_status"] == StaffingStatus.COVERED


class TestForecastWeightedVersusCommitted:
    @staticmethod
    def _pipeline_with_a_long_tail(api):
        """Three 33%-probability demands plus one 80% anchor, no supply at all."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        tail = []
        for client in ("Tail One", "Tail Two", "Tail Three"):
            demand = fixtures.qualified_demand(
                api,
                world,
                staffing_mode=None,
                client_name=client,
                required_fte=0.25,
                win_probability_pct=33,
                start_date="2026-09-01",
                end_date="2026-12-15",
                standard_rate_usd_per_hour=250.00,
                requested_rate_usd_per_hour=250.00,
            )
            tail.append(demand)
        anchor = fixtures.qualified_demand(
            api,
            world,
            staffing_mode=None,
            client_name="Anchor Bank",
            required_fte=1.00,
            win_probability_pct=80,
            start_date="2026-09-01",
            end_date="2026-12-15",
            industry_code="BANKING",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        return world, tail, anchor

    def test_probability_floor_drops_the_tail_and_counts_survivors_whole(self, api):
        """PRD §3.9: "Under the `COMMITTED` variant, in-scope demands with a
        `win_probability_pct` below 70 are dropped entirely and contribute 0.00, while
        the survivors contribute their **full** `required_fte` rounded to two decimals
        rather than a probability-weighted share."

        Design: Difficulty/dual_variant_calc/forecast_weighted_vs_committed_diverges_on_probability_floor
        """
        _, tail, anchor = self._pipeline_with_a_long_tail(api)

        assert tail[0]["weighted_fte"] == pytest.approx(0.08, abs=0.01)
        assert anchor["weighted_fte"] == pytest.approx(0.80, abs=0.01)

        weighted = fixtures.create_forecast(
            api,
            skill_code="CLOUD_ARCH",
            geography_code="NA",
            horizon_start_on="2026-08-01",
            horizon_end_on="2026-12-31",
            basis=ForecastBasis.WEIGHTED,
        )
        committed = fixtures.create_forecast(
            api,
            skill_code="CLOUD_ARCH",
            geography_code="NA",
            horizon_start_on="2026-08-01",
            horizon_end_on="2026-12-31",
            basis=ForecastBasis.COMMITTED,
        )
        assert_hiring_forecast(weighted)
        assert_hiring_forecast(committed)

        assert weighted["basis"] == ForecastBasis.WEIGHTED
        assert weighted["weighted_demand_fte"] == pytest.approx(1.04, abs=0.01)
        assert committed["basis"] == ForecastBasis.COMMITTED
        assert committed["weighted_demand_fte"] == pytest.approx(1.00, abs=0.01)

    def test_both_bases_recommend_hires_from_a_zero_supply_gap(self, api):
        """PRD §3.9: "The `recommended_hires` figure is 0 whenever `gap_fte` is 0.00
        or negative, and otherwise `gap_fte` divided by the 0.85 expected yield per
        hire, **rounded up to the next whole number** — half a recruit cannot be
        hired."

        Design: Difficulty/dual_variant_calc/forecast_weighted_vs_committed_diverges_on_probability_floor
        """
        self._pipeline_with_a_long_tail(api)

        weighted = fixtures.create_forecast(
            api,
            skill_code="CLOUD_ARCH",
            geography_code="NA",
            horizon_start_on="2026-08-01",
            horizon_end_on="2026-12-31",
            basis=ForecastBasis.WEIGHTED,
        )
        committed = fixtures.create_forecast(
            api,
            skill_code="CLOUD_ARCH",
            geography_code="NA",
            horizon_start_on="2026-08-01",
            horizon_end_on="2026-12-31",
            basis=ForecastBasis.COMMITTED,
        )

        for forecast in (weighted, committed):
            assert forecast["internal_supply_fte"] == pytest.approx(0.00, abs=0.01)
            assert forecast["external_supply_fte"] == pytest.approx(0.00, abs=0.01)

        assert weighted["gap_fte"] == pytest.approx(1.04, abs=0.01)
        assert committed["gap_fte"] == pytest.approx(1.00, abs=0.01)
        assert weighted["recommended_hires"] == 2
        assert committed["recommended_hires"] == 2

        # generated_at is stamped from the logical clock, not from wall time.
        assert weighted["generated_at"].startswith("2026-08-03T00:00:00")
