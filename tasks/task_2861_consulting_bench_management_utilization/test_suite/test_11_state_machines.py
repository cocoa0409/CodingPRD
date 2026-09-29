"""State machines: declared initial states, one-way edges and terminal lockdown."""

import pytest

from test_helpers import (
    PRACTICE_PARTNER_2,
    PRACTICE_PARTNER_2_USER_ID,
    RESOURCE_MANAGER,
    RESOURCE_MANAGER_USER_ID,
    SALES_LEAD,
    ApiErrorId,
    AssertionStatus,
    AssignmentStatus,
    AvailabilityStatus,
    BenchSpellState,
    ClosedOutcome,
    PeriodStatus,
    PipelineStatus,
    PlacementStatus,
    Posture,
    ProgramStatus,
    SeparationDecision,
    StaffingStatus,
    assert_bench_ratio,
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
    INSTANT_SEP_02,
    INSTANT_SEP_30,
)


class TestDeclaredInitialStates:
    def test_the_hire_and_the_demand_and_the_proposal_all_start_where_declared(
        self, api
    ):
        """PRD §3.2: "The new consultant's `availability_status` is `BENCH` and their
        `allocated_pct` is 0.00, their `separated_on` is absent, and — critically — the
        hire **creates the consultant's first bench spell** in state `MONITORING`, with
        `started_on` stamped from the logical clock date, `age_reset_on` absent, and
        `escalation_count` at 0."

        Design: Corner/state_machines/every_state_machine_starts_in_its_declared_initial_state
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=4)
        consultant_id = staff["consultant"]["id"]

        assert staff["consultant"]["availability_status"] == AvailabilityStatus.BENCH
        assert staff["consultant"]["allocated_pct"] == pytest.approx(0.00, abs=0.005)
        assert staff["consultant"]["separated_on"] is None

        # The spell is a cascade of the hire and is discoverable only by listing.
        spells, meta = validate_paginated(
            api.list_bench_spells(RESOURCE_MANAGER, {"consultant_id": consultant_id})
        )
        assert meta["total_count"] == 1
        spell = spells[0]
        assert spell["state"] == BenchSpellState.MONITORING
        assert spell["started_on"] == "2026-08-03"
        assert spell["age_reset_on"] is None
        assert spell["escalation_count"] == 0
        assert spell["age_days"] == 0
        assert spell["ended_on"] is None

        demand = fixtures.create_demand(
            api,
            world["group"]["id"],
            world["skill"]["id"],
            required_fte=1.00,
        )
        assert demand["pipeline_status"] == PipelineStatus.QUALIFYING
        assert demand["staffing_status"] == StaffingStatus.UNSTAFFED
        assert demand["staffing_mode"] is None
        assert demand["closed_outcome"] is None

        fixtures.qualify(api, demand["id"])
        fixtures.set_mode(api, demand["id"], "INTERNAL")
        proposal = fixtures.propose_assignment(
            api,
            consultant_id,
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        assert proposal["status"] == AssignmentStatus.PROPOSED
        assert proposal["confirmed_on"] is None
        assert proposal["activated_on"] is None
        assert proposal["released_on"] is None

    def test_the_cohort_and_the_period_and_the_assertion_all_start_where_declared(
        self, api
    ):
        """PRD §3.8: "The cohort is created `PLANNED` with `seats_taken` at 0, where
        `seats_taken` is always the count of spells currently enrolled in it."

        Design: Corner/state_machines/every_state_machine_starts_in_its_declared_initial_state
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=4)
        consultant_id = staff["consultant"]["id"]

        program = fixtures.create_program(
            api,
            world["skill"]["id"],
            target_proficiency_level=5,
            cohort_start_on="2026-09-01",
            cohort_end_on="2026-09-30",
            seat_capacity=2,
        )
        assert program["status"] == ProgramStatus.PLANNED
        assert program["seats_taken"] == 0

        period = fixtures.create_period(
            api, consultant_id, "2026-08-03", "2026-08-28"
        )
        assert period["status"] == PeriodStatus.OPEN

        assert staff["assertion"]["assertion_status"] == AssertionStatus.ACTIVE
        assert staff["assertion"]["certification_code"] is None


