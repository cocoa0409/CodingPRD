"""Cyclic negotiation, the execution fork-join, and the two award cascades.

The scenarios here follow state that does not move in a straight line: a bid that
re-enters `UNDER_REVIEW` after a second counter/revise loop, a contract whose
signature dimension finishes before its approval dimension so execution fires
from the last approval, an award that propagates through four different entities,
and an approval rejection that unwinds that award again.
"""

from typing import Any, Dict

import pytest

from test_helpers import (
    APPROVER_ALT_HEADERS,
    APPROVER_ALT_USER_ID,
    APPROVER_HEADERS,
    APPROVER_USER_ID,
    CLOCK_SOURCING_WINDOW,
    FINANCE_HEADERS,
    PLANNER_HEADERS,
    api_client,
    assertions as domain_assert,
    fixtures,
    validate_paginated,
    validate_success,
)

# The runner-up's grid: a smaller, cheaper commissionable block, so the canonical
# bid is the one worth awarding.
RUNNER_UP_BID_GRID: Dict[str, Any] = {
    "room_rate_usd": 275.00,
    "rate_type": "GROSS",
    "commission_pct": 0.10,
    "room_nights_offered": 400,
    "comp_room_ratio": 40,
    "resort_fee_usd_per_night": 0.00,
    "service_charge_pct": 0.22,
    "tax_pct": 0.145,
    "av_estimate_usd": 30000.00,
    "fnb_minimum_usd": 90000.00,
    "concession_credit_usd": 12000.00,
    "attrition_allowance_pct": 0.05,
    "rebooking_credit_pct": 0.40,
}


# ---------------------------------------------------------------------------
# Scenario builders local to this module
# ---------------------------------------------------------------------------
@pytest.fixture
def two_loop_negotiation() -> Dict[str, Any]:
    """One bid taken twice around the counter/revise/evaluate cycle.

    The first loop is accepted at a lower rate; the second loop asks for a richer
    concession and the venue declines it, then the planner re-prices the bid.
    """
    world = fixtures.build_negotiation_cycle(loops=1)
    second_counter = fixtures.raise_counter(
        world["proposal_id"],
        term_category="CONCESSION",
        proposed_numeric_value=30000.00,
        planner_note="Raise the concession credit to 30000.00.",
    )
    fixtures.revise_bid(
        world["proposal_id"],
        world["venue_id"],
        second_counter["id"],
        accepted=False,
    )
    fixtures.evaluate_bid(world["proposal_id"], "CONTRACTED_BASIS")
    world["first_counter"] = world["counters"][0]
    world["second_counter"] = second_counter
    world["proposal"] = fixtures.read_proposal(world["proposal_id"])
    return world


@pytest.fixture
def countersigned_then_approved() -> Dict[str, Any]:
    """A contract signed by both parties while its approvals are still running.

    The signature dimension therefore reaches its end first and the final
    approval is what closes the contract out.
    """
    world = fixtures.build_routed_contract()
    fixtures.sign_contract(world["contract_id"])
    fixtures.countersign_contract(world["contract_id"], world["venue_id"])
    steps = sorted(fixtures.approval_steps(world["contract_id"]), key=lambda s: s["step_seq"])
    fixtures.decide_step(steps[0]["id"], "APPROVED", APPROVER_HEADERS)
    world["contract_before"] = fixtures.read_contract(world["contract_id"])
    world["final_step"] = fixtures.decide_step(steps[1]["id"], "APPROVED", APPROVER_ALT_HEADERS)
    world["first_step_id"] = steps[0]["id"]
    world["final_step_id"] = steps[1]["id"]
    world["contract"] = fixtures.read_contract(world["contract_id"])
    world["event"] = fixtures.read_event(world["event_id"])
    world["entry"] = fixtures.read_entry(world["entry_id"])
    world["venue"] = fixtures.read_venue(world["venue_id"])
    return world


