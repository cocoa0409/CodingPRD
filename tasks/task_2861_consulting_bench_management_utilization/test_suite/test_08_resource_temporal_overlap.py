"""Two interval conventions on one calendar: half-open assignments, closed placements."""

import pytest

from test_helpers import (
    PRACTICE_PARTNER,
    RESOURCE_MANAGER,
    ApiErrorId,
    AssignmentStatus,
    AvailabilityStatus,
    BenchSpellState,
    PlacementStatus,
    StaffingStatus,
    fixtures,
    validate_error,
    validate_paginated,
)
from test_helpers.constants import INSTANT_AUG_03


class TestAssignmentHalfOpenAdjacency:
    @staticmethod
    def _three_back_to_back_proposals(api):
        """A1 [08-03, 08-17), A2 [08-17, 08-31), A3 [08-16, 08-30), all 100.00%."""
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
            start_date="2026-08-03",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=240.00,
        )
        rows = []
        for start, end in (
            ("2026-08-03", "2026-08-17"),
            ("2026-08-17", "2026-08-31"),
            ("2026-08-16", "2026-08-30"),
        ):
            rows.append(
                fixtures.propose_assignment(
                    api,
                    consultant_id,
                    demand["id"],
                    allocation_pct=100.00,
                    start_date=start,
                    end_date=end,
                )
            )
        return world, staff, demand, rows

    def test_two_intervals_meeting_on_one_day_both_confirm(self, api):
        """PRD §2.5: "An **assignment** interval is **half-open**: `start_date` is
        inclusive and `end_date` is exclusive. An assignment whose `end_date` is the day D
        and another whose `start_date` is that same day D therefore never overlap, and an
        assignment contributes nothing to allocation on its own `end_date`."

        Design: Difficulty/resource_temporal_overlap/consultant_allocation_half_open_adjacency_passes_one_day_overlap_fails
        """
        _, staff, _, rows = self._three_back_to_back_proposals(api)
        consultant_id = staff["consultant"]["id"]

        first = fixtures.confirm(api, rows[0]["id"])
        second = fixtures.confirm(api, rows[1]["id"])

        # 200.00 points across time, with no single date carrying more than 100.00.
        assert first["status"] == AssignmentStatus.CONFIRMED
        assert first["end_date"] == "2026-08-17"
        assert second["status"] == AssignmentStatus.CONFIRMED
        assert second["start_date"] == "2026-08-17"

        consultant = fixtures.read_consultant(api, consultant_id)
        # Only A1's interval contains the 2026-08-03 clock date.
        assert consultant["allocated_pct"] == pytest.approx(100.00, abs=0.005)
        assert consultant["availability_status"] == AvailabilityStatus.ASSIGNED

        spells = fixtures.spells_of(api, consultant_id)
        assert [row["state"] for row in spells] == [BenchSpellState.CLOSED]

    def test_a_single_shared_day_of_overlap_is_refused(self, api):
        """PRD §2.9: "32. **Allocation capacity** — on every date of the assignment's
        half-open interval, the consultant's committed allocation from `CONFIRMED` and
        `ACTIVE` assignments plus this assignment's `allocation_pct` must be at most
        100.00; a total of exactly 100.00 is allowed. Applies to assignment confirmation.
        Failure: `ERR_ALLOCATION_CAPACITY_EXCEEDED` (409)."

        Design: Difficulty/resource_temporal_overlap/consultant_allocation_half_open_adjacency_passes_one_day_overlap_fails
        """
        _, staff, demand, rows = self._three_back_to_back_proposals(api)
        fixtures.confirm(api, rows[0]["id"])
        fixtures.confirm(api, rows[1]["id"])

        # 2026-08-16 alone is enough: it lies inside A1's half-open interval.
        response = api.confirm_assignment(rows[2]["id"], RESOURCE_MANAGER)
        validate_error(response, ApiErrorId.ERR_ALLOCATION_CAPACITY_EXCEEDED, 409)

        refused = fixtures.read_assignment(api, rows[2]["id"])
        assert refused["status"] == AssignmentStatus.PROPOSED
        assert refused["confirmed_on"] is None

        assert fixtures.read_consultant(api, staff["consultant"]["id"])[
            "allocated_pct"
        ] == pytest.approx(100.00, abs=0.005)

        # Coverage is date-agnostic even though allocation is not.
        after = fixtures.read_demand(api, demand["id"])
        assert after["covered_internal_fte"] == pytest.approx(2.00, abs=0.005)
        assert after["open_fte"] == pytest.approx(1.00, abs=0.005)
        assert after["staffing_status"] == StaffingStatus.PARTIALLY_COVERED


