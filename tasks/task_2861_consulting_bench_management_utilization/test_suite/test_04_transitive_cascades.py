"""Deep cascades: one release freezing an ancestor, one approval breaching margin."""

import pytest

from test_helpers import (
    FINANCE_CONTROLLER,
    ApprovalDecision,
    ApprovalStatus,
    ApprovalTier,
    AssignmentStatus,
    AvailabilityStatus,
    BenchSpellState,
    Posture,
    StaffingStatus,
    assert_bench_ratio,
    assert_margin_breach_consistent,
    fixtures,
)
from test_helpers.constants import INSTANT_AUG_03
from test_helpers.test_users import FINANCE_CONTROLLER_USER_ID


class TestReleaseFreezesTheAncestorChain:
    @staticmethod
    def _fully_staffed_child_group(api):
        """A parent with no headcount of its own over a child holding the firm's
        only consultant, fully committed and mid-interval."""
        world = fixtures.parent_child_world(api, clock=INSTANT_AUG_03)
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
        fixtures.set_clock(api, "2026-08-10T00:00:00Z")
        return world, staff, demand, assignment

    def test_one_release_walks_allocation_availability_and_a_new_spell(self, api):
        """PRD §3.5: "Hop one to two: the consultant's `allocated_pct` is recomputed.
        Hop two to three: because that value has fallen below 50.00, the consultant's
        `availability_status` becomes `BENCH`. Hop three to four: because the
        consultant is now on the bench and holds no open spell, a new bench spell row
        is created in state `MONITORING` with `started_on` stamped from the clock date
        and `escalation_count` at 0."

        Design: Difficulty/transitive_cascade/release_to_ancestor_posture_freeze_chain
        """
        _, staff, _, assignment = self._fully_staffed_child_group(api)
        consultant_id = staff["consultant"]["id"]

        released = fixtures.release(
            api, assignment["id"], reason="client paused the programme"
        )

        assert released["status"] == AssignmentStatus.RELEASED
        assert released["released_on"] == "2026-08-10"

        consultant = fixtures.read_consultant(api, consultant_id)
        assert consultant["allocated_pct"] == pytest.approx(0.00, abs=0.005)
        assert consultant["availability_status"] == AvailabilityStatus.BENCH

        spells = fixtures.spells_of(api, consultant_id)
        assert len(spells) == 2, "the closed hiring spell plus the one the release opened"
        closed = [row for row in spells if row["state"] == BenchSpellState.CLOSED]
        opened = [row for row in spells if row["ended_on"] is None]
        assert len(closed) == 1 and closed[0]["started_on"] == "2026-08-03"
        assert len(opened) == 1
        assert opened[0]["state"] == BenchSpellState.MONITORING
        assert opened[0]["started_on"] == "2026-08-10"
        assert opened[0]["age_days"] == 0
        assert opened[0]["escalation_count"] == 0

    def test_the_last_two_hops_freeze_a_group_the_consultant_does_not_belong_to(
        self, api
    ):
        """PRD §3.5: "Hop four to five: because that spell now exists, the group's
        `bench_headcount` increments and `own_bench_ratio` and `rollup_bench_ratio`
        are recomputed for the group and every ancestor. Hop five to six: because
        `rollup_bench_ratio` may have crossed a breakpoint, `posture` is re-derived
        for the group and every ancestor — moving from `OPEN` to `CONSTRAINED` at a
        ratio of 0.3000 or more and to `FROZEN` at 0.5000 or more."

        Design: Difficulty/transitive_cascade/release_to_ancestor_posture_freeze_chain
        """
        world, _, demand, assignment = self._fully_staffed_child_group(api)
        child_id = world["child"]["id"]
        parent_id = world["parent"]["id"]

        before_child = fixtures.read_group(api, child_id)
        before_parent = fixtures.read_group(api, parent_id)
        assert before_child["bench_headcount"] == 0
        assert_bench_ratio(before_child, 0.0000, 0.0000, Posture.OPEN)
        assert_bench_ratio(before_parent, 0.0000, 0.0000, Posture.OPEN)

        fixtures.release(api, assignment["id"], reason="client paused the programme")

        after_child = fixtures.read_group(api, child_id)
        assert after_child["total_headcount"] == 1
        assert after_child["bench_headcount"] == 1
        assert_bench_ratio(after_child, 1.0000, 1.0000, Posture.FROZEN)

        after_parent = fixtures.read_group(api, parent_id)
        assert after_parent["total_headcount"] == 0
        assert after_parent["bench_headcount"] == 0
        # The ancestor freezes on the subtree ratio, not on its own headcount.
        assert_bench_ratio(after_parent, 0.0000, 1.0000, Posture.FROZEN)

        side_chain = fixtures.read_demand(api, demand["id"])
        assert side_chain["covered_internal_fte"] == pytest.approx(0.00, abs=0.005)
        assert side_chain["open_fte"] == pytest.approx(1.00, abs=0.005)
        assert side_chain["staffing_status"] == StaffingStatus.INTERNAL_STAFFING
        assert side_chain["earned_realization_pct"] == pytest.approx(96.00, abs=0.01)