@pytest.fixture
def award_cascade_world() -> Dict[str, Any]:
    """Two bidders on one round, the runner-up carrying a planned inspection.

    The canonical grid is awarded, which is the trigger the cascade follows.
    """
    world = fixtures.build_sourcing_world()
    venue_b = fixtures.create_second_venue()
    entry_b = fixtures.add_entry(world["event_id"], venue_b["id"], rank_seq=2)
    entry_b = fixtures.promote_entry(entry_b["id"])
    inspection = fixtures.plan_inspection(entry_b["id"])
    rfp = fixtures.issue_rfp(fixtures.create_rfp(world["event_id"])["id"])
    proposal_a = fixtures.find_invited_proposal(rfp["id"], world["venue_id"])
    proposal_b = fixtures.find_invited_proposal(rfp["id"], venue_b["id"])
    fixtures.submit_bid(proposal_a["id"], world["venue_id"])
    fixtures.submit_bid(proposal_b["id"], venue_b["id"], **RUNNER_UP_BID_GRID)
    fixtures.close_rfp(rfp["id"])
    fixtures.evaluate_bid(proposal_a["id"], "CONTRACTED_BASIS")
    fixtures.evaluate_bid(proposal_b["id"], "CONTRACTED_BASIS")
    contract = fixtures.award_bid(world["event_id"], proposal_a["id"])
    world.update(
        {
            "venue_b_id": venue_b["id"],
            "entry_b_id": entry_b["id"],
            "inspection_id": inspection["id"],
            "rfp_id": rfp["id"],
            "proposal_id": proposal_a["id"],
            "proposal_b_id": proposal_b["id"],
            "contract": contract,
            "contract_id": contract["id"],
            "winning_proposal": fixtures.read_proposal(proposal_a["id"]),
            "losing_proposal": fixtures.read_proposal(proposal_b["id"]),
            "losing_entry": fixtures.read_entry(entry_b["id"]),
            "cancelled_inspection": fixtures.read_inspection(inspection["id"]),
            "winning_entry": fixtures.read_entry(world["entry_id"]),
            "event": fixtures.read_event(world["event_id"]),
            "venue": fixtures.read_venue(world["venue_id"]),
        }
    )
    return world


@pytest.fixture
def rejected_approval_world() -> Dict[str, Any]:
    """A planner-signed contract whose first control step is rejected."""
    world = fixtures.build_routed_contract()
    fixtures.sign_contract(world["contract_id"])
    steps = sorted(fixtures.approval_steps(world["contract_id"]), key=lambda s: s["step_seq"])
    world["rejected_step"] = fixtures.decide_step(steps[0]["id"], "REJECTED", APPROVER_HEADERS)
    world["skipped_step"] = validate_success(
        api_client.get_approval_step(steps[1]["id"], PLANNER_HEADERS)
    )
    world["contract"] = fixtures.read_contract(world["contract_id"])
    world["proposal"] = fixtures.read_proposal(world["proposal_id"])
    world["event"] = fixtures.read_event(world["event_id"])
    world["entry"] = fixtures.read_entry(world["entry_id"])
    world["venue"] = fixtures.read_venue(world["venue_id"])
    return world