class TestPlacementClosedIntervalEndpointDay:
    @staticmethod
    def _one_slot_firm_with_three_placements(api):
        """P1 [08-03, 08-17] APPROVED, P2 [08-17, 08-28] and P3 [08-18, 08-28] waiting."""
        world = fixtures.base_world(
            api, clock=INSTANT_AUG_03, external_sourcing_cap_pct=100.00
        )
        external = fixtures.demand_with_external_branch(
            api,
            world,
            firm_kwargs={
                "name": "NorthStar Partners",
                "geo_code": "NA",
                "max_concurrent_placements": 1,
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
        firm_id = external["firm"]["id"]
        demand_id = external["demand"]["id"]
        first = fixtures.create_placement(
            api, firm_id, demand_id, fte=1.00, start_date="2026-08-03", end_date="2026-08-17"
        )
        # PRD §3.6: approval is what moves the row to APPROVED, so the approved
        # row — not the REQUESTED create response — is the one under test.
        first = fixtures.approve_placement(api, first["id"])
        sharing_a_day = fixtures.create_placement(
            api, firm_id, demand_id, fte=1.00, start_date="2026-08-17", end_date="2026-08-28"
        )
        one_day_later = fixtures.create_placement(
            api, firm_id, demand_id, fte=1.00, start_date="2026-08-18", end_date="2026-08-28"
        )
        return world, external, first, sharing_a_day, one_day_later

    def test_the_shared_endpoint_day_breaks_a_ceiling_of_one(self, api):
        """PRD §2.9: "31. **Firm concurrency ceiling** — on every date of the placement's
        closed interval, the count of the firm's other `APPROVED` or `ACTIVE` placements
        covering that date plus this one must be at most `max_concurrent_placements`.
        Applies to placement approval. Failure: `ERR_FIRM_CONCURRENCY_EXCEEDED` (409)."

        Design: Difficulty/resource_temporal_overlap/firm_placement_closed_interval_endpoint_day_collides
        """
        _, external, first, sharing_a_day, _ = self._one_slot_firm_with_three_placements(
            api
        )
        assert first["status"] == PlacementStatus.APPROVED
        assert first["end_date"] == "2026-08-17"
        assert sharing_a_day["start_date"] == "2026-08-17"

        response = api.approve_placement(sharing_a_day["id"], PRACTICE_PARTNER)
        # 2026-08-17 is P1's last day and P2's first, and one shared day is enough.
        validate_error(response, ApiErrorId.ERR_FIRM_CONCURRENCY_EXCEEDED, 409)

        refused = fixtures.read_placement(api, sharing_a_day["id"])
        assert refused["status"] == PlacementStatus.REQUESTED
        assert refused["terminated_on"] is None

        assert (
            fixtures.read_firm(api, external["firm"]["id"])["active_placements_count"]
            == 1
        )
        still = fixtures.read_demand(api, external["demand"]["id"])
        assert still["covered_external_fte"] == pytest.approx(1.00, abs=0.005)
        assert still["staffing_status"] == StaffingStatus.PARTIALLY_COVERED

    def test_moving_the_start_one_day_later_empties_the_shared_date_set(self, api):
        """PRD §3.6: "Because placement intervals are closed on both ends, a placement
        ending on a day D and one starting on that same day D *do* collide on D — the exact
        opposite of the assignment convention, and a distinction the concurrency count
        depends on."

        Design: Difficulty/resource_temporal_overlap/firm_placement_closed_interval_endpoint_day_collides
        """
        _, external, _, sharing_a_day, one_day_later = (
            self._one_slot_firm_with_three_placements(api)
        )
        validate_error(
            api.approve_placement(sharing_a_day["id"], PRACTICE_PARTNER),
            ApiErrorId.ERR_FIRM_CONCURRENCY_EXCEEDED,
        )

        approved = fixtures.approve_placement(api, one_day_later["id"])
        assert approved["status"] == PlacementStatus.APPROVED
        assert approved["start_date"] == "2026-08-18"
        assert approved["bill_rate_usd_per_hour"] == pytest.approx(240.00, abs=0.01)

        # A lifetime-of-interval counter, not a per-date one.
        assert (
            fixtures.read_firm(api, external["firm"]["id"])["active_placements_count"]
            == 2
        )

        # The sourcing ceiling was exercised at exactly 1.0000 and passed.
        after = fixtures.read_demand(api, external["demand"]["id"])
        assert after["covered_external_fte"] == pytest.approx(2.00, abs=0.005)
        assert after["open_fte"] == pytest.approx(0.00, abs=0.005)
        assert after["staffing_status"] == StaffingStatus.COVERED

        rows, meta = validate_paginated(api.list_placements(RESOURCE_MANAGER))
        assert meta["total_count"] == 3
        assert sorted(row["status"] for row in rows) == [
            PlacementStatus.APPROVED,
            PlacementStatus.APPROVED,
            PlacementStatus.REQUESTED,
        ]


class TestCohortVersusFutureAssignment:
    @staticmethod
    def _escalated_bencher_with_a_september_assignment(api):
        """One CONFIRMED assignment over [2026-09-01, 2026-09-15) and two cohorts:
        one starting on 2026-09-14, one on 2026-09-15."""
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
            start_date="2026-09-01",
            end_date="2026-09-14",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=240.00,
        )
        clashing = fixtures.create_program(
            api,
            world["skill"]["id"],
            target_proficiency_level=5,
            cohort_start_on="2026-09-14",
            cohort_end_on="2026-09-30",
            seat_capacity=2,
        )
        disjoint = fixtures.create_program(
            api,
            world["skill"]["id"],
            target_proficiency_level=5,
            cohort_start_on="2026-09-15",
            cohort_end_on="2026-09-30",
            seat_capacity=2,
        )
        fixtures.advance_clock_and_run(api, "2026-08-17T00:00:00Z")
        assignment = fixtures.confirmed_assignment(
            api,
            consultant_id,
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-09-01",
            end_date="2026-09-15",
        )
        return world, staff, demand, clashing, disjoint, assignment

    def test_the_inclusive_cohort_day_inside_the_interval_clashes(self, api):
        """PRD §2.9: "28. **Cohort clash with committed work** — the cohort's inclusive
        window must not intersect any `CONFIRMED` or `ACTIVE` assignment of the enrolling
        consultant on that assignment's half-open interval. Applies to cohort enrolment.
        Failure: `ERR_COHORT_CONFLICTS_WITH_ASSIGNMENT` (409)."

        Design: Difficulty/resource_temporal_overlap/reskilling_cohort_versus_future_confirmed_assignment_interval
        """
        _, staff, _, clashing, _, assignment = (
            self._escalated_bencher_with_a_september_assignment(api)
        )
        consultant_id = staff["consultant"]["id"]

        # The future assignment commits nothing today, so the spell is still open.
        consultant = fixtures.read_consultant(api, consultant_id)
        assert consultant["allocated_pct"] == pytest.approx(0.00, abs=0.005)
        assert consultant["availability_status"] == AvailabilityStatus.BENCH
        spell = fixtures.open_spell_of(api, consultant_id)
        assert spell["state"] == BenchSpellState.ESCALATED_L1
        assert spell["age_days"] == 14
        assert assignment["status"] == AssignmentStatus.CONFIRMED
        assert assignment["confirmed_on"] == "2026-08-17"
        assert assignment["bill_rate_usd_per_hour"] == pytest.approx(240.00, abs=0.01)

        response = api.enrol_in_program(
            clashing["id"], consultant_id, RESOURCE_MANAGER
        )
        # 2026-09-14 is the cohort's first day and lies inside [2026-09-01, 2026-09-15).
        validate_error(response, ApiErrorId.ERR_COHORT_CONFLICTS_WITH_ASSIGNMENT, 409)

        assert fixtures.read_program(api, clashing["id"])["seats_taken"] == 0
        assert (
            fixtures.read_spell(api, spell["id"])["state"]
            == BenchSpellState.ESCALATED_L1
        )

    def test_a_cohort_opening_on_the_exclusive_end_date_is_disjoint(self, api):
        """PRD §2.5: "An **assignment** interval is **half-open**: `start_date` is
        inclusive and `end_date` is exclusive. An assignment whose `end_date` is the day D
        and another whose `start_date` is that same day D therefore never overlap, and an
        assignment contributes nothing to allocation on its own `end_date`."

        Design: Difficulty/resource_temporal_overlap/reskilling_cohort_versus_future_confirmed_assignment_interval
        """
        _, staff, demand, clashing, disjoint, assignment = (
            self._escalated_bencher_with_a_september_assignment(api)
        )
        consultant_id = staff["consultant"]["id"]
        validate_error(
            api.enrol_in_program(clashing["id"], consultant_id, RESOURCE_MANAGER),
            ApiErrorId.ERR_COHORT_CONFLICTS_WITH_ASSIGNMENT,
        )

        enrolled = fixtures.enrol(api, disjoint["id"], consultant_id)

        assert enrolled["state"] == BenchSpellState.RESKILLING
        assert enrolled["reskilling_program_id"] == disjoint["id"]
        assert fixtures.read_program(api, disjoint["id"])["seats_taken"] == 1

        assert (
            fixtures.read_consultant(api, consultant_id)["availability_status"]
            == AvailabilityStatus.RESKILLING
        )
        # The future assignment is not disturbed by the enrolment.
        untouched = fixtures.read_assignment(api, assignment["id"])
        assert untouched["status"] == AssignmentStatus.CONFIRMED
        after = fixtures.read_demand(api, demand["id"])
        assert after["covered_internal_fte"] == pytest.approx(1.00, abs=0.005)
        assert after["staffing_status"] == StaffingStatus.COVERED
