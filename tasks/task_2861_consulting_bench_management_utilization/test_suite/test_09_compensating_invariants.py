"""Compensating actions: hours change bucket and FTE changes column, nothing vanishes."""

import pytest

from test_helpers import (
    RESOURCE_MANAGER,
    AssignmentStatus,
    AvailabilityStatus,
    BenchSpellState,
    PipelineStatus,
    PlacementStatus,
    StaffingStatus,
    assert_fte_coverage_conserved,
    assert_hours_conserved,
    fixtures,
    validate_paginated,
)
from test_helpers.constants import INSTANT_AUG_03


class TestReleaseMovesHoursBetweenBuckets:
    @staticmethod
    def _fully_billable_period(api):
        """A 20-workday period every hour of which is billable at the start."""
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
            required_fte=1.00,
            start_date="2026-08-03",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=240.00,
        )
        assignment = fixtures.confirmed_assignment(
            api,
            consultant_id,
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        period = fixtures.create_period(
            api, consultant_id, "2026-08-03", "2026-08-28", holiday_hours=0.00
        )
        return world, staff, demand, assignment, period

    def test_the_four_bucket_identity_holds_on_both_sides_of_the_release(self, api):
        """PRD §3.9: "Those definitions exist to make one identity hold: whenever
        `hour_overallocated` is false, `billable_hours` plus `investment_hours` plus
        `bench_hours` plus `holiday_hours` equals `capacity_hours` exactly."

        Design: Difficulty/compensating_invariant/utilization_hour_classification_conserved_across_release
        """
        _, staff, _, assignment, period = self._fully_billable_period(api)
        consultant_id = staff["consultant"]["id"]

        assert period["capacity_hours"] == pytest.approx(160.00, abs=0.01)
        assert period["net_available_hours"] == pytest.approx(160.00, abs=0.01)
        assert period["billable_hours"] == pytest.approx(160.00, abs=0.01)
        assert period["investment_hours"] == pytest.approx(0.00, abs=0.01)
        assert period["bench_hours"] == pytest.approx(0.00, abs=0.01)
        assert period["hour_overallocated"] is False
        assert_hours_conserved(period)
        assert period["utilization_pct_target_basis"] == pytest.approx(100.00, abs=0.01)
        assert period["utilization_pct_available_basis"] == pytest.approx(100.00, abs=0.01)

        fixtures.set_clock(api, "2026-08-10T00:00:00Z")
        released = fixtures.release(api, assignment["id"], reason="client paused")
        assert released["status"] == AssignmentStatus.RELEASED
        assert released["released_on"] == "2026-08-10"

        after = fixtures.read_period(api, consultant_id, period["id"])
        assert after["capacity_hours"] == pytest.approx(160.00, abs=0.01)
        assert after["net_available_hours"] == pytest.approx(160.00, abs=0.01)
        assert after["hour_overallocated"] is False
        assert_hours_conserved(after)
        assert after["utilization_pct_target_basis"] == pytest.approx(25.00, abs=0.01)
        assert after["utilization_pct_available_basis"] == pytest.approx(25.00, abs=0.01)
        assert after["variance_pp"] == pytest.approx(-50.00, abs=0.01)

    def test_whatever_billable_loses_bench_gains_to_the_penny(self, api):
        """PRD §3.9: "Releasing an assignment never destroys hours — whatever
        `billable_hours` loses, `bench_hours` gains, to the penny."

        Design: Difficulty/compensating_invariant/utilization_hour_classification_conserved_across_release
        """
        _, staff, demand, assignment, period = self._fully_billable_period(api)
        consultant_id = staff["consultant"]["id"]

        fixtures.set_clock(api, "2026-08-10T00:00:00Z")
        fixtures.release(api, assignment["id"], reason="client paused")

        after = fixtures.read_period(api, consultant_id, period["id"])
        # Only the 5 workdays 2026-08-03..2026-08-07 fall inside the exclusive
        # effective end of 2026-08-10.
        assert after["billable_hours"] == pytest.approx(40.00, abs=0.01)
        assert after["investment_hours"] == pytest.approx(0.00, abs=0.01)
        assert after["bench_hours"] == pytest.approx(120.00, abs=0.01)
        lost = period["billable_hours"] - after["billable_hours"]
        gained = after["bench_hours"] - period["bench_hours"]
        assert lost == pytest.approx(gained, abs=0.005)

        # The compensation also ran on the other side of the release cascade.
        consultant = fixtures.read_consultant(api, consultant_id)
        assert consultant["allocated_pct"] == pytest.approx(0.00, abs=0.005)
        assert consultant["availability_status"] == AvailabilityStatus.BENCH
        reopened = fixtures.open_spell_of(api, consultant_id)
        assert reopened["state"] == BenchSpellState.MONITORING
        assert reopened["started_on"] == "2026-08-10"

        after_demand = fixtures.read_demand(api, demand["id"])
        assert after_demand["covered_internal_fte"] == pytest.approx(0.00, abs=0.005)
        assert after_demand["open_fte"] == pytest.approx(1.00, abs=0.005)


class TestTerminationRestoresOpenFte:
    @staticmethod
    def _half_covered_external_demand(api):
        """A 2.00 FTE external demand carrying one APPROVED 1.00 FTE placement."""
        world = fixtures.base_world(
            api, clock=INSTANT_AUG_03, external_sourcing_cap_pct=100.00
        )
        external = fixtures.demand_with_external_branch(
            api,
            world,
            firm_kwargs={
                "name": "NorthStar Partners",
                "geo_code": "NA",
                "max_concurrent_placements": 2,
                "pass_through_rate_usd_per_hour": 150.00,
            },
            demand_kwargs={
                "client_name": "Globex Bank",
                "required_fte": 2.00,
                "win_probability_pct": 70,
                "industry_code": "BANKING",
                "start_date": "2026-08-03",
                "end_date": "2026-08-28",
                "standard_rate_usd_per_hour": 250.00,
                "requested_rate_usd_per_hour": 240.00,
            },
        )
        placement = fixtures.approved_placement(
            api,
            external["firm"]["id"],
            external["demand"]["id"],
            fte=1.00,
            start_date="2026-08-03",
            end_date="2026-08-28",
        )
        return world, external, placement

    def test_the_freed_fte_lands_entirely_in_open_fte(self, api):
        """PRD §3.6: "**Termination** by a `PracticePartner`, optionally carrying a
        `reason`, is permitted from `APPROVED` and from `ACTIVE`, with identical effects
        from both: `status` becomes `TERMINATED`, `terminated_on` is stamped from the
        logical clock date, the firm's `active_placements_count` is recomputed so the
        concurrency slot for that interval is freed, and the demand's
        `covered_external_fte`, `open_fte` and `staffing_status` are restored exactly to
        their pre-approval values — the compensating action that keeps the FTE-coverage
        identity exact."

        Design: Difficulty/compensating_invariant/opportunity_fte_coverage_conserved_across_placement_terminate
        """
        _, external, placement = self._half_covered_external_demand(api)
        demand_id = external["demand"]["id"]

        before = fixtures.read_demand(api, demand_id)
        assert before["covered_internal_fte"] == pytest.approx(0.00, abs=0.005)
        assert before["covered_external_fte"] == pytest.approx(1.00, abs=0.005)
        assert before["open_fte"] == pytest.approx(1.00, abs=0.005)
        assert before["staffing_status"] == StaffingStatus.PARTIALLY_COVERED
        assert_fte_coverage_conserved(before)
        assert (
            fixtures.read_firm(api, external["firm"]["id"])["active_placements_count"]
            == 1
        )

        fixtures.set_clock(api, "2026-08-10T00:00:00Z")
        terminated = fixtures.terminate_placement(
            api, placement["id"], reason="partner withdrew the consultant"
        )
        assert terminated["status"] == PlacementStatus.TERMINATED
        assert terminated["terminated_on"] == "2026-08-10"

        after = fixtures.read_demand(api, demand_id)
        assert after["covered_external_fte"] == pytest.approx(0.00, abs=0.005)
        assert after["open_fte"] == pytest.approx(2.00, abs=0.005)
        assert_fte_coverage_conserved(after)
        assert (
            fixtures.read_firm(api, external["firm"]["id"])["active_placements_count"]
            == 0
        )

    def test_the_rollback_falls_back_to_the_branch_it_was_committed_to(self, api):
        """PRD §3.4: "When the *last* covering commitment goes away, the demand falls all
        the way back to its branch value: to `INTERNAL_STAFFING` on an internal demand and
        to `EXTERNAL_SOURCING` on an external one."

        Design: Difficulty/compensating_invariant/opportunity_fte_coverage_conserved_across_placement_terminate
        """
        _, external, placement = self._half_covered_external_demand(api)
        demand_id = external["demand"]["id"]

        fixtures.set_clock(api, "2026-08-10T00:00:00Z")
        fixtures.terminate_placement(api, placement["id"], reason="partner withdrew")

        after = fixtures.read_demand(api, demand_id)
        assert after["staffing_status"] == StaffingStatus.EXTERNAL_SOURCING
        assert after["staffing_status"] != StaffingStatus.INTERNAL_STAFFING
        # The rollback touches coverage, not the branch or the pipeline.
        assert after["staffing_mode"] == "EXTERNAL"
        assert after["pipeline_status"] == PipelineStatus.QUALIFIED

        rows, meta = validate_paginated(
            api.list_placements(
                RESOURCE_MANAGER, {"demand_opportunity_id": demand_id}
            )
        )
        # Nothing was deleted: the TERMINATED row is still readable.
        assert meta["total_count"] == 1
        assert rows[0]["status"] == PlacementStatus.TERMINATED

        # The concurrency slot is free again for the identical interval.
        replacement = fixtures.approved_placement(
            api,
            external["firm"]["id"],
            demand_id,
            fte=1.00,
            start_date="2026-08-03",
            end_date="2026-08-28",
        )
        assert replacement["status"] == PlacementStatus.APPROVED
        restored = fixtures.read_demand(api, demand_id)
        assert restored["covered_external_fte"] == pytest.approx(1.00, abs=0.005)
        assert restored["staffing_status"] == StaffingStatus.PARTIALLY_COVERED
