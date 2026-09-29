"""Derivations: the selector's ranking, the ratios, the realizations, the ladders."""

import pytest

from test_helpers import (
    RESOURCE_MANAGER,
    ApiErrorId,
    AssignmentCategory,
    AssignmentStatus,
    AvailabilityStatus,
    BenchSpellState,
    ForecastBasis,
    Posture,
    StaffingStatus,
    assert_bench_ratio,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    INSTANT_AUG_03,
    INSTANT_AUG_10,
    INSTANT_AUG_17,
    INSTANT_SEP_01,
)


class TestAutoStaffRanking:
    @staticmethod
    def _three_candidates_two_eligible(api):
        """c1 at 260.00 and c2 at 300.00 both score 0.4000; c3 is under the floor."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        first = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=4,
            cost_rate_usd_per_hour=260.00,
        )
        second = fixtures.hire(
            api,
            world,
            full_name="Alan Turing",
            proficiency_level=4,
            cost_rate_usd_per_hour=300.00,
        )
        third = fixtures.hire(
            api,
            world,
            full_name="Grace Hopper",
            proficiency_level=2,
            cost_rate_usd_per_hour=100.00,
        )
        demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=1.00,
            min_proficiency_level=3,
            onsite_nights_per_week=2,
            industry_code="RETAIL",
            start_date="2026-08-03",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        return world, first, second, third, demand

    def test_the_cost_tie_break_decides_between_two_identical_scores(self, api):
        """PRD §3.5: "Candidates are then ranked in this exact order: highest
        `match_score` first; among ties, lowest `cost_rate_usd_per_hour` first — a
        tie-break that is genuinely reachable because the cost component clamps at
        0.0000, so two expensive consultants can score identically and still differ in
        cost; among still-tied candidates, the longest-benched first, meaning the greatest
        `age_days` on their open bench spell; and finally, as the sole last resort, the
        earliest `created_at`."

        Design: Corner/calculations/auto_staff_ranks_by_score_then_cost_over_the_eligible_pool
        """
        _, first, second, third, demand = self._three_candidates_two_eligible(api)

        winner = validate_success(
            api.auto_staff_demand(demand["id"], RESOURCE_MANAGER), 201
        )

        # c3 has the best cost of all three and still loses on proficiency.
        assert winner["consultant_id"] == first["consultant"]["id"]
        assert winner["consultant_id"] != second["consultant"]["id"]
        assert winner["consultant_id"] != third["consultant"]["id"]
        # 0.35*0.8000 + 0.15*0.0000 + 0.15*0.0000 + 0.20*0.6000 + 0.15*0.0000
        assert winner["match_score"] == pytest.approx(0.4000, abs=0.00005)

        rows, meta = validate_paginated(
            api.list_assignments(
                RESOURCE_MANAGER, {"demand_opportunity_id": demand["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == winner["id"]

    def test_the_selectors_row_takes_the_declared_fixed_values(self, api):
        """PRD §3.5: "The winner receives one new assignment with `status` at `PROPOSED`,
        `allocation_pct` of 100.00, `category` of `BILLABLE`, `start_date` equal to the
        demand's `start_date`, `end_date` equal to the day *after* the demand's `end_date`
        — because the demand's window is inclusive on the right while the assignment's is
        exclusive — and the winner's `match_score` stored on the row."

        Design: Corner/calculations/auto_staff_ranks_by_score_then_cost_over_the_eligible_pool
        """
        _, first, _, _, demand = self._three_candidates_two_eligible(api)

        winner = validate_success(
            api.auto_staff_demand(demand["id"], RESOURCE_MANAGER), 201
        )
        assert winner["status"] == AssignmentStatus.PROPOSED
        assert winner["allocation_pct"] == pytest.approx(100.00, abs=0.005)
        assert winner["category"] == AssignmentCategory.BILLABLE
        assert winner["start_date"] == "2026-08-03"
        # 2026-08-28 is the demand's inclusive last day.
        assert winner["end_date"] == "2026-08-29"
        assert winner["cost_rate_usd_per_hour"] == pytest.approx(260.00, abs=0.01)
        assert winner["bill_rate_usd_per_hour"] == pytest.approx(250.00, abs=0.01)

        # A PROPOSED winner moves no coverage at all.
        after = fixtures.read_demand(api, demand["id"])
        assert after["covered_internal_fte"] == pytest.approx(0.00, abs=0.005)
        assert after["open_fte"] == pytest.approx(1.00, abs=0.005)
        assert after["staffing_status"] == StaffingStatus.INTERNAL_STAFFING
        assert (
            fixtures.read_consultant(api, first["consultant"]["id"])[
                "availability_status"
            ]
            == AvailabilityStatus.BENCH
        )


class TestAutoStaffEmptyPool:
    def test_an_empty_pool_refuses_and_mutates_absolutely_nothing(self, api):
        """PRD §3.5: "If the candidate set is empty the request is rejected with
        `ERR_NO_ELIGIBLE_CONSULTANT` and **nothing at all is mutated**: no assignment row,
        no `version` bump on the demand or on any consultant, and no change to coverage or
        `staffing_status`."

        Design: Corner/calculations/auto_staff_with_an_empty_candidate_pool_returns_4XX_and_mutates_nothing
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=4)
        consultant_id = staff["consultant"]["id"]
        assert staff["consultant"]["travel_max_nights_per_week"] == 3
        assert staff["consultant"]["version"] == 1

        demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=1.00,
            min_proficiency_level=3,
            onsite_nights_per_week=4,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        # create, qualify, staffing-mode: three writes, three versions.
        assert demand["version"] == 3

        validate_error(
            api.auto_staff_demand(demand["id"], RESOURCE_MANAGER),
            ApiErrorId.ERR_NO_ELIGIBLE_CONSULTANT,
            409,
        )

        _, meta = validate_paginated(
            api.list_assignments(
                RESOURCE_MANAGER, {"demand_opportunity_id": demand["id"]}
            )
        )
        assert meta["total_count"] == 0

        after_demand = fixtures.read_demand(api, demand["id"])
        assert after_demand["version"] == 3
        assert after_demand["staffing_status"] == StaffingStatus.INTERNAL_STAFFING

        after_consultant = fixtures.read_consultant(api, consultant_id)
        assert after_consultant["version"] == 1
        assert after_consultant["availability_status"] == AvailabilityStatus.BENCH