class TestNegotiationCycleRevisitsReview:
    """One bid driven twice around the counter/revise/evaluate loop."""

    def test_the_bid_re_enters_review_after_the_second_loop(self, two_loop_negotiation):
        """Two full loops leave the bid back in the state it started them from.

        From `REVISED` the planner evaluates again, which returns the bid to `UNDER_REVIEW` and closes the loop; the cycle `UNDER_REVIEW → COUNTERED → REVISED → UNDER_REVIEW` may run as many times as the negotiation requires, and each pass leaves one more counter row and one more evaluation row behind as the audit trail.

        Design: Difficulty/non_linear_state_machine/proposal_negotiation_cycle_revisits_under_review
        """
        domain_assert.assert_fields_equal(
            two_loop_negotiation["proposal"], {"status": "UNDER_REVIEW"}
        )

    def test_the_round_count_reaches_two(self, two_loop_negotiation):
        """Each countering pass bumps the bid's negotiation round count.

        The bid then moves `UNDER_REVIEW → COUNTERED`, its `negotiation_round_count` increases by 1, and its `version` advances by 1.

        Design: Difficulty/non_linear_state_machine/proposal_negotiation_cycle_revisits_under_review
        """
        domain_assert.assert_integer(
            two_loop_negotiation["proposal"]["negotiation_round_count"],
            2,
            "negotiation_round_count",
        )

    def test_counters_are_numbered_in_creation_order(self, two_loop_negotiation):
        """The two counters carry a 1-based sequence within the bid.

        A successful counter is created with HTTP 201 in `resolution` `OPEN`, with `resolved_at` null, with `initiated_by_user_id` set to the calling planner's `X-User-ID`, and with `round_seq` set to the bid's `negotiation_round_count` plus 1, giving a 1-based sequence in creation order within the bid.

        Design: Difficulty/non_linear_state_machine/proposal_negotiation_cycle_revisits_under_review
        """
        domain_assert.assert_integer(
            two_loop_negotiation["first_counter"]["round_seq"], 1, "round_seq"
        )
        domain_assert.assert_integer(
            two_loop_negotiation["second_counter"]["round_seq"], 2, "round_seq"
        )

    def test_acceptance_and_refusal_resolve_their_own_counter(self, two_loop_negotiation):
        """The venue's answer decides each counter's resolution separately.

        On success the referenced counter's `resolution` becomes `ACCEPTED` when `accepted` is `true` and `DECLINED_BY_VENUE` when it is `false`, and its `resolved_at` is stamped from the logical clock.

        Design: Difficulty/non_linear_state_machine/proposal_negotiation_cycle_revisits_under_review
        """
        counters, _meta = validate_paginated(
            api_client.list_negotiation_counters(
                two_loop_negotiation["proposal_id"], PLANNER_HEADERS
            )
        )
        by_seq = {row["round_seq"]: row for row in counters}
        domain_assert.assert_fields_equal(by_seq[1], {"resolution": "ACCEPTED"})
        domain_assert.assert_fields_equal(by_seq[2], {"resolution": "DECLINED_BY_VENUE"})

    def test_only_the_accepted_term_is_rewritten_on_the_bid(self, two_loop_negotiation):
        """The declined concession leaves the quoted credit exactly as submitted.

        Each supplied revised value overwrites the corresponding quoted term on the bid — a supplied `revised_room_rate_usd` becomes the new `room_rate_usd`, a supplied `revised_fnb_minimum_usd` becomes the new `fnb_minimum_usd`, and so on for each pair — while omitted fields leave their quoted term untouched.

        Design: Difficulty/non_linear_state_machine/proposal_negotiation_cycle_revisits_under_review
        """
        proposal = two_loop_negotiation["proposal"]
        domain_assert.assert_money_field(proposal, "room_rate_usd", 235.00)
        domain_assert.assert_money_field(proposal, "concession_credit_usd", 25000.00)

    def test_revision_re_prices_the_bid_on_the_contracted_basis(
        self, two_loop_negotiation
    ):
        """The negotiated rate flows through to the bid's contracted total.

        The contracted-basis cost model is then re-run over the revised terms, refreshing `net_adr_usd`, `comp_room_nights`, `paid_room_nights` and `total_cost_contracted_usd`, and the benchmark rules are re-run, refreshing `benchmark_variance_pct` and `compliance_status`.

        Design: Difficulty/non_linear_state_machine/proposal_negotiation_cycle_revisits_under_review
        """
        proposal = two_loop_negotiation["proposal"]
        domain_assert.assert_money_field(proposal, "net_adr_usd", 235.00)
        domain_assert.assert_money_field(proposal, "total_cost_contracted_usd", 436722.27)

    def test_the_negotiated_rate_sits_below_benchmark(self, two_loop_negotiation):
        """The variance against the published benchmark is negative and four-decimal.

        With the benchmark in hand, `benchmark_variance_pct` is the signed fraction by which the bid's `net_adr_usd` exceeds the benchmark's `benchmark_adr_usd`: the difference between `net_adr_usd` and `benchmark_adr_usd`, divided by `benchmark_adr_usd`, rounded half up to **four** decimal places.

        Design: Difficulty/non_linear_state_machine/proposal_negotiation_cycle_revisits_under_review
        """
        domain_assert.assert_variance_pct(
            two_loop_negotiation["proposal"]["benchmark_variance_pct"], -0.0962
        )

    def test_a_below_benchmark_preferred_venue_is_compliant(self, two_loop_negotiation):
        """A preferred supplier priced under benchmark earns the top verdict.

        When the venue's `preferred_supplier_status` is `PREFERRED` or `CONDITIONAL`, a variance at or below `0.0000` earns `COMPLIANT`; a variance above `0.0000` but at or below the maximum programme premium of `0.1000` — ten percent over benchmark — earns `COMPLIANT_WITH_VARIANCE`; and a variance above `0.1000` earns `NON_COMPLIANT`.

        Design: Difficulty/non_linear_state_machine/proposal_negotiation_cycle_revisits_under_review
        """
        domain_assert.assert_fields_equal(
            two_loop_negotiation["proposal"], {"compliance_status": "COMPLIANT"}
        )

    def test_both_counters_are_listed_in_sequence_order(self, two_loop_negotiation):
        """The bid's counter trail holds one row per pass, in sequence order.

        Four collections carry an explicit ordering that supersedes that default: a bid's cost-model snapshots are returned oldest first, a bid's negotiation counters are returned in ascending `round_seq`, a contract's approval steps are returned in ascending `step_seq`, and a contract's deposit installments are returned in ascending `installment_seq`.

        Design: Difficulty/non_linear_state_machine/proposal_negotiation_cycle_revisits_under_review
        """
        counters, _meta = validate_paginated(
            api_client.list_negotiation_counters(
                two_loop_negotiation["proposal_id"], PLANNER_HEADERS
            )
        )
        assert len(counters) == 2, f"expected exactly two counters, got {len(counters)}"
        domain_assert.assert_sequence(counters, "round_seq", [1, 2])