class TestQualifyIsNotIdempotent:
    def test_the_second_qualify_is_refused_and_the_version_does_not_move(self, api):
        """PRD §3.3: "Attempting to qualify a demand that is not `QUALIFYING` is
        `ERR_OPPORTUNITY_STATE_INVALID`."

        Design: Corner/state_machines/second_qualify_on_a_qualified_demand_is_rejected
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        demand = fixtures.create_demand(
            api,
            world["group"]["id"],
            world["skill"]["id"],
            required_fte=1.00,
            win_probability_pct=60,
        )
        assert demand["version"] == 1
        assert demand["pipeline_status"] == PipelineStatus.QUALIFYING

        qualified = fixtures.qualify(api, demand["id"])
        assert qualified["pipeline_status"] == PipelineStatus.QUALIFIED
        assert qualified["version"] == 2
        # 1.00 FTE at 60 percent win probability weights to 0.60.
        assert qualified["weighted_fte"] == pytest.approx(0.60, abs=0.005)

        replay = api.qualify_demand(demand["id"], SALES_LEAD)
        validate_error(replay, ApiErrorId.ERR_OPPORTUNITY_STATE_INVALID, 409)

        after = fixtures.read_demand(api, demand["id"])
        assert after["version"] == 2
        assert after["pipeline_status"] == PipelineStatus.QUALIFIED
        assert after["weighted_fte"] == pytest.approx(0.60, abs=0.005)


class TestClosureActivatesTheInternalBranch:
    @staticmethod
    def _covered_internal_demand(api):
        """A 1.00 FTE internal demand fully covered by one CONFIRMED assignment."""
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
            start_date="2026-08-03",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=240.00,
        )
        assignment = fixtures.confirmed_assignment(
            api,
            staff["consultant"]["id"],
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        return world, staff, demand, assignment

    def test_the_won_closure_promotes_every_confirmed_row_to_active(self, api):
        """PRD §3.3: "It sets `pipeline_status` to `CLOSED_WON` and `closed_outcome` to
        `WON`, and then it activates whichever branch the demand chose: on the internal
        branch every assignment on the demand whose `status` is `CONFIRMED` becomes
        `ACTIVE` with `activated_on` stamped from the logical clock date, and on the
        external branch every placement on the demand whose `status` is `APPROVED`
        becomes `ACTIVE`."

        Design: Corner/state_machines/closed_won_activates_confirmed_assignments_on_the_internal_branch
        """
        _, _, demand, assignment = self._covered_internal_demand(api)

        before = fixtures.read_demand(api, demand["id"])
        assert before["staffing_status"] == StaffingStatus.COVERED
        assert before["open_fte"] == pytest.approx(0.00, abs=0.005)
        assert before["margin_breach"] is False
        assert assignment["status"] == AssignmentStatus.CONFIRMED
        assert assignment["confirmed_on"] == "2026-08-03"
        assert assignment["activated_on"] is None

        won = fixtures.close_demand(api, demand["id"], "WON", note="signed")
        assert won["pipeline_status"] == PipelineStatus.CLOSED_WON
        assert won["closed_outcome"] == ClosedOutcome.WON
        # The coverage dimension is untouched by the pipeline write.
        assert won["staffing_status"] == StaffingStatus.COVERED

        activated = fixtures.read_assignment(api, assignment["id"])
        assert activated["status"] == AssignmentStatus.ACTIVE
        assert activated["activated_on"] == "2026-08-03"
        assert activated["activated_on"] == activated["confirmed_on"]
        assert activated["released_on"] is None

    def test_the_activation_re_reports_realization_cost_and_margin(self, api):
        """PRD §3.5: "Activation recomputes the demand's `earned_realization_pct`, since
        `ACTIVE` assignments enter the delivered-hours denominator, and recomputes every
        intersecting `OPEN` utilization period."

        Design: Corner/state_machines/closed_won_activates_confirmed_assignments_on_the_internal_branch
        """
        _, _, demand, _ = self._covered_internal_demand(api)
        fixtures.close_demand(api, demand["id"], "WON")

        after = fixtures.read_demand(api, demand["id"])
        # One delivered workday, all of it billable at 240.00 against a 250.00 list.
        assert after["booked_realization_pct"] == pytest.approx(96.00, abs=0.01)
        assert after["earned_realization_pct"] == pytest.approx(96.00, abs=0.01)
        assert after["blended_cost_rate_usd_per_hour"] == pytest.approx(120.00, abs=0.01)
        assert after["blended_margin_pct"] == pytest.approx(50.00, abs=0.01)
        assert after["margin_breach"] is False


class TestClosureUnwindsTheInternalBranch:
    def test_the_lost_closure_cancels_the_proposed_and_the_confirmed_row_alike(
        self, api
    ):
        """PRD §3.3: "From `QUALIFIED` the same two status writes happen and then the
        branch is unwound: on the internal branch every assignment on the demand whose
        `status` is `PROPOSED` or `CONFIRMED` becomes `CANCELLED`, and every assignment
        whose `status` is `ACTIVE` becomes `RELEASED` with `released_on` stamped from the
        logical clock date; on the external branch every placement whose `status` is
        `REQUESTED`, `APPROVED` or `ACTIVE` becomes `TERMINATED` with `terminated_on`
        stamped."

        Design: Corner/state_machines/closed_lost_cancels_both_proposed_and_confirmed_assignments
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
        demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=2.00,
            start_date="2026-09-01",
            end_date="2026-09-14",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=240.00,
        )
        confirmed = fixtures.confirmed_assignment(
            api,
            consultant_id,
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-09-01",
            end_date="2026-09-15",
        )
        proposed = fixtures.propose_assignment(
            api,
            consultant_id,
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-09-01",
            end_date="2026-09-15",
        )

        before = fixtures.read_demand(api, demand["id"])
        # A PROPOSED row contributes nothing, so only the confirmed 1.00 counts.
        assert before["covered_internal_fte"] == pytest.approx(1.00, abs=0.005)
        assert before["open_fte"] == pytest.approx(1.00, abs=0.005)
        assert before["staffing_status"] == StaffingStatus.PARTIALLY_COVERED

        lost = fixtures.close_demand(api, demand["id"], "LOST", note="client shelved it")
        assert lost["pipeline_status"] == PipelineStatus.CLOSED_LOST
        assert lost["closed_outcome"] == ClosedOutcome.LOST

        for row_id in (confirmed["id"], proposed["id"]):
            cancelled = fixtures.read_assignment(api, row_id)
            assert cancelled["status"] == AssignmentStatus.CANCELLED
            # Cancellation is not a release, so no release date is stamped.
            assert cancelled["released_on"] is None

        after = fixtures.read_demand(api, demand["id"])
        assert after["covered_internal_fte"] == pytest.approx(0.00, abs=0.005)
        assert after["open_fte"] == pytest.approx(2.00, abs=0.005)
        assert after["staffing_status"] == StaffingStatus.INTERNAL_STAFFING

        consultant = fixtures.read_consultant(api, consultant_id)
        assert consultant["allocated_pct"] == pytest.approx(0.00, abs=0.005)
        assert consultant["availability_status"] == AvailabilityStatus.BENCH

        spells, meta = validate_paginated(
            api.list_bench_spells(RESOURCE_MANAGER, {"consultant_id": consultant_id})
        )
        # A September commitment never reserved August capacity, so the hire's
        # own spell never closed and no second spell was opened.
        assert meta["total_count"] == 1
        assert spells[0]["state"] == BenchSpellState.MONITORING
        assert spells[0]["started_on"] == "2026-08-03"
        assert spells[0]["ended_on"] is None