class TestPostureThresholdAndRollup:
    @staticmethod
    def _two_staffed_heads_in_a_child_group(api):
        """Parent 'Cloud Global' over child 'Cloud NA', both heads staffed."""
        world = fixtures.parent_child_world(api, clock=INSTANT_AUG_03)
        demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=2.00,
            start_date="2026-08-03",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        assignments = []
        consultants = []
        for name in ("Ada Byron", "Alan Turing"):
            staff = fixtures.hire(
                api,
                world,
                full_name=name,
                proficiency_level=4,
                cost_rate_usd_per_hour=120.00,
            )
            consultants.append(staff["consultant"])
            assignments.append(
                fixtures.confirmed_assignment(
                    api,
                    staff["consultant"]["id"],
                    demand["id"],
                    allocation_pct=100.00,
                    start_date="2026-08-03",
                    end_date="2026-08-29",
                )
            )
        return world, consultants, demand, assignments

    def test_exactly_one_half_freezes_because_the_comparison_is_inclusive(self, api):
        """PRD §2.10: "Posture then follows three arms, evaluated in this order. The group
        is `FROZEN` when its `rollup_bench_ratio` is at least 0.5000 **or** when its
        `escalated_l2_count` is at least 3."

        Design: Corner/calculations/posture_thresholds_are_inclusive_and_roll_up_to_the_parent_group
        """
        world, consultants, demand, assignments = self._two_staffed_heads_in_a_child_group(
            api
        )
        child_id = world["child"]["id"]

        before = fixtures.read_group(api, child_id)
        assert before["total_headcount"] == 2
        assert before["bench_headcount"] == 0
        assert_bench_ratio(before, 0.0000, 0.0000, Posture.OPEN)

        released = fixtures.release(api, assignments[0]["id"], reason="client paused")
        assert released["status"] == AssignmentStatus.RELEASED
        assert released["released_on"] == "2026-08-03"

        after = fixtures.read_group(api, child_id)
        assert after["bench_headcount"] == 1
        # 1 over 2 is exactly the 0.5000 frozen breakpoint, and >= fires.
        assert_bench_ratio(after, 0.5000, 0.5000, Posture.FROZEN)

        benched = fixtures.read_consultant(api, consultants[0]["id"])
        assert benched["allocated_pct"] == pytest.approx(0.00, abs=0.005)
        assert benched["availability_status"] == AvailabilityStatus.BENCH
        spells, meta = validate_paginated(
            api.list_bench_spells(
                RESOURCE_MANAGER, {"consultant_id": consultants[0]["id"]}
            )
        )
        assert meta["total_count"] == 2
        reopened = fixtures.open_spell_of(api, consultants[0]["id"])
        assert reopened["state"] == BenchSpellState.MONITORING
        assert reopened["started_on"] == "2026-08-03"

        covered = fixtures.read_demand(api, demand["id"])
        assert covered["covered_internal_fte"] == pytest.approx(1.00, abs=0.005)
        assert covered["open_fte"] == pytest.approx(1.00, abs=0.005)
        assert covered["staffing_status"] == StaffingStatus.PARTIALLY_COVERED

    def test_the_childless_parent_freezes_on_its_subtree_not_its_own_roster(self, api):
        """PRD §2.10: "The `rollup_bench_ratio` is the sum of `bench_headcount` over the
        group and all of its transitive descendants divided by the sum of
        `total_headcount` over the same set, rounded half-up to four decimals, and is
        exactly 0.0000 when that denominator is zero."

        Design: Corner/calculations/posture_thresholds_are_inclusive_and_roll_up_to_the_parent_group
        """
        world, _, _, assignments = self._two_staffed_heads_in_a_child_group(api)
        parent_id = world["parent"]["id"]

        before = fixtures.read_group(api, parent_id)
        assert before["total_headcount"] == 0
        assert_bench_ratio(before, 0.0000, 0.0000, Posture.OPEN)

        fixtures.release(api, assignments[0]["id"], reason="client paused")

        after = fixtures.read_group(api, parent_id)
        # The parent owns nobody, so its own ratio cannot move at all.
        assert after["total_headcount"] == 0
        assert after["bench_headcount"] == 0
        assert_bench_ratio(after, 0.0000, 0.5000, Posture.FROZEN)


