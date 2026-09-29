"""Cycles and parallel dimensions: bench reskilling, demand pair, discount loop."""

import pytest

from test_helpers import (
    FINANCE_CONTROLLER,
    PRACTICE_PARTNER,
    SALES_LEAD_USER_ID,
    ApiErrorId,
    ApprovalDecision,
    ApprovalStatus,
    ApprovalTier,
    AssignmentStatus,
    AvailabilityStatus,
    BenchSpellState,
    ClosedOutcome,
    PipelineStatus,
    ProgramStatus,
    StaffingStatus,
    fixtures,
    validate_error,
)
from test_helpers.constants import INSTANT_AUG_03
from test_helpers.test_users import (
    FINANCE_CONTROLLER_USER_ID,
    PRACTICE_PARTNER_USER_ID,
)

COHORT = {
    "target_proficiency_level": 5,
    "cohort_start_on": "2026-08-18",
    "cohort_end_on": "2026-08-28",
    "seat_capacity": 2,
}


class TestBenchSpellReskillingCycle:
    @staticmethod
    def _escalated_and_enrolled(api):
        """A CONSULTANT-level bencher escalated at 14 days, then enrolled."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=4)
        consultant_id = staff["consultant"]["id"]
        cohort = fixtures.enrolled_in_cohort(
            api,
            world,
            consultant_id,
            program_kwargs=dict(COHORT),
            l1_instant="2026-08-17T00:00:00Z",
        )
        return world, staff, cohort

    def test_enrolment_moves_the_spell_into_reskilling_and_takes_a_seat(self, api):
        """PRD §3.8: "A successful enrolment sets the spell's `state` to
        `RESKILLING`, stamps `reskilling_program_id` and stamps
        `investment_started_on` from the logical clock date, recomputes the
        programme's `seats_taken` upward by one, and sets the consultant's
        `availability_status` to `RESKILLING` — which removes them from every
        auto-staff candidate pool and forces their match score to 0.0000."

        Design: Difficulty/non_linear_state_machine/bench_spell_reskilling_cycle_returns_to_monitoring
        """
        _, staff, cohort = self._escalated_and_enrolled(api)
        spell = cohort["spell"]

        assert spell["state"] == BenchSpellState.RESKILLING
        assert spell["reskilling_program_id"] == cohort["program"]["id"]
        assert spell["investment_started_on"] == "2026-08-17"
        assert spell["escalation_count"] == 1
        assert spell["ended_on"] is None
        assert cohort["program"]["seats_taken"] == 1

        consultant = fixtures.read_consultant(api, staff["consultant"]["id"])
        assert consultant["availability_status"] == AvailabilityStatus.RESKILLING

        # The checkpoint opens the cohort, and the ladder skips a RESKILLING spell,
        # so no further escalation happens while the consultant is in the cohort.
        fixtures.advance_clock_and_run(api, "2026-08-18T00:00:00Z")
        assert (
            fixtures.read_program(api, cohort["program"]["id"])["status"]
            == ProgramStatus.RUNNING
        )
        mid_cohort = fixtures.read_spell(api, spell["id"])
        assert mid_cohort["state"] == BenchSpellState.RESKILLING
        assert mid_cohort["escalation_count"] == 1

    def test_graduation_returns_the_spell_to_monitoring_with_the_age_reset(self, api):
        """PRD §3.8: "Then, for every spell enrolled in it, the spell's `state`
        returns to `MONITORING`, `age_reset_on` is stamped from the logical clock
        date so `age_days` falls back to 0 and the whole ladder can be climbed
        again, `investment_ended_on` is stamped as the exclusive end of the
        investment window, and the consultant's `availability_status` returns to
        `BENCH`."

        Design: Difficulty/non_linear_state_machine/bench_spell_reskilling_cycle_returns_to_monitoring
        """
        world, staff, cohort = self._escalated_and_enrolled(api)
        consultant_id = staff["consultant"]["id"]
        spell_id = cohort["spell"]["id"]

        fixtures.advance_clock_and_run(api, "2026-08-18T00:00:00Z")
        fixtures.set_clock(api, "2026-08-28T00:00:00Z")
        program = fixtures.complete_program(api, cohort["program"]["id"])

        assert program["status"] == ProgramStatus.COMPLETED
        assert program["seats_taken"] == 0

        graduated = fixtures.read_spell(api, spell_id)
        # The row is back in a state it already occupied.
        assert graduated["state"] == BenchSpellState.MONITORING
        assert graduated["age_reset_on"] == "2026-08-28"
        assert graduated["age_days"] == 0
        # The escalation history is a lifetime counter and survives the cycle.
        assert graduated["escalation_count"] == 1
        assert graduated["investment_ended_on"] == "2026-08-28"
        assert graduated["ended_on"] is None

        consultant = fixtures.read_consultant(api, consultant_id)
        assert consultant["availability_status"] == AvailabilityStatus.BENCH

        rows = fixtures.assertions_of(
            api, consultant_id, skill_id=world["skill"]["id"]
        )
        assert len(rows) == 1, "graduation raises the existing assertion, it does not insert"
        assert rows[0]["id"] == staff["assertion"]["id"]
        assert rows[0]["proficiency_level"] == 5


class TestOpportunityParallelDimensions:
    @staticmethod
    def _two_candidates_and_a_registered_demand(api):
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        ada = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=4,
            cost_rate_usd_per_hour=120.00,
        )
        grace = fixtures.hire(
            api,
            world,
            full_name="Grace Hopper",
            proficiency_level=3,
            cost_rate_usd_per_hour=140.00,
        )
        demand = fixtures.create_demand(
            api,
            world["group"]["id"],
            world["skill"]["id"],
            client_name="Acme Retail",
            required_fte=1.00,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=240.00,
        )
        return world, ada, grace, demand

    def test_the_two_dimensions_advance_independently_of_one_another(self, api):
        """PRD §3.4: "A demand carries **two independent status dimensions on the
        same row**, and keeping them straight is the single most important structural
        fact about this entity."

        Design: Difficulty/non_linear_state_machine/opportunity_parallel_pipeline_and_staffing_dimensions
        """
        _, ada, grace, demand = self._two_candidates_and_a_registered_demand(api)
        pairs = [(demand["pipeline_status"], demand["staffing_status"])]

        qualified = fixtures.qualify(api, demand["id"])
        pairs.append((qualified["pipeline_status"], qualified["staffing_status"]))

        branched = fixtures.set_mode(api, demand["id"], "INTERNAL")
        pairs.append((branched["pipeline_status"], branched["staffing_status"]))

        first = fixtures.propose_assignment(
            api,
            ada["consultant"]["id"],
            demand["id"],
            allocation_pct=50.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        proposed = fixtures.read_demand(api, demand["id"])
        # A PROPOSED row contributes nothing, so the staffing dimension has not moved.
        assert proposed["staffing_status"] == StaffingStatus.INTERNAL_STAFFING
        assert proposed["covered_internal_fte"] == pytest.approx(0.00, abs=0.005)

        fixtures.confirm(api, first["id"])
        half = fixtures.read_demand(api, demand["id"])
        pairs.append((half["pipeline_status"], half["staffing_status"]))
        assert half["covered_internal_fte"] == pytest.approx(0.50, abs=0.005)
        assert half["open_fte"] == pytest.approx(0.50, abs=0.005)

        second = fixtures.propose_assignment(
            api,
            grace["consultant"]["id"],
            demand["id"],
            allocation_pct=50.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        fixtures.confirm(api, second["id"])
        full = fixtures.read_demand(api, demand["id"])
        pairs.append((full["pipeline_status"], full["staffing_status"]))
        assert full["covered_internal_fte"] == pytest.approx(1.00, abs=0.005)
        assert full["open_fte"] == pytest.approx(0.00, abs=0.005)

        assert pairs == [
            (PipelineStatus.QUALIFYING, StaffingStatus.UNSTAFFED),
            (PipelineStatus.QUALIFIED, StaffingStatus.UNSTAFFED),
            (PipelineStatus.QUALIFIED, StaffingStatus.INTERNAL_STAFFING),
            (PipelineStatus.QUALIFIED, StaffingStatus.PARTIALLY_COVERED),
            (PipelineStatus.QUALIFIED, StaffingStatus.COVERED),
        ]

    def test_the_won_closure_moves_only_the_pipeline_dimension(self, api):
        """PRD §3.5: "The operations checkpoint of §3.9 later moves a `CONFIRMED`
        assignment whose `start_date` has arrived to `ACTIVE`, stamping `activated_on`
        with the clock date, and a `WON` closure does the same for every `CONFIRMED`
        assignment on the demand."

        Design: Difficulty/non_linear_state_machine/opportunity_parallel_pipeline_and_staffing_dimensions
        """
        _, ada, grace, demand = self._two_candidates_and_a_registered_demand(api)
        fixtures.qualify(api, demand["id"])
        fixtures.set_mode(api, demand["id"], "INTERNAL")
        first = fixtures.confirmed_assignment(
            api,
            ada["consultant"]["id"],
            demand["id"],
            allocation_pct=50.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        second = fixtures.confirmed_assignment(
            api,
            grace["consultant"]["id"],
            demand["id"],
            allocation_pct=50.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )

        closed = fixtures.close_demand(api, demand["id"], "WON", note="signed")

        assert closed["pipeline_status"] == PipelineStatus.CLOSED_WON
        assert closed["closed_outcome"] == ClosedOutcome.WON
        # The coverage dimension held its value across the pipeline transition.
        assert closed["staffing_status"] == StaffingStatus.COVERED
        assert closed["covered_internal_fte"] == pytest.approx(1.00, abs=0.005)

        for assignment_id in (first["id"], second["id"]):
            activated = fixtures.read_assignment(api, assignment_id)
            assert activated["status"] == AssignmentStatus.ACTIVE
            assert activated["activated_on"] == "2026-08-03"


class TestDiscountRejectReviseCycle:
    @staticmethod
    def _pending_deep_discount(api):
        """A 20.00 percent request on an unstaffed demand, so S3 is level-floor."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        demand = fixtures.qualified_demand(
            api,
            world,
            staffing_mode=None,
            min_proficiency_level=3,
            required_fte=1.00,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        approval = fixtures.request_discount(
            api, demand["id"], 200.00, decision_note="competitive pressure"
        )
        return world, demand, approval

    def test_revision_re_enters_pending_and_recomputes_the_tier_from_scratch(self, api):
        """PRD §3.7: "A successful revision sets `status` back to `PENDING`,
        increments `revision_count` by one, clears `decided_by_user_id`, and
        re-stamps `requested_by_user_id` with the reviser's `X-User-ID` — so the
        identity barred from deciding follows the negotiation. The first six steps of
        the pass are then re-run from scratch against the new rate and the **current**
        assignment mix, so `discount_pct`, `provisional_realization_pct`,
        `blended_cost_rate_usd_per_hour`, `projected_margin_pct`, `required_tier` and
        `tier_escalated` may all change."

        Design: Difficulty/non_linear_state_machine/discount_approval_reject_revise_cycle
        """
        _, demand, approval = self._pending_deep_discount(api)

        assert approval["discount_pct"] == pytest.approx(20.00, abs=0.01)
        assert approval["provisional_realization_pct"] == pytest.approx(80.00, abs=0.01)
        assert approval["blended_cost_rate_usd_per_hour"] == pytest.approx(80.00, abs=0.01)
        assert approval["projected_margin_pct"] == pytest.approx(60.00, abs=0.01)
        assert approval["required_tier"] == ApprovalTier.L2_FINANCE
        assert approval["tier_escalated"] is False
        assert approval["status"] == ApprovalStatus.PENDING
        assert approval["requested_by_user_id"] == SALES_LEAD_USER_ID
        assert approval["revision_count"] == 0

        rejected = fixtures.decide_discount(
            api,
            approval["id"],
            ApprovalDecision.REJECTED,
            headers=FINANCE_CONTROLLER,
            decision_note="20 percent is too deep",
        )
        assert rejected["status"] == ApprovalStatus.REJECTED
        assert rejected["decided_by_user_id"] == FINANCE_CONTROLLER_USER_ID
        assert fixtures.read_demand(api, demand["id"])["approved_rate_usd_per_hour"] is None

        revised = fixtures.revise_discount(
            api, approval["id"], 225.00, decision_note="meet in the middle"
        )
        # The row re-enters a state it had already left, with new derived values.
        assert revised["status"] == ApprovalStatus.PENDING
        assert revised["requested_rate_usd_per_hour"] == pytest.approx(225.00, abs=0.01)
        assert revised["revision_count"] == 1
        assert revised["discount_pct"] == pytest.approx(10.00, abs=0.01)
        assert revised["provisional_realization_pct"] == pytest.approx(90.00, abs=0.01)
        assert revised["blended_cost_rate_usd_per_hour"] == pytest.approx(80.00, abs=0.01)
        assert revised["projected_margin_pct"] == pytest.approx(64.44, abs=0.01)
        assert revised["required_tier"] == ApprovalTier.L1_PRACTICE_PARTNER
        assert revised["tier_escalated"] is False
        assert revised["decided_by_user_id"] is None

    def test_the_partner_may_only_decide_after_the_tier_has_dropped(self, api):
        """PRD §3.7: "The row must be `PENDING`; the caller's `X-User-ID` must differ
        from `requested_by_user_id`; the caller's role must satisfy `required_tier`
        per §2.11; and the stored `discount_pct` must still be within the 35.00
        percent hard cap."

        Design: Difficulty/non_linear_state_machine/discount_approval_reject_revise_cycle
        """
        _, demand, approval = self._pending_deep_discount(api)

        too_junior = api.decide_discount_approval(
            approval["id"], ApprovalDecision.APPROVED, PRACTICE_PARTNER
        )
        validate_error(too_junior, ApiErrorId.ERR_APPROVAL_TIER_INSUFFICIENT)
        assert (
            fixtures.read_approval(api, approval["id"])["status"]
            == ApprovalStatus.PENDING
        )

        fixtures.decide_discount(
            api,
            approval["id"],
            ApprovalDecision.REJECTED,
            headers=FINANCE_CONTROLLER,
            decision_note="20 percent is too deep",
        )
        fixtures.revise_discount(
            api, approval["id"], 225.00, decision_note="meet in the middle"
        )

        approved = fixtures.decide_discount(
            api,
            approval["id"],
            ApprovalDecision.APPROVED,
            headers=PRACTICE_PARTNER,
            decision_note="10 percent is within practice authority",
        )
        assert approved["status"] == ApprovalStatus.APPROVED
        assert approved["decided_by_user_id"] == PRACTICE_PARTNER_USER_ID

        cascaded = fixtures.read_demand(api, demand["id"])
        assert cascaded["approved_rate_usd_per_hour"] == pytest.approx(225.00, abs=0.01)
        assert cascaded["effective_rate_usd_per_hour"] == pytest.approx(225.00, abs=0.01)
        assert cascaded["booked_realization_pct"] == pytest.approx(90.00, abs=0.01)
        # No assignment ever existed, so the earned variant has no delivered hours.
        assert cascaded["earned_realization_pct"] is None