class TestClosureUnwindsTheExternalBranch:
    def test_the_lost_closure_terminates_the_requested_row_too(self, api):
        """PRD §3.3: "Every newly released or cancelled assignment runs the full release
        cascade documented in §3.5 — allocation, then availability, then bench spell,
        then the group's bench ratio, then the ancestor chain of postures — and every
        terminated placement frees the firm's concurrency slot for its interval."

        Design: Corner/state_machines/closed_lost_terminates_every_placement_on_the_external_branch
        """
        world = fixtures.base_world(
            api, clock=INSTANT_AUG_03, external_sourcing_cap_pct=100.00
        )
        assert world["group"]["posture"] == Posture.OPEN
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
        firm_id = external["firm"]["id"]
        demand_id = external["demand"]["id"]
        approved = fixtures.approved_placement(
            api, firm_id, demand_id, fte=1.00, start_date="2026-08-03", end_date="2026-08-28"
        )
        requested = fixtures.create_placement(
            api, firm_id, demand_id, fte=1.00, start_date="2026-08-03", end_date="2026-08-28"
        )
        assert approved["status"] == PlacementStatus.APPROVED
        assert requested["status"] == PlacementStatus.REQUESTED

        before = fixtures.read_demand(api, demand_id)
        assert before["covered_external_fte"] == pytest.approx(1.00, abs=0.005)
        assert before["open_fte"] == pytest.approx(1.00, abs=0.005)
        assert before["staffing_status"] == StaffingStatus.PARTIALLY_COVERED
        assert fixtures.read_firm(api, firm_id)["active_placements_count"] == 1

        fixtures.set_clock(api, INSTANT_AUG_10)
        lost = fixtures.close_demand(api, demand_id, "LOST", note="lost on price")
        assert lost["pipeline_status"] == PipelineStatus.CLOSED_LOST
        assert lost["closed_outcome"] == ClosedOutcome.LOST

        for row_id in (approved["id"], requested["id"]):
            terminated = fixtures.read_placement(api, row_id)
            # The REQUESTED row takes the edge too, not just the approved one.
            assert terminated["status"] == PlacementStatus.TERMINATED
            assert terminated["terminated_on"] == "2026-08-10"

        after = fixtures.read_demand(api, demand_id)
        assert after["covered_internal_fte"] == pytest.approx(0.00, abs=0.005)
        assert after["covered_external_fte"] == pytest.approx(0.00, abs=0.005)
        assert after["open_fte"] == pytest.approx(2.00, abs=0.005)
        assert after["staffing_status"] == StaffingStatus.EXTERNAL_SOURCING
        assert fixtures.read_firm(api, firm_id)["active_placements_count"] == 0