class TestMatchScoreRoundingBeforeTheTieBreak:
    @staticmethod
    def _two_candidates_two_cents_apart(api):
        """c1 at 130.00 and c2 at 130.02 both round to a stored 0.6820."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        skill_id = world["skill"]["id"]
        candidates = []
        for name, cost in (("Ada Byron", 130.00), ("Alan Turing", 130.02)):
            candidates.append(
                fixtures.hire(
                    api,
                    world,
                    full_name=name,
                    proficiency_level=4,
                    cost_rate_usd_per_hour=cost,
                    development_goal_skill_id=skill_id,
                    industry_experience=factories.industry_experience("RETAIL", 2),
                )
            )
        demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=1.00,
            min_proficiency_level=3,
            onsite_nights_per_week=3,
            industry_code="RETAIL",
            start_date="2026-08-03",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        probe = fixtures.propose_assignment(
            api,
            candidates[1]["consultant"]["id"],
            demand["id"],
            allocation_pct=50.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        return world, candidates, demand, probe

    def test_both_stored_scores_land_on_the_same_four_decimals(self, api):
        """PRD §3.5: "All comparisons use the stored four-decimal score and the stored
        two-decimal cost rate exactly as stored, with no tolerance of any kind."

        Design: Corner/calculations/match_score_rounds_to_four_decimals_before_the_tie_break_runs
        """
        _, candidates, demand, probe = self._two_candidates_two_cents_apart(api)

        # 0.2800 + 0.15*0.6667 + 0.1500 + 0.20*0.4000 + 0.15*0.4799 == 0.681990
        assert probe["match_score"] == pytest.approx(0.6820, abs=0.00005)

        winner = validate_success(
            api.auto_staff_demand(demand["id"], RESOURCE_MANAGER), 201
        )
        # 0.2800 + 0.15*0.6667 + 0.1500 + 0.20*0.4000 + 0.15*0.4800 == 0.682005
        assert winner["match_score"] == pytest.approx(0.6820, abs=0.00005)
        assert winner["match_score"] == probe["match_score"]

        # R1 cannot separate the pair, so R2 hands it to the cheaper row.
        assert winner["consultant_id"] == candidates[0]["consultant"]["id"]
        assert winner["cost_rate_usd_per_hour"] == pytest.approx(130.00, abs=0.01)

    def test_a_proposed_row_reserves_no_headroom_for_the_selector(self, api):
        """PRD §3.5: "Creating the proposal increments the consultant's `version` by one
        but changes no coverage and no allocation whatsoever — a `PROPOSED` assignment
        reserves nothing, which is precisely why this creation needs the stale-version
        guard instead of a state precondition."

        Design: Corner/calculations/match_score_rounds_to_four_decimals_before_the_tie_break_runs
        """
        _, candidates, demand, probe = self._two_candidates_two_cents_apart(api)
        assert probe["allocation_pct"] == pytest.approx(50.00, abs=0.005)

        winner = validate_success(
            api.auto_staff_demand(demand["id"], RESOURCE_MANAGER), 201
        )
        # The 50.00% proposal on c2 never entered filter five's headroom sum.
        assert winner["allocation_pct"] == pytest.approx(100.00, abs=0.005)

        for candidate in candidates:
            row = fixtures.read_consultant(api, candidate["consultant"]["id"])
            assert row["allocated_pct"] == pytest.approx(0.00, abs=0.005)
            assert row["availability_status"] == AvailabilityStatus.BENCH


class TestCoverageInputSet:
    def test_one_row_moves_coverage_only_while_it_is_confirmed(self, api):
        """PRD §3.4: "Assignments that are merely `PROPOSED` and placements that are merely
        `REQUESTED` contribute nothing to any of the three — which is exactly why proposing
        never moves `staffing_status`, and why releasing a commitment restores the previous
        value precisely."

        Design: Corner/calculations/coverage_counts_only_committed_rows_across_propose_confirm_cancel
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=4,
            cost_rate_usd_per_hour=120.00,
        )
        demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=2.00,
            start_date="2026-08-03",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        # PRD §3.5: cancelling a CONFIRMED row requires the clock date to be
        # strictly earlier than the assignment's start_date, so the interval
        # opens after the 2026-08-03 clock this world is set to.
        assignment = fixtures.propose_assignment(
            api,
            staff["consultant"]["id"],
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-08-17",
            end_date="2026-08-29",
        )

        proposed = fixtures.read_demand(api, demand["id"])
        assert proposed["covered_internal_fte"] == pytest.approx(0.00, abs=0.005)
        assert proposed["open_fte"] == pytest.approx(2.00, abs=0.005)
        assert proposed["staffing_status"] == StaffingStatus.INTERNAL_STAFFING

        fixtures.confirm(api, assignment["id"])
        confirmed = fixtures.read_demand(api, demand["id"])
        assert confirmed["covered_internal_fte"] == pytest.approx(1.00, abs=0.005)
        assert confirmed["open_fte"] == pytest.approx(1.00, abs=0.005)
        assert confirmed["staffing_status"] == StaffingStatus.PARTIALLY_COVERED

        cancelled = fixtures.cancel(api, assignment["id"], reason="client paused")
        assert cancelled["status"] == AssignmentStatus.CANCELLED

        after = fixtures.read_demand(api, demand["id"])
        # Exactly the pre-confirm values: a CANCELLED row is excluded just as a
        # PROPOSED one is.
        assert after["covered_internal_fte"] == pytest.approx(0.00, abs=0.005)
        assert after["open_fte"] == pytest.approx(2.00, abs=0.005)
        assert after["staffing_status"] == StaffingStatus.INTERNAL_STAFFING