class TestExecutionJoinsFromTheApprovalSide:
    """A countersigned contract whose last approval is what completes execution."""

    def test_the_signature_dimension_finishes_first_and_waits(
        self, countersigned_then_approved
    ):
        """Before the final approval the two dimensions sit at different points.

        The two dimensions advance independently, and `EXECUTED` is the fork-join where they meet: it is reachable from either side, depending on which dimension finishes last.

        Design: Difficulty/non_linear_state_machine/contract_parallel_dimensions_join_from_approval_side
        """
        before = countersigned_then_approved["contract_before"]
        domain_assert.assert_fields_equal(
            before,
            {"signature_state": "COUNTERSIGNED", "approval_state": "IN_APPROVAL"},
        )
        domain_assert.assert_nulls(before, ["executed_at"])

    def test_the_final_decision_records_its_own_approver(
        self, countersigned_then_approved
    ):
        """The deciding identity is persisted on the step it decided.

        Both decisions persist `approver_user_id` from `X-User-ID` and stamp `decided_at` from the logical clock.

        Design: Difficulty/non_linear_state_machine/contract_parallel_dimensions_join_from_approval_side
        """
        final_step = countersigned_then_approved["final_step"]
        domain_assert.assert_fields_equal(
            final_step,
            {"decision": "APPROVED", "approver_user_id": APPROVER_ALT_USER_ID},
        )

    def test_the_top_step_closes_the_approval_dimension(
        self, countersigned_then_approved
    ):
        """Approving the highest step finishes internal authorisation.

        An `APPROVED` decision on the highest `step_seq` additionally moves the contract `approval_state` `IN_APPROVAL → APPROVED`.

        Design: Difficulty/non_linear_state_machine/contract_parallel_dimensions_join_from_approval_side
        """
        domain_assert.assert_fields_equal(
            countersigned_then_approved["contract"], {"approval_state": "APPROVED"}
        )

    def test_the_join_fires_from_the_approval_side(self, countersigned_then_approved):
        """With the countersignature already in, the last approval executes the contract.

        If at that moment `signature_state` is already `COUNTERSIGNED`, the contract immediately joins to `EXECUTED` in the same request, firing exactly the execution effects listed below.

        Design: Difficulty/non_linear_state_machine/contract_parallel_dimensions_join_from_approval_side
        """
        domain_assert.assert_fields_equal(
            countersigned_then_approved["contract"], {"signature_state": "EXECUTED"}
        )

    def test_execution_stamps_the_instant_from_the_clock(
        self, countersigned_then_approved
    ):
        """The execution instant comes from the logical clock, not the wall clock.

        `executed_at` is stamped from the logical clock.

        Design: Difficulty/non_linear_state_machine/contract_parallel_dimensions_join_from_approval_side
        """
        executed_at = countersigned_then_approved["contract"]["executed_at"]
        domain_assert.assert_iso_instant(executed_at, "executed_at")
        assert executed_at == CLOCK_SOURCING_WINDOW, (
            f"expected {CLOCK_SOURCING_WINDOW}, got {executed_at}"
        )

    def test_execution_blocks_the_contracted_room_nights(
        self, countersigned_then_approved
    ):
        """The venue's blocked inventory picks up the contracted block on execution.

        The venue's `blocked_room_nights` increases by the contract's `contracted_paid_room_nights`, restoring the room-night identity of section 2.10.

        Design: Difficulty/non_linear_state_machine/contract_parallel_dimensions_join_from_approval_side
        """
        domain_assert.assert_room_night_inventory(
            countersigned_then_approved["venue"], 587
        )

    def test_execution_awards_the_winning_shortlist_entry(
        self, countersigned_then_approved
    ):
        """The winning entry only reaches its awarded terminal state on execution.

        The awarded shortlist entry moves `RFP_ISSUED → AWARDED`, which is its second terminal state alongside `ELIMINATED`.

        Design: Difficulty/non_linear_state_machine/contract_parallel_dimensions_join_from_approval_side
        """
        domain_assert.assert_fields_equal(
            countersigned_then_approved["entry"], {"status": "AWARDED"}
        )

    def test_execution_moves_the_event_to_contracted(self, countersigned_then_approved):
        """The meeting event follows the contract into its contracted state.

        The event moves `AWARDED → CONTRACTED`.

        Design: Difficulty/non_linear_state_machine/contract_parallel_dimensions_join_from_approval_side
        """
        domain_assert.assert_fields_equal(
            countersigned_then_approved["event"], {"status": "CONTRACTED"}
        )

    def test_the_contract_carries_the_two_generated_control_steps(
        self, countersigned_then_approved
    ):
        """The routed chain is exactly the two steps the value required.

        The contract's `approval_step_count` is set to the number of steps generated, the contract moves `approval_state` `PENDING_ROUTING → IN_APPROVAL`, and its `version` advances by 1.

        Design: Difficulty/non_linear_state_machine/contract_parallel_dimensions_join_from_approval_side
        """
        domain_assert.assert_integer(
            countersigned_then_approved["contract"]["approval_step_count"],
            2,
            "approval_step_count",
        )