class TestSeparationTerminal:
    @staticmethod
    def _spell_at_the_second_rung(api):
        """One never-staffed CONSULTANT whose spell has climbed to ESCALATED_L2."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=4)
        consultant_id = staff["consultant"]["id"]
        spell = fixtures.bench_spell_at_l2(
            api,
            world,
            consultant_id,
            l1_instant=INSTANT_AUG_17,
            l2_instant=INSTANT_SEP_02,
        )
        return world, consultant_id, spell

    def test_the_approved_decision_empties_all_three_group_counters(self, api):
        """PRD §3.8: "On approval the spell's `state` becomes `SEPARATED`, which is
        terminal, `separation_decision` is set to `APPROVED`,
        `separation_decided_by_user_id` is stamped, and `ended_on` is stamped from the
        clock date, freezing `age_days`."

        Design: Corner/state_machines/separation_flow_reaches_the_separated_terminal_state
        """
        world, consultant_id, spell = self._spell_at_the_second_rung(api)
        group_id = world["group"]["id"]

        assert spell["state"] == BenchSpellState.ESCALATED_L2
        assert spell["escalation_count"] == 2
        assert spell["age_days"] == 30
        before = fixtures.read_group(api, group_id)
        assert before["escalated_l2_count"] == 1
        assert_bench_ratio(before, 1.0000, 1.0000, Posture.FROZEN)

        proposed = validate_success(
            api.propose_separation(
                spell["id"], RESOURCE_MANAGER, rationale="no pipeline fit in 30 days"
            ),
            200,
        )
        assert proposed["state"] == BenchSpellState.SEPARATION_PROPOSED
        assert proposed["separation_proposed_by_user_id"] == RESOURCE_MANAGER_USER_ID
        # The counter spans ESCALATED_L2 and SEPARATION_PROPOSED alike.
        assert fixtures.read_group(api, group_id)["escalated_l2_count"] == 1

        decided = validate_success(
            api.decide_separation(
                spell["id"], "APPROVED", PRACTICE_PARTNER_2, note="partner review"
            ),
            200,
        )
        assert decided["state"] == BenchSpellState.SEPARATED
        assert decided["separation_decision"] == SeparationDecision.APPROVED
        assert decided["separation_decided_by_user_id"] == PRACTICE_PARTNER_2_USER_ID
        assert decided["ended_on"] == "2026-09-02"

        consultant = fixtures.read_consultant(api, consultant_id)
        assert consultant["availability_status"] == AvailabilityStatus.SEPARATED
        assert consultant["separated_on"] is not None
        assert consultant["separated_on"].startswith("2026-09-02")

        after = fixtures.read_group(api, group_id)
        assert after["total_headcount"] == 0
        assert after["bench_headcount"] == 0
        assert after["escalated_l2_count"] == 0
        assert_bench_ratio(after, 0.0000, 0.0000, Posture.OPEN)

    def test_a_rejected_decision_loops_back_and_accepts_an_internal_project(self, api):
        """PRD §3.8: "A `REJECTED` decision instead returns the `state` to `ESCALATED_L2`
        with `escalation_count` untouched and `escalated_l2_count` unchanged, sets
        `separation_decision` to `REJECTED`, and stamps `separation_decided_by_user_id`."

        Design: Corner/state_machines/rejected_separation_returns_the_spell_to_the_escalation_cycle
        """
        world, consultant_id, spell = self._spell_at_the_second_rung(api)
        group_id = world["group"]["id"]
        validate_success(
            api.propose_separation(
                spell["id"], RESOURCE_MANAGER, rationale="no pipeline fit in 30 days"
            ),
            200,
        )

        rejected = validate_success(
            api.decide_separation(
                spell["id"], "REJECTED", PRACTICE_PARTNER_2, note="give her a project"
            ),
            200,
        )
        assert rejected["state"] == BenchSpellState.ESCALATED_L2
        assert rejected["separation_decision"] == SeparationDecision.REJECTED
        assert rejected["separation_decided_by_user_id"] == PRACTICE_PARTNER_2_USER_ID
        assert rejected["ended_on"] is None
        assert rejected["escalation_count"] == 2

        # Nothing about a rejection separates anyone.
        consultant = fixtures.read_consultant(api, consultant_id)
        assert consultant["availability_status"] == AvailabilityStatus.BENCH
        assert consultant["separated_on"] is None

        parked = validate_success(
            api.start_internal_project(spell["id"], "IP-KM-01", RESOURCE_MANAGER), 200
        )
        assert parked["state"] == BenchSpellState.INTERNAL_PROJECT
        assert parked["internal_project_code"] == "IP-KM-01"
        assert parked["investment_started_on"] == "2026-09-02"
        assert (
            fixtures.read_consultant(api, consultant_id)["availability_status"]
            == AvailabilityStatus.INTERNAL_PROJECT
        )

        after = fixtures.read_group(api, group_id)
        # An internal project takes the head out of the bench ratio while
        # total_headcount stays 1, and leaving ESCALATED_L2 decrements the counter.
        assert after["total_headcount"] == 1
        assert after["bench_headcount"] == 0
        assert after["escalated_l2_count"] == 0
        assert_bench_ratio(after, 0.0000, 0.0000, Posture.OPEN)


class TestTerminalPipelineLockdown:
    def test_a_closed_lost_demand_refuses_qualify_mode_and_a_second_close(self, api):
        """PRD §2.9: "8. **Demand pipeline state** — qualification requires
        `QUALIFYING`; staffing-branch selection requires `QUALIFYING` or `QUALIFIED` with
        the branch still unset; closure requires `QUALIFIED`; auto-staffing, assignment
        proposal and external-placement request all require `QUALIFIED`;
        discount-approval creation is likewise gated here. Failure:
        `ERR_OPPORTUNITY_STATE_INVALID` (409)."

        Design: Corner/state_machines/terminal_pipeline_state_accepts_no_further_transition
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        demand = fixtures.create_demand(
            api, world["group"]["id"], world["skill"]["id"], required_fte=1.00
        )
        closed = fixtures.close_demand(api, demand["id"], "LOST", note="abandoned")
        assert closed["pipeline_status"] == PipelineStatus.CLOSED_LOST
        assert closed["closed_outcome"] == ClosedOutcome.LOST
        # Nothing was staffed, so the coverage dimension never left UNSTAFFED.
        assert closed["staffing_status"] == StaffingStatus.UNSTAFFED
        assert closed["version"] == 2

        validate_error(
            api.qualify_demand(demand["id"], SALES_LEAD),
            ApiErrorId.ERR_OPPORTUNITY_STATE_INVALID,
            409,
        )
        validate_error(
            api.set_staffing_mode(demand["id"], "INTERNAL", RESOURCE_MANAGER),
            ApiErrorId.ERR_OPPORTUNITY_STATE_INVALID,
            409,
        )
        validate_error(
            api.close_demand(demand["id"], "LOST", SALES_LEAD),
            ApiErrorId.ERR_OPPORTUNITY_STATE_INVALID,
            409,
        )

        after = fixtures.read_demand(api, demand["id"])
        assert after["version"] == 2
        assert after["pipeline_status"] == PipelineStatus.CLOSED_LOST
        assert after["staffing_mode"] is None