class TestEarnedRealizationNeedsDelivery:
    @staticmethod
    def _future_confirmed_assignment(api):
        """A CONFIRMED September assignment read from an August clock."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=4,
            cost_rate_usd_per_hour=120.00,
        )
        demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=1.00,
            start_date="2026-09-01",
            end_date="2026-09-14",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=240.00,
        )
        assignment = fixtures.confirmed_assignment(
            api,
            staff["consultant"]["id"],
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-09-01",
            end_date="2026-09-15",
        )
        return world, staff, demand, assignment

    def test_zero_delivered_hours_leave_earned_and_margin_absent(self, api):
        """PRD §3.7: "When the total is zero, `earned_realization_pct` is absent."

        Design: Corner/calculations/earned_realization_is_null_until_a_workday_has_been_delivered
        """
        _, _, demand, _ = self._future_confirmed_assignment(api)

        before = fixtures.read_demand(api, demand["id"])
        # The booked figure is a pure price ratio and is never absent.
        assert before["booked_realization_pct"] == pytest.approx(96.00, abs=0.01)
        assert before["earned_realization_pct"] is None
        assert before["blended_cost_rate_usd_per_hour"] == pytest.approx(0.00, abs=0.01)
        assert before["blended_margin_pct"] is None
        # An absent margin does not trip the floor gate.
        assert before["margin_breach"] is False

    def test_one_delivery_day_fills_all_three_without_any_write(self, api):
        """PRD §3.7: "The `blended_margin_pct` is absent whenever
        `blended_cost_rate_usd_per_hour` is 0.00 — nothing is staffed, so there is no
        margin to report — and is otherwise one hundred multiplied by
        `effective_rate_usd_per_hour` less `blended_cost_rate_usd_per_hour`, divided by
        that effective rate, rounded half-up to two decimals."

        Design: Corner/calculations/earned_realization_is_null_until_a_workday_has_been_delivered
        """
        _, _, demand, assignment = self._future_confirmed_assignment(api)

        # Moving the clock re-derives without any write to the assignment.
        fixtures.set_clock(api, INSTANT_SEP_01)

        after = fixtures.read_demand(api, demand["id"])
        assert after["earned_realization_pct"] == pytest.approx(96.00, abs=0.01)
        assert after["blended_cost_rate_usd_per_hour"] == pytest.approx(120.00, abs=0.01)
        assert after["blended_margin_pct"] == pytest.approx(50.00, abs=0.01)
        assert after["margin_breach"] is False

        fixtures.bench_run(api)
        activated = fixtures.read_assignment(api, assignment["id"])
        assert activated["status"] == AssignmentStatus.ACTIVE

        # CONFIRMED, ACTIVE and RELEASED are one input set for realization.
        unchanged = fixtures.read_demand(api, demand["id"])
        assert unchanged["earned_realization_pct"] == pytest.approx(96.00, abs=0.01)
        assert unchanged["blended_cost_rate_usd_per_hour"] == pytest.approx(
            120.00, abs=0.01
        )
        assert unchanged["blended_margin_pct"] == pytest.approx(50.00, abs=0.01)


class TestForecastScope:
    @staticmethod
    def _four_demands_and_one_underqualified_bencher(api):
        """Only d1 is QUALIFIED, in-horizon and therefore in scope."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        group_id = world["group"]["id"]
        skill_id = world["skill"]["id"]

        in_scope = fixtures.create_demand(
            api,
            group_id,
            skill_id,
            client_name="Acme Retail",
            required_fte=1.00,
            win_probability_pct=60,
            start_date="2026-08-03",
            end_date="2026-08-28",
        )
        fixtures.qualify(api, in_scope["id"])

        unqualified = fixtures.create_demand(
            api,
            group_id,
            skill_id,
            client_name="Globex Bank",
            required_fte=2.00,
            win_probability_pct=90,
            start_date="2026-08-03",
            end_date="2026-08-28",
        )

        out_of_horizon = fixtures.create_demand(
            api,
            group_id,
            skill_id,
            client_name="Initech",
            required_fte=3.00,
            win_probability_pct=100,
            start_date="2026-10-01",
            end_date="2026-10-31",
        )
        fixtures.qualify(api, out_of_horizon["id"])

        lost = fixtures.create_demand(
            api,
            group_id,
            skill_id,
            client_name="Umbrella Health",
            required_fte=4.00,
            win_probability_pct=100,
            start_date="2026-08-03",
            end_date="2026-08-28",
        )
        fixtures.qualify(api, lost["id"])
        fixtures.close_demand(api, lost["id"], "LOST", note="lost on price")

        staff = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=2)
        return world, in_scope, unqualified, out_of_horizon, lost, staff

    def test_only_the_qualified_in_horizon_demand_reaches_the_forecast(self, api):
        """PRD §3.9: "The forecast's scope is every demand whose `pipeline_status` is
        `QUALIFIED`, whose required skill's `code` equals the forecast's `skill_code`,
        whose practice group's `geography_code` equals the forecast's `geography_code`,
        whose `start_date` is on or before `horizon_end_on` and whose `end_date` is on or
        after `horizon_start_on`."

        Design: Corner/calculations/forecast_scope_drops_unqualified_closed_and_out_of_horizon_demand
        """
        _, _, unqualified, _, _, _ = self._four_demands_and_one_underqualified_bencher(
            api
        )

        forecast = fixtures.create_forecast(
            api,
            skill_code="CLOUD_ARCH",
            geography_code="NA",
            horizon_start_on="2026-08-03",
            horizon_end_on="2026-08-28",
        )
        assert forecast["basis"] == ForecastBasis.WEIGHTED
        assert forecast["generated_at"].startswith("2026-08-03")
        # 1.00 FTE at 60 percent is the only contribution.
        assert forecast["weighted_demand_fte"] == pytest.approx(0.60, abs=0.005)

        # The QUALIFYING row still carries its own weight; it simply is not summed.
        assert fixtures.read_demand(api, unqualified["id"])[
            "weighted_fte"
        ] == pytest.approx(1.80, abs=0.005)

    def test_a_proficiency_two_bencher_is_not_supply_and_the_gap_ceils_to_one(self, api):
        """PRD §3.9: "The `recommended_hires` figure is 0 whenever `gap_fte` is 0.00 or
        negative, and otherwise `gap_fte` divided by the 0.85 expected yield per hire,
        **rounded up to the next whole number** — half a recruit cannot be hired."

        Design: Corner/calculations/forecast_scope_drops_unqualified_closed_and_out_of_horizon_demand
        """
        _, _, _, _, _, staff = self._four_demands_and_one_underqualified_bencher(api)
        assert staff["assertion"]["proficiency_level"] == 2
        assert (
            staff["consultant"]["availability_status"] == AvailabilityStatus.BENCH
        )

        forecast = fixtures.create_forecast(
            api,
            skill_code="CLOUD_ARCH",
            geography_code="NA",
            horizon_start_on="2026-08-03",
            horizon_end_on="2026-08-28",
        )
        # Proficiency 2 is below the supply floor of 3.
        assert forecast["internal_supply_fte"] == pytest.approx(0.00, abs=0.005)
        assert forecast["external_supply_fte"] == pytest.approx(0.00, abs=0.005)
        assert forecast["gap_fte"] == pytest.approx(0.60, abs=0.005)
        # 0.60 / 0.85 is 0.7059, and the ceiling of that is 1.
        assert forecast["recommended_hires"] == 1