class TestAwardCascadeReachesTheLosingInspection:
    """One award closing out a bid, an entry and that entry's planned inspection."""

    def test_the_winning_bid_is_awarded(self, award_cascade_world):
        """The named bid leaves review as the awarded one.

        The named bid must belong to this event, and its `status` must be exactly `UNDER_REVIEW`; the bid moves `UNDER_REVIEW → AWARDED`.

        Design: Difficulty/transitive_cascade/award_cascade_four_hops_cancels_losing_venue_inspection
        """
        domain_assert.assert_fields_equal(
            award_cascade_world["winning_proposal"], {"status": "AWARDED"}
        )

    def test_the_contract_snapshots_the_winning_total_and_its_tier(
        self, award_cascade_world
    ):
        """The contract carries the quoted total and the tier that total earns.

        The rebate percentage is then chosen from that pre-rebate figure: a `pre_rebate_total_usd` below `150000.00` earns `volume_rebate_pct` of `0.000`; a `pre_rebate_total_usd` at or above `150000.00` but below `400000.00` earns `0.020`; and a `pre_rebate_total_usd` at or above `400000.00` earns `0.035`.

        Design: Difficulty/transitive_cascade/award_cascade_four_hops_cancels_losing_venue_inspection
        """
        contract = award_cascade_world["contract"]
        domain_assert.assert_money_field(contract, "pre_rebate_total_usd", 447844.84)
        assert contract["volume_rebate_pct"] == pytest.approx(0.035, abs=1e-9), (
            f"expected the 0.035 tier, got {contract['volume_rebate_pct']}"
        )

    def test_the_contract_deducts_the_rebate_from_the_quoted_total(
        self, award_cascade_world
    ):
        """The committed contract value is the quoted total net of the rebate.

        Then `volume_rebate_usd` is `pre_rebate_total_usd` multiplied by `volume_rebate_pct`, rounded to 2 decimal places, and `contracted_total_usd` is `pre_rebate_total_usd` minus `volume_rebate_usd`, rounded to 2 decimal places.

        Design: Difficulty/transitive_cascade/award_cascade_four_hops_cancels_losing_venue_inspection
        """
        contract = award_cascade_world["contract"]
        domain_assert.assert_money_field(contract, "volume_rebate_usd", 15674.57)
        domain_assert.assert_money_field(contract, "contracted_total_usd", 432170.27)

    def test_the_competing_bid_is_rejected(self, award_cascade_world):
        """The losing bid on the same round is closed out by the award.

        Every other bid on the same solicitation round whose `status` is `SUBMITTED`, `UNDER_REVIEW`, `COUNTERED` or `REVISED` moves to `REJECTED`.

        Design: Difficulty/transitive_cascade/award_cascade_four_hops_cancels_losing_venue_inspection
        """
        domain_assert.assert_fields_equal(
            award_cascade_world["losing_proposal"], {"status": "REJECTED"}
        )

    def test_the_rejected_bids_entry_is_eliminated_as_not_selected(
        self, award_cascade_world
    ):
        """The rejection carries on into the losing venue's shortlist entry.

        For each bid rejected at level 2, that bid's shortlist entry moves to `ELIMINATED` with `elimination_reason` set to `NOT_SELECTED`.

        Design: Difficulty/transitive_cascade/award_cascade_four_hops_cancels_losing_venue_inspection
        """
        domain_assert.assert_fields_equal(
            award_cascade_world["losing_entry"],
            {"status": "ELIMINATED", "elimination_reason": "NOT_SELECTED"},
        )

    def test_the_eliminated_entrys_planned_inspection_is_cancelled(
        self, award_cascade_world
    ):
        """The cascade reaches the site visit the losing venue had booked.

        For each shortlist entry eliminated at level 3, every site inspection on that entry whose `status` is `PLANNED` moves to `CANCELLED` with `cancel_reason` set to `SHORTLIST_ELIMINATED`.

        Design: Difficulty/transitive_cascade/award_cascade_four_hops_cancels_losing_venue_inspection
        """
        domain_assert.assert_fields_equal(
            award_cascade_world["cancelled_inspection"],
            {"status": "CANCELLED", "cancel_reason": "SHORTLIST_ELIMINATED"},
        )

    def test_the_cancelled_visit_drops_out_of_the_inspection_count(
        self, award_cascade_world
    ):
        """A cancelled inspection stops counting on its entry.

        The `inspection_count` field is maintained as the number of inspections on the entry whose `status` is `PLANNED` or `COMPLETED`.

        Design: Difficulty/transitive_cascade/award_cascade_four_hops_cancels_losing_venue_inspection
        """
        domain_assert.assert_integer(
            award_cascade_world["losing_entry"]["inspection_count"], 0, "inspection_count"
        )

    def test_the_emptied_entry_stays_eliminated(self, award_cascade_world):
        """Losing its last inspection does not revive the eliminated entry.

        Both `AWARDED` and `ELIMINATED` are terminal for a shortlist entry: there is no operation that revives an entry out of either.

        Design: Difficulty/transitive_cascade/award_cascade_four_hops_cancels_losing_venue_inspection
        """
        entry = validate_success(
            api_client.get_shortlist_entry(
                award_cascade_world["entry_b_id"], PLANNER_HEADERS
            )
        )
        domain_assert.assert_fields_equal(entry, {"status": "ELIMINATED"})

    def test_the_winning_entry_is_not_awarded_yet(self, award_cascade_world):
        """The winner's entry waits for execution before it turns awarded.

        The awarded shortlist entry moves `RFP_ISSUED → AWARDED`, which is its second terminal state alongside `ELIMINATED`.

        Design: Difficulty/transitive_cascade/award_cascade_four_hops_cancels_losing_venue_inspection
        """
        domain_assert.assert_fields_equal(
            award_cascade_world["winning_entry"], {"status": "RFP_ISSUED"}
        )

    def test_the_event_records_the_award_and_its_committed_money(
        self, award_cascade_world
    ):
        """The event points at the winning bid and books the committed spend.

        The event moves to `AWARDED`, its `awarded_proposal_id` is set to the winning bid, its `committed_spend_usd` is set to the contract's `contracted_total_usd`, its `budget_remaining_usd` is recomputed from the money identity in section 2.10, and its `version` advances by 1.

        Design: Difficulty/transitive_cascade/award_cascade_four_hops_cancels_losing_venue_inspection
        """
        event = award_cascade_world["event"]
        domain_assert.assert_fields_equal(
            event,
            {
                "status": "AWARDED",
                "awarded_proposal_id": award_cascade_world["proposal_id"],
            },
        )
        domain_assert.assert_money_field(event, "committed_spend_usd", 432170.27)
        domain_assert.assert_money_field(event, "budget_remaining_usd", 67829.73)
        domain_assert.assert_budget_envelope(event)

    def test_the_new_contract_starts_unrouted_and_unsigned(self, award_cascade_world):
        """Awarding mints the contract at the start of both dimensions.

        A new contract begins with `approval_state` `PENDING_ROUTING` and `signature_state` `UNSIGNED` — the two parallel dimensions described below — and with its money and signature fields empty: `deposit_total_usd` null, `deposit_paid_usd` `0.00`, `deposit_outstanding_usd` null, `approval_step_count` `0`, and `planner_signatory_name`, `venue_signatory_name`, `executed_at`, `terminated_at`, `cancellation_fee_usd`, `rebooking_credit_usd` and `termination_reason` all null.

        Design: Difficulty/transitive_cascade/award_cascade_four_hops_cancels_losing_venue_inspection
        """
        domain_assert.assert_fields_equal(
            award_cascade_world["contract"],
            {"approval_state": "PENDING_ROUTING", "signature_state": "UNSIGNED"},
        )

    def test_no_room_nights_are_blocked_before_execution(self, award_cascade_world):
        """The winning venue's inventory is untouched by the award alone.

        At every observable instant a venue's `blocked_room_nights` equals the sum of `contracted_paid_room_nights` over that venue's contracts whose `signature_state` is `EXECUTED`.

        Design: Difficulty/transitive_cascade/award_cascade_four_hops_cancels_losing_venue_inspection
        """
        domain_assert.assert_room_night_inventory(award_cascade_world["venue"], 0)