class TestGraduationClosesTheCohort:
    @staticmethod
    def _running_cohort_with_one_enrolled_spell(api):
        """A proficiency-3 bencher enrolled at L1, in a cohort the checkpoint has
        already moved from PLANNED to RUNNING."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=3)
        consultant_id = staff["consultant"]["id"]
        enrolment = fixtures.enrolled_in_cohort(
            api,
            world,
            consultant_id,
            program_kwargs={
                "target_proficiency_level": 5,
                "cohort_start_on": "2026-09-01",
                "cohort_end_on": "2026-09-30",
                "seat_capacity": 2,
            },
            l1_instant=INSTANT_AUG_17,
        )
        fixtures.advance_clock_and_run(api, INSTANT_SEP_01)
        return world, staff, enrolment

    def test_completing_inside_the_cohort_window_is_refused(self, api):
        """PRD §2.9: "11. **Programme state** — enrolment requires `PLANNED` or
        `RUNNING`; graduation requires `RUNNING` and requires `cohort_end_on` to be on or
        before the logical clock date. Failure: `ERR_PROGRAM_STATE_INVALID` (409)."

        Design: Corner/state_machines/reskilling_completion_graduates_the_cohort_and_upgrades_the_assertion
        """
        _, _, enrolment = self._running_cohort_with_one_enrolled_spell(api)
        program_id = enrolment["program"]["id"]
        spell_id = enrolment["spell"]["id"]

        running = fixtures.read_program(api, program_id)
        assert running["status"] == ProgramStatus.RUNNING
        assert running["seats_taken"] == 1
        enrolled_spell = fixtures.read_spell(api, spell_id)
        assert enrolled_spell["state"] == BenchSpellState.RESKILLING
        assert enrolled_spell["investment_started_on"] == "2026-08-17"

        # 2026-09-30 is still in the future at the 2026-09-01 clock.
        validate_error(
            api.complete_program(program_id, RESOURCE_MANAGER),
            ApiErrorId.ERR_PROGRAM_STATE_INVALID,
            409,
        )
        assert fixtures.read_program(api, program_id)["status"] == ProgramStatus.RUNNING
        assert (
            fixtures.read_spell(api, spell_id)["state"] == BenchSpellState.RESKILLING
        )

    def test_graduation_resets_the_ladder_and_raises_the_existing_assertion(self, api):
        """PRD §3.8: "Each graduate also gets a `SkillAssertion` for the programme's
        skill: a new row at `proficiency_level` equal to `target_proficiency_level` when
        none existed, or, where one already existed for that consultant and skill, its
        `proficiency_level` raised to whichever is greater of the existing level and the
        target — never lowered."

        Design: Corner/state_machines/reskilling_completion_graduates_the_cohort_and_upgrades_the_assertion
        """
        world, staff, enrolment = self._running_cohort_with_one_enrolled_spell(api)
        consultant_id = staff["consultant"]["id"]
        program_id = enrolment["program"]["id"]
        spell_id = enrolment["spell"]["id"]

        fixtures.set_clock(api, INSTANT_SEP_30)
        completed = fixtures.complete_program(api, program_id)
        assert completed["status"] == ProgramStatus.COMPLETED
        assert completed["seats_taken"] == 0

        graduated = fixtures.read_spell(api, spell_id)
        assert graduated["state"] == BenchSpellState.MONITORING
        assert graduated["age_reset_on"] == "2026-09-30"
        assert graduated["age_days"] == 0
        assert graduated["investment_ended_on"] == "2026-09-30"
        # escalation_count is a lifetime counter and survives the cycle.
        assert graduated["escalation_count"] == 1
        assert (
            fixtures.read_consultant(api, consultant_id)["availability_status"]
            == AvailabilityStatus.BENCH
        )

        rows, meta = validate_paginated(
            api.list_skill_assertions(
                RESOURCE_MANAGER,
                {"consultant_id": consultant_id, "skill_id": world["skill"]["id"]},
            )
        )
        # The existing row was raised to max(3, 5), not duplicated.
        assert meta["total_count"] == 1
        assert rows[0]["id"] == staff["assertion"]["id"]
        assert rows[0]["proficiency_level"] == 5

        # RESKILLING and BENCH both count, so the ratio never moved.
        after = fixtures.read_group(api, world["group"]["id"])
        assert after["bench_headcount"] == 1
        assert_bench_ratio(after, 1.0000, 1.0000, Posture.FROZEN)


class TestUnstartedCommitmentIsCancelledNotReleased:
    @staticmethod
    def _confirmed_september_assignment(api):
        """A CONFIRMED 100.00% assignment whose start_date is 29 days away."""
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

    def test_releasing_before_the_start_date_is_refused(self, api):
        """PRD §3.5: "From either state it requires the logical clock date to be on or
        after the assignment's `start_date`; releasing something that has not started yet
        is refused with `ERR_ASSIGNMENT_STATE_INVALID`, because an unstarted commitment is
        cancelled rather than released."

        Design: Corner/state_machines/assignment_release_before_start_date_is_rejected_while_cancel_is_allowed
        """
        _, _, demand, assignment = self._confirmed_september_assignment(api)
        assert assignment["status"] == AssignmentStatus.CONFIRMED
        assert assignment["start_date"] == "2026-09-01"
        assert assignment["confirmed_on"] == "2026-08-03"

        validate_error(
            api.release_assignment(
                assignment["id"], RESOURCE_MANAGER, reason="client paused"
            ),
            ApiErrorId.ERR_ASSIGNMENT_STATE_INVALID,
            409,
        )

        untouched = fixtures.read_assignment(api, assignment["id"])
        assert untouched["status"] == AssignmentStatus.CONFIRMED
        assert untouched["released_on"] is None
        still = fixtures.read_demand(api, demand["id"])
        assert still["covered_internal_fte"] == pytest.approx(1.00, abs=0.005)
        assert still["staffing_status"] == StaffingStatus.COVERED

    def test_cancelling_before_the_start_date_succeeds_and_restores_coverage(self, api):
        """PRD §3.5: "Cancelling a `CONFIRMED` row additionally requires the logical clock
        date to be strictly earlier than the assignment's `start_date` — a commitment that
        has already started must be released, not cancelled — and it is the compensating
        action that restores the FTE-coverage identity exactly: `allocated_pct` is
        recomputed and, if it falls below 50.00, the identical
        availability-to-bench-spell-to-bench-ratio-to-posture cascade described above runs
        unchanged; the demand's `covered_internal_fte`, `open_fte` and `staffing_status`
        are recomputed along with realization and margin; and the demand's `version`
        increments as well."

        Design: Corner/state_machines/assignment_release_before_start_date_is_rejected_while_cancel_is_allowed
        """
        _, staff, demand, assignment = self._confirmed_september_assignment(api)
        consultant_id = staff["consultant"]["id"]
        validate_error(
            api.release_assignment(assignment["id"], RESOURCE_MANAGER),
            ApiErrorId.ERR_ASSIGNMENT_STATE_INVALID,
        )

        cancelled = fixtures.cancel(api, assignment["id"], reason="client paused")
        assert cancelled["status"] == AssignmentStatus.CANCELLED
        assert cancelled["released_on"] is None
        assert cancelled["confirmed_on"] == "2026-08-03"

        after = fixtures.read_demand(api, demand["id"])
        assert after["covered_internal_fte"] == pytest.approx(0.00, abs=0.005)
        assert after["open_fte"] == pytest.approx(1.00, abs=0.005)
        assert after["staffing_status"] == StaffingStatus.INTERNAL_STAFFING

        consultant = fixtures.read_consultant(api, consultant_id)
        assert consultant["allocated_pct"] == pytest.approx(0.00, abs=0.005)
        assert consultant["availability_status"] == AvailabilityStatus.BENCH

        spells, meta = validate_paginated(
            api.list_bench_spells(RESOURCE_MANAGER, {"consultant_id": consultant_id})
        )
        # The first spell never closed, so no second spell was created.
        assert meta["total_count"] == 1
        assert spells[0]["state"] == BenchSpellState.MONITORING
        assert spells[0]["started_on"] == "2026-08-03"