class TestApprovalDrivesMarginBreach:
    @staticmethod
    def _confirmed_at_list_price_with_a_pending_cut(api):
        """A 170.00-cost consultant confirmed at 250.00, then a 200.00 request."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=4,
            cost_rate_usd_per_hour=170.00,
            standard_bill_rate_usd_per_hour=400.00,
        )
        demand = fixtures.qualified_demand(
            api,
            world,
            min_proficiency_level=3,
            required_fte=1.00,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        assignment = fixtures.confirmed_assignment(
            api,
            staff["consultant"]["id"],
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        fixtures.set_clock(api, "2026-08-10T00:00:00Z")
        approval = fixtures.request_discount(
            api, demand["id"], 200.00, decision_note="renewal at 200"
        )
        return world, demand, assignment, approval

    def test_approval_cascades_the_rate_onto_the_demand(self, api):
        """PRD §3.7: "Hop one to two: the demand's `approved_rate_usd_per_hour` is set
        to the approval's `requested_rate_usd_per_hour`, so the demand's
        `effective_rate_usd_per_hour` and `booked_realization_pct` are recomputed."

        Design: Difficulty/transitive_cascade/discount_approval_to_margin_breach_chain
        """
        _, demand, assignment, approval = self._confirmed_at_list_price_with_a_pending_cut(
            api
        )

        before_demand = fixtures.read_demand(api, demand["id"])
        assert before_demand["booked_realization_pct"] == pytest.approx(100.00, abs=0.01)
        assert before_demand["blended_margin_pct"] == pytest.approx(32.00, abs=0.01)
        assert before_demand["margin_breach"] is False
        before_assignment = fixtures.read_assignment(api, assignment["id"])
        assert before_assignment["bill_rate_usd_per_hour"] == pytest.approx(250.00, abs=0.01)

        assert approval["required_tier"] == ApprovalTier.L2_FINANCE
        assert approval["tier_escalated"] is False
        assert approval["blended_cost_rate_usd_per_hour"] == pytest.approx(170.00, abs=0.01)
        assert approval["projected_margin_pct"] == pytest.approx(15.00, abs=0.01)

        decided = fixtures.decide_discount(
            api,
            approval["id"],
            ApprovalDecision.APPROVED,
            headers=FINANCE_CONTROLLER,
            decision_note="approved on volume commitment",
        )
        assert decided["status"] == ApprovalStatus.APPROVED
        assert decided["decided_by_user_id"] == FINANCE_CONTROLLER_USER_ID

        after = fixtures.read_demand(api, demand["id"])
        assert after["approved_rate_usd_per_hour"] == pytest.approx(200.00, abs=0.01)
        assert after["effective_rate_usd_per_hour"] == pytest.approx(200.00, abs=0.01)
        assert after["booked_realization_pct"] == pytest.approx(80.00, abs=0.01)

    def test_the_repinned_bill_rate_flips_margin_breach_true(self, api):
        """PRD §3.7: "Hop two to three: because the effective rate changed, every
        assignment on the demand whose `status` is `PROPOSED`, `CONFIRMED` or `ACTIVE`
        and whose `category` is `BILLABLE` has its `bill_rate_usd_per_hour` re-pinned
        to the new effective rate, while `RELEASED` and `CANCELLED` rows keep their
        frozen values. Hop three to four: because those bill rates changed, the
        demand's `earned_realization_pct`, `blended_margin_pct` and `margin_breach`
        are recomputed from the re-priced rows."

        Design: Difficulty/transitive_cascade/discount_approval_to_margin_breach_chain
        """
        _, demand, assignment, approval = self._confirmed_at_list_price_with_a_pending_cut(
            api
        )

        fixtures.decide_discount(
            api,
            approval["id"],
            ApprovalDecision.APPROVED,
            headers=FINANCE_CONTROLLER,
            decision_note="approved on volume commitment",
        )

        repriced = fixtures.read_assignment(api, assignment["id"])
        assert repriced["bill_rate_usd_per_hour"] == pytest.approx(200.00, abs=0.01)
        # The cascade re-pins the bill rate only, never the cost snapshot or status.
        assert repriced["cost_rate_usd_per_hour"] == pytest.approx(170.00, abs=0.01)
        assert repriced["status"] == AssignmentStatus.CONFIRMED

        after = fixtures.read_demand(api, demand["id"])
        assert after["earned_realization_pct"] == pytest.approx(80.00, abs=0.01)
        assert after["blended_cost_rate_usd_per_hour"] == pytest.approx(170.00, abs=0.01)
        assert after["blended_margin_pct"] == pytest.approx(15.00, abs=0.01)
        # A 15.00 percent margin is a state no confirmation could have produced.
        assert after["margin_breach"] is True
        assert_margin_breach_consistent(after)