class TestApprovalRejectionUnwindsTheAward:
    """One rejected control step running backwards through the whole award."""

    def test_the_rejected_step_records_its_decider_and_the_instant(
        self, rejected_approval_world
    ):
        """A rejection is attributed and timestamped like any other decision.

        Both decisions persist `approver_user_id` from `X-User-ID` and stamp `decided_at` from the logical clock.

        Design: Difficulty/transitive_cascade/approval_rejection_cascade_three_hops_unwinds_award
        """
        step = rejected_approval_world["rejected_step"]
        domain_assert.assert_fields_equal(
            step, {"decision": "REJECTED", "approver_user_id": APPROVER_USER_ID}
        )
        assert step["decided_at"] == CLOCK_SOURCING_WINDOW, (
            f"expected {CLOCK_SOURCING_WINDOW}, got {step['decided_at']}"
        )

    def test_the_rejection_ends_the_approval_dimension(self, rejected_approval_world):
        """The contract's authorisation dimension terminates with the step.

        The step moves `PENDING → REJECTED` and the contract's `approval_state` moves `IN_APPROVAL → REJECTED`.

        Design: Difficulty/transitive_cascade/approval_rejection_cascade_three_hops_unwinds_award
        """
        domain_assert.assert_fields_equal(
            rejected_approval_world["contract"], {"approval_state": "REJECTED"}
        )

    def test_the_remaining_step_is_skipped(self, rejected_approval_world):
        """The higher control step is never decided at all.

        Every remaining step on the contract whose `decision` is still `PENDING` moves to `SKIPPED`, and the contract's `signature_state` moves to `VOIDED` — reachable from `UNSIGNED`, from `PLANNER_SIGNED` and from `COUNTERSIGNED` alike, so a rejection voids the contract no matter how far the signing ceremony had progressed.

        Design: Difficulty/transitive_cascade/approval_rejection_cascade_three_hops_unwinds_award
        """
        domain_assert.assert_fields_equal(
            rejected_approval_world["skipped_step"], {"decision": "SKIPPED"}
        )

    def test_a_skipped_step_names_nobody(self, rejected_approval_world):
        """The skipped step carries no approver and no decision instant.

        A `SKIPPED` step keeps `approver_user_id` and `decided_at` null: nobody decided it.

        Design: Difficulty/transitive_cascade/approval_rejection_cascade_three_hops_unwinds_award
        """
        domain_assert.assert_nulls(
            rejected_approval_world["skipped_step"], ["approver_user_id", "decided_at"]
        )

    def test_the_rejection_voids_the_planner_signed_contract(
        self, rejected_approval_world
    ):
        """A half-finished signing ceremony is voided by the rejection.

        Every remaining step on the contract whose `decision` is still `PENDING` moves to `SKIPPED`, and the contract's `signature_state` moves to `VOIDED` — reachable from `UNSIGNED`, from `PLANNER_SIGNED` and from `COUNTERSIGNED` alike, so a rejection voids the contract no matter how far the signing ceremony had progressed.

        Design: Difficulty/transitive_cascade/approval_rejection_cascade_three_hops_unwinds_award
        """
        domain_assert.assert_fields_equal(
            rejected_approval_world["contract"], {"signature_state": "VOIDED"}
        )

    def test_the_signature_already_given_is_preserved(self, rejected_approval_world):
        """Voiding the contract does not erase the planner's signature record.

        A `SourcingManager` signs by supplying `planner_signatory_name`, which is persisted on the contract.

        Design: Difficulty/transitive_cascade/approval_rejection_cascade_three_hops_unwinds_award
        """
        domain_assert.assert_fields_equal(
            rejected_approval_world["contract"], {"planner_signatory_name": "Anita Vale"}
        )

    def test_the_voided_contract_was_never_executed(self, rejected_approval_world):
        """No execution instant is ever stamped on a voided contract.

        A new contract begins with `approval_state` `PENDING_ROUTING` and `signature_state` `UNSIGNED` — the two parallel dimensions described below — and with its money and signature fields empty: `deposit_total_usd` null, `deposit_paid_usd` `0.00`, `deposit_outstanding_usd` null, `approval_step_count` `0`, and `planner_signatory_name`, `venue_signatory_name`, `executed_at`, `terminated_at`, `cancellation_fee_usd`, `rebooking_credit_usd` and `termination_reason` all null.

        Design: Difficulty/transitive_cascade/approval_rejection_cascade_three_hops_unwinds_award
        """
        domain_assert.assert_nulls(rejected_approval_world["contract"], ["executed_at"])

    def test_the_awarded_bid_returns_to_rejected(self, rejected_approval_world):
        """The bid that had won loses its award when the contract is voided.

        Because the contract is voided, the awarded bid returns to `REJECTED`, the event's `awarded_proposal_id` is cleared to null, its `committed_spend_usd` returns to `0.00` with `budget_remaining_usd` recomputed, and the event moves `AWARDED → BID_REVIEW` so the planner can award a different bid.

        Design: Difficulty/transitive_cascade/approval_rejection_cascade_three_hops_unwinds_award
        """
        domain_assert.assert_fields_equal(
            rejected_approval_world["proposal"], {"status": "REJECTED"}
        )

    def test_the_event_returns_to_bid_review_with_no_winner(
        self, rejected_approval_world
    ):
        """The event is handed back to the planner to award something else.

        Because the contract is voided, the awarded bid returns to `REJECTED`, the event's `awarded_proposal_id` is cleared to null, its `committed_spend_usd` returns to `0.00` with `budget_remaining_usd` recomputed, and the event moves `AWARDED → BID_REVIEW` so the planner can award a different bid.

        Design: Difficulty/transitive_cascade/approval_rejection_cascade_three_hops_unwinds_award
        """
        event = rejected_approval_world["event"]
        domain_assert.assert_fields_equal(event, {"status": "BID_REVIEW"})
        domain_assert.assert_nulls(event, ["awarded_proposal_id"])

    def test_the_committed_money_is_released_again(self, rejected_approval_world):
        """The voided contract's value is subtracted back out of committed spend.

        Superseding an award, or an approval rejection that voids the contract, subtracts the voided contract's `contracted_total_usd` again.

        Design: Difficulty/transitive_cascade/approval_rejection_cascade_three_hops_unwinds_award
        """
        domain_assert.assert_money_field(
            rejected_approval_world["event"], "committed_spend_usd", 0.00
        )

    def test_the_whole_budget_is_available_again(self, rejected_approval_world):
        """The money identity is restored with nothing committed and nothing liable.

        At every observable instant, and for every meeting event, the sum of `budget_remaining_usd`, `committed_spend_usd` and `cancellation_liability_usd` equals `budget_ceiling_usd` exactly.

        Design: Difficulty/transitive_cascade/approval_rejection_cascade_three_hops_unwinds_award
        """
        event = rejected_approval_world["event"]
        domain_assert.assert_money_field(event, "cancellation_liability_usd", 0.00)
        domain_assert.assert_money_field(event, "budget_remaining_usd", 500000.00)
        domain_assert.assert_budget_envelope(event)

    def test_the_shortlist_entry_never_reached_awarded(self, rejected_approval_world):
        """The entry is still solicited, because execution never happened.

        The awarded shortlist entry moves `RFP_ISSUED → AWARDED`, which is its second terminal state alongside `ELIMINATED`.

        Design: Difficulty/transitive_cascade/approval_rejection_cascade_three_hops_unwinds_award
        """
        domain_assert.assert_fields_equal(
            rejected_approval_world["entry"], {"status": "RFP_ISSUED"}
        )

    def test_no_room_nights_were_ever_blocked(self, rejected_approval_world):
        """The venue's inventory is untouched by an award that was voided.

        At every observable instant a venue's `blocked_room_nights` equals the sum of `contracted_paid_room_nights` over that venue's contracts whose `signature_state` is `EXECUTED`.

        Design: Difficulty/transitive_cascade/approval_rejection_cascade_three_hops_unwinds_award
        """
        domain_assert.assert_room_night_inventory(rejected_approval_world["venue"], 0)

    def test_no_deposit_schedule_was_ever_generated(self, rejected_approval_world):
        """A contract that never executed carries no installments.

        Once a contract is `EXECUTED`, a `FinanceController` generates its deposit schedule.

        Design: Difficulty/transitive_cascade/approval_rejection_cascade_three_hops_unwinds_award
        """
        installments, _meta = validate_paginated(
            api_client.list_deposit_installments(
                rejected_approval_world["contract_id"], FINANCE_HEADERS
            )
        )
        assert installments == [], f"expected no installments, got {installments}"