class TestLevelTargetsPerKeyFallback:
    @staticmethod
    def _analyst_override_group_with_two_hires(api):
        """A group overriding the ANALYST key only, holding one ANALYST and one
        CONSULTANT hired on the same day and never staffed."""
        fixtures.set_clock(api, INSTANT_AUG_03)
        group = fixtures.create_group(
            api,
            name="Cloud NA",
            geography_code="NA",
            level_targets={
                "ANALYST": {
                    "target_utilization_pct": 60.00,
                    "bench_escalation_l1_days": 7,
                    "bench_escalation_l2_days": 10,
                    "max_investment_pct": 30.00,
                }
            },
        )
        analyst = fixtures.create_consultant(
            api,
            group["id"],
            full_name="Ada Byron",
            email=factories.unique_email("ada"),
            level="ANALYST",
            cost_rate_usd_per_hour=90.00,
            standard_bill_rate_usd_per_hour=200.00,
        )
        consultant = fixtures.create_consultant(
            api,
            group["id"],
            full_name="Alan Turing",
            email=factories.unique_email("alan"),
            level="CONSULTANT",
            cost_rate_usd_per_hour=120.00,
            standard_bill_rate_usd_per_hour=300.00,
        )
        analyst_period = fixtures.create_period(
            api, analyst["id"], "2026-08-03", "2026-08-28"
        )
        consultant_period = fixtures.create_period(
            api, consultant["id"], "2026-08-03", "2026-08-28"
        )
        return group, analyst, consultant, analyst_period, consultant_period

    def test_the_overridden_level_climbs_while_the_defaulted_level_waits(self, api):
        """PRD §2.10: "Resolution is **per key, not per object**: for any given consultant
        the system looks up the entry under that consultant's `level`, and if — and only if
        — that specific level key is absent from the group's object it falls back to the
        firm-wide default for that level."

        Design: Corner/calculations/bench_and_utilization_targets_fall_back_per_level_key
        """
        group, analyst, consultant, _, _ = self._analyst_override_group_with_two_hires(
            api
        )
        analyst_spell = fixtures.open_spell_of(api, analyst["id"])
        consultant_spell = fixtures.open_spell_of(api, consultant["id"])

        fixtures.advance_clock_and_run(api, INSTANT_AUG_10)
        assert fixtures.read_spell(api, analyst_spell["id"])["age_days"] == 7
        assert (
            fixtures.read_spell(api, analyst_spell["id"])["state"]
            == BenchSpellState.ESCALATED_L1
        )
        # The CONSULTANT default L1 is 14 days, so nothing moves here.
        assert (
            fixtures.read_spell(api, consultant_spell["id"])["state"]
            == BenchSpellState.MONITORING
        )

        fixtures.advance_clock_and_run(api, "2026-08-13T00:00:00Z")
        at_l2 = fixtures.read_spell(api, analyst_spell["id"])
        assert at_l2["age_days"] == 10
        assert at_l2["state"] == BenchSpellState.ESCALATED_L2
        assert at_l2["escalation_count"] == 2
        assert (
            fixtures.read_spell(api, consultant_spell["id"])["state"]
            == BenchSpellState.MONITORING
        )

        fixtures.advance_clock_and_run(api, INSTANT_AUG_17)
        late = fixtures.read_spell(api, consultant_spell["id"])
        assert late["age_days"] == 14
        assert late["state"] == BenchSpellState.ESCALATED_L1
        assert late["escalation_count"] == 1
        # The top rung is not an input to the ladder any more.
        assert (
            fixtures.read_spell(api, analyst_spell["id"])["state"]
            == BenchSpellState.ESCALATED_L2
        )

        after = fixtures.read_group(api, group["id"])
        assert after["escalated_l2_count"] == 1
        assert_bench_ratio(after, 1.0000, 1.0000, Posture.FROZEN)

    def test_the_same_fallback_freezes_two_different_utilization_targets(self, api):
        """PRD §3.9: "On creation the row is `OPEN`, and `target_utilization_pct` is
        resolved once from the consultant's group `level_targets` for the consultant's
        `level` and **frozen** on the row, so a later change to the group's targets never
        moves it retroactively."

        Design: Corner/calculations/bench_and_utilization_targets_fall_back_per_level_key
        """
        _, _, _, analyst_period, consultant_period = (
            self._analyst_override_group_with_two_hires(api)
        )

        for period in (analyst_period, consultant_period):
            assert period["period_workdays"] == 20
            assert period["capacity_hours"] == pytest.approx(160.00, abs=0.01)
            assert period["billable_hours"] == pytest.approx(0.00, abs=0.01)
            assert period["utilization_pct_of_record"] == pytest.approx(0.00, abs=0.01)

        assert analyst_period["target_utilization_pct"] == pytest.approx(60.00, abs=0.01)
        assert analyst_period["variance_pp"] == pytest.approx(-60.00, abs=0.01)
        # No CONSULTANT key was supplied, so the firm-wide 75.00 applies.
        assert consultant_period["target_utilization_pct"] == pytest.approx(
            75.00, abs=0.01
        )
        assert consultant_period["variance_pp"] == pytest.approx(-75.00, abs=0.01)


class TestAvailabilityFlipsAtExactlyFifty:
    def test_forty_stays_on_the_bench_and_the_tenth_point_closes_the_spell(self, api):
        """PRD §3.5: "It then recomputes the consultant's `allocated_pct`, and when that
        value reaches 50.00 or more it sets `availability_status` to `ASSIGNED` and
        **closes the consultant's open bench spell**: any spell not already `CLOSED` or
        `SEPARATED` moves to `CLOSED` with `ended_on` stamped from the clock date, its
        `age_days` frozen at that point, and — when the spell had been in `RESKILLING` or
        `INTERNAL_PROJECT` — its `investment_ended_on` stamped too."

        Design: Corner/calculations/availability_flips_to_assigned_at_exactly_fifty_percent_allocation
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=4,
            cost_rate_usd_per_hour=120.00,
        )
        consultant_id = staff["consultant"]["id"]
        spell = fixtures.open_spell_of(api, consultant_id)
        demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=1.00,
            start_date="2026-08-03",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )

        fixtures.confirmed_assignment(
            api,
            consultant_id,
            demand["id"],
            allocation_pct=40.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        under = fixtures.read_consultant(api, consultant_id)
        assert under["allocated_pct"] == pytest.approx(40.00, abs=0.005)
        assert under["availability_status"] == AvailabilityStatus.BENCH
        assert (
            fixtures.read_spell(api, spell["id"])["state"]
            == BenchSpellState.MONITORING
        )
        assert fixtures.read_group(api, world["group"]["id"])["bench_headcount"] == 1

        fixtures.confirmed_assignment(
            api,
            consultant_id,
            demand["id"],
            allocation_pct=10.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        on_the_line = fixtures.read_consultant(api, consultant_id)
        # The comparison is >= on exactly 50.00.
        assert on_the_line["allocated_pct"] == pytest.approx(50.00, abs=0.005)
        assert on_the_line["availability_status"] == AvailabilityStatus.ASSIGNED

        closed = fixtures.read_spell(api, spell["id"])
        assert closed["state"] == BenchSpellState.CLOSED
        assert closed["ended_on"] == "2026-08-03"

        group = fixtures.read_group(api, world["group"]["id"])
        assert group["bench_headcount"] == 0
        assert_bench_ratio(group, 0.0000, 0.0000, Posture.OPEN)

        after = fixtures.read_demand(api, demand["id"])
        assert after["covered_internal_fte"] == pytest.approx(0.50, abs=0.005)
        assert after["open_fte"] == pytest.approx(0.50, abs=0.005)
        assert after["staffing_status"] == StaffingStatus.PARTIALLY_COVERED
        assert after["blended_cost_rate_usd_per_hour"] == pytest.approx(120.00, abs=0.01)
        assert after["blended_margin_pct"] == pytest.approx(52.00, abs=0.01)
