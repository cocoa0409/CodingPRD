"""Unwinds: the void cascade, the eligibility re-pend cascade, and the conservation
invariants a compensating operation must restore."""
import pytest

from test_helpers import (
    adjudicate,
    claim_line_payload,
    create_adjustment,
    get_accumulator,
    get_authorization,
    get_claim,
    get_claim_lines,
    get_events,
    get_member,
    get_remittances,
    lines_by_number,
    setup_coverage_termination_cascade_ready,
    setup_finalized_claim_holding_four_units,
    setup_seeded_accumulator_finalized_claim,
    setup_void_cascade_ready_claim,
    terminate_coverage,
    void_claim,
)


class TestVoidCascade:
    def test_void_flips_the_claim_its_payment_and_its_remittance(self, api):
        """PRD §3.9: "First, the claim moves `FINALIZED → VOIDED`, which is terminal.
        Second, because the claim voided, its `payment_status` flips `REMITTED → REVERSED`."
        PRD §3.9: "Third, because the payment reversed, every remittance advice of that
        claim standing at `ISSUED` flips `ISSUED → VOIDED`, and the accumulator deltas those
        remittances posted are taken back: the claim's `total_deductible_applied_cents` is
        subtracted from the accumulator's `deductible_applied_cents`, the claim's
        `total_member_liability_cents` is subtracted from its `oop_applied_cents`, and
        `remitted_claim_count` decreases by one."

        Design: Difficulty/transitive_cascade/void_cascade_reverses_remittance_accumulator_lines_and_auth_units
        """
        env = setup_void_cascade_ready_claim()
        before = env["accumulator_after_finalize"]
        assert before["deductible_applied_cents"] == 50000
        assert before["oop_applied_cents"] == 52000

        voided = void_claim(env["claim"]["id"], "VOID_BILLING_ERROR")
        assert voided["status"] == "VOIDED"
        assert voided["payment_status"] == "REVERSED"

        remittances = get_remittances(env["claim"]["id"])
        assert len(remittances) == 1
        assert remittances[0]["status"] == "VOIDED"

        after = get_accumulator(env["member"]["id"])
        assert after["deductible_applied_cents"] == 0
        assert after["oop_applied_cents"] == 0
        assert after["remitted_claim_count"] == 0

    def test_void_reverses_the_paid_line_and_releases_its_authorization_units(self, api):
        """PRD §3.9: "Fourth, because the remittance voided, every service line standing at
        `PAID` flips `PAID → REVERSED`."
        PRD §3.9: "Fifth, because a line reversed, the authorization it was linked to has
        its `units_consumed` reduced by that line's `units`."
        PRD §3.9: "Sixth, because `units_consumed` moved, the authorization's `status` is
        re-derived: `EXHAUSTED → PARTIALLY_CONSUMED` when consumption now sits strictly
        between zero and `authorized_units`, and `PARTIALLY_CONSUMED → ACTIVE` when
        consumption reaches zero."

        Design: Difficulty/transitive_cascade/void_cascade_reverses_remittance_accumulator_lines_and_auth_units
        """
        env = setup_void_cascade_ready_claim()
        void_claim(env["claim"]["id"], "VOID_BILLING_ERROR")

        lines = get_claim_lines(env["claim"]["id"])
        assert len(lines) == 1
        assert lines[0]["line_status"] == "REVERSED"

        authorization = get_authorization(env["authorization"]["id"])
        assert authorization["units_consumed"] == 0
        assert authorization["status"] == "ACTIVE", (
            "Reversing every consuming line takes the grant all the way back to ACTIVE"
        )


class TestEligibilityRepandCascade:
    def test_terminating_coverage_repends_the_claim_it_matched(self, api):
        """PRD §3.2: "First, the segment's `status` becomes `TERMINATED` and its `term_date`
        is set to the supplied date."
        PRD §3.2: "Second, **because** the coverage terminated, every claim matched to this
        coverage segment whose `status` is `RECEIVED`, `PENDED` or `ADJUDICATED` and whose
        `statement_from_date` falls on or after the new `term_date` moves to `PENDED` with
        `pend_reason_code` set to `PEND_ELIG_REVIEW`."
        PRD §3.2: "An adjudication event of type `ELIG_REPEND` is appended to every
        re-pended claim."

        Design: Difficulty/transitive_cascade/coverage_termination_repends_claim_lines_and_releases_auth_units
        """
        env = setup_coverage_termination_cascade_ready()
        assert env["claim_before"]["status"] == "ADJUDICATED"
        assert env["claim_before"]["total_allowed_cents"] == 160000

        coverage = terminate_coverage(env["coverage"]["id"], "2026-04-01")
        assert coverage["status"] == "TERMINATED"
        assert coverage["term_date"] == "2026-04-01"

        claim = get_claim(env["claim"]["id"])
        assert claim["status"] == "PENDED"
        assert claim["pend_reason_code"] == "PEND_ELIG_REVIEW"

        event_types = [event["event_type"] for event in get_events(env["claim"]["id"])]
        assert "ELIG_REPEND" in event_types

    def test_repended_lines_zero_their_money_and_hand_back_authorization_units(self, api):
        """PRD §3.2: "Third, **because** those claims moved to `PENDED`, each of their
        service lines standing at `PRICED` flips `PRICED → PENDED`, has its
        `edit_reason_code` stamped `PEND_ELIG_REVIEW`, has every per-line money field zeroed,
        and releases the units it was holding back to its linked authorization."
        PRD §3.2: "Fourth, **because** `units_consumed` decreased on those authorizations,
        each authorization's `status` is re-derived — `EXHAUSTED → PARTIALLY_CONSUMED` when
        consumption sits strictly between zero and the grant, and `PARTIALLY_CONSUMED →
        ACTIVE` when consumption reaches zero."
        PRD §3.2: "Fifth, as a separate direct effect of the termination, the member's
        `status` becomes `TERMINATED` when no remaining coverage segment of that member
        contains the current logical clock date."

        Design: Difficulty/transitive_cascade/coverage_termination_repends_claim_lines_and_releases_auth_units
        """
        env = setup_coverage_termination_cascade_ready()
        terminate_coverage(env["coverage"]["id"], "2026-04-01")

        line = lines_by_number(env["claim"]["id"])[1]
        assert line["line_status"] == "PENDED"
        assert line["edit_reason_code"] == "PEND_ELIG_REVIEW"
        assert line["allowed_amount_cents"] == 0
        assert line["member_liability_cents"] == 0
        assert line["plan_paid_cents"] == 0

        authorization = get_authorization(env["authorization"]["id"])
        assert authorization["units_consumed"] == 0
        assert authorization["status"] == "ACTIVE"

        member = get_member(env["member"]["id"])
        assert member["status"] == "TERMINATED", (
            "No remaining segment contains the 2026-05-01 logical clock date"
        )


class TestAccumulatorDollarConservation:
    def test_finalize_posts_the_claim_deltas_onto_the_seeded_accumulator(self, api):
        """PRD §3.9: "The claim's `total_deductible_applied_cents` is added to the member's
        `deductible_applied_cents` and its `total_member_liability_cents` to the member's
        `oop_applied_cents`, on the benefit accumulator for that member and the calendar
        year of the earliest `service_date` on the claim — creating that accumulator row if
        the year has none yet — and `remitted_claim_count` increases by one."
        PRD §3.2: "A `PlanAdmin` posts a correction by supplying `deductible_delta_cents`
        and `oop_delta_cents` — signed values, added respectively to
        `deductible_applied_cents` and `oop_applied_cents` — an optional free-text `note`,
        and the `expected_accumulator_version` guard described in §2.7."

        Design: Difficulty/compensating_invariant/finalize_then_void_conserves_member_accumulator_dollars
        """
        env = setup_seeded_accumulator_finalized_claim()
        assert env["accumulator_baseline"]["deductible_applied_cents"] == 12000
        assert env["accumulator_baseline"]["oop_applied_cents"] == 15000
        assert env["adjudicated_claim"]["total_deductible_applied_cents"] == 38000
        assert env["adjudicated_claim"]["total_member_liability_cents"] == 38400

        after_finalize = env["accumulator_after_finalize"]
        assert after_finalize["deductible_applied_cents"] == 50000
        assert after_finalize["oop_applied_cents"] == 53400
        assert after_finalize["remitted_claim_count"] == 1

    def test_the_compensating_void_returns_the_accumulator_to_its_seeded_baseline(self, api):
        """PRD §2.9: "It follows that unwinding a finalized claim must move all four back,
        in a fixed cascade, and that the cascade is not optional or partial: after a void,
        the member's accumulator, the authorization's consumed units and the derived
        authorization status must all read exactly as they did before the finalization."
        PRD §3.9: "Third, because the payment reversed, every remittance advice of that
        claim standing at `ISSUED` flips `ISSUED → VOIDED`, and the accumulator deltas those
        remittances posted are taken back: the claim's `total_deductible_applied_cents` is
        subtracted from the accumulator's `deductible_applied_cents`, the claim's
        `total_member_liability_cents` is subtracted from its `oop_applied_cents`, and
        `remitted_claim_count` decreases by one."

        Design: Difficulty/compensating_invariant/finalize_then_void_conserves_member_accumulator_dollars
        """
        env = setup_seeded_accumulator_finalized_claim()
        void_claim(env["claim"]["id"], "VOID_DUPLICATE_PAYMENT")

        accumulator = get_accumulator(env["member"]["id"])
        assert accumulator["deductible_applied_cents"] == 12000, (
            "The seeded deductible baseline must come back exactly"
        )
        assert accumulator["oop_applied_cents"] == 15000
        assert accumulator["remitted_claim_count"] == 0


class TestAuthorizationUnitConservation:
    def test_creating_an_adjustment_reverses_the_original_and_releases_every_unit(self, api):
        """PRD §3.9: "On the original claim the cascade is identical to the void cascade in
        hops one through five: the original moves `FINALIZED → ADJUSTED` (terminal),
        `payment_status` flips `REMITTED → REVERSED`, the `ISSUED` remittance advices flip to
        `VOIDED` and their accumulator deltas are subtracted exactly as a void subtracts
        them, and the `PAID` lines flip to `REVERSED`, releasing their authorization units
        and re-deriving each authorization's `status`."

        Design: Difficulty/compensating_invariant/adjustment_cycle_conserves_authorization_units
        """
        env = setup_finalized_claim_holding_four_units()
        before = env["authorization_before"]
        assert before["units_consumed"] == 4
        assert before["status"] == "PARTIALLY_CONSUMED"

        create_adjustment(
            env["claim"]["id"],
            "CLM-INV-2-A1",
            [claim_line_payload(1, "73721", 2, 100000, "2026-02-10")],
            adjustment_reason_code="ADJ_UNITS_CORRECTION",
        )

        original = get_claim(env["claim"]["id"])
        assert original["status"] == "ADJUSTED"
        assert original["payment_status"] == "REVERSED"
        original_lines = get_claim_lines(env["claim"]["id"])
        assert len(original_lines) == 1
        assert original_lines[0]["line_status"] == "REVERSED"

        released = get_authorization(env["authorization"]["id"])
        assert released["units_consumed"] == 0
        assert released["status"] == "ACTIVE"

    def test_the_replacement_claim_reconsumes_only_the_units_it_bills(self, api):
        """PRD §3.9: "A **new** claim is then created and returned: its `claim_type` is
        `ADJUSTMENT`, its `original_claim_id` names the claim it replaces, its `status` is
        `RECEIVED`, its `payment_status` is `NOT_REMITTED`, and it holds the submitted
        replacement lines."
        PRD §3.6: "4. Otherwise the line moves `PENDING → PRICED`, its `authorization_id`
        records the selected grant, and that grant's `units_consumed` increases by the line's
        `units`, after which the grant's `status` is re-derived."

        Design: Difficulty/compensating_invariant/adjustment_cycle_conserves_authorization_units
        """
        env = setup_finalized_claim_holding_four_units()
        replacement = create_adjustment(
            env["claim"]["id"],
            "CLM-INV-2-A1",
            [claim_line_payload(1, "73721", 2, 100000, "2026-02-10")],
            adjustment_reason_code="ADJ_UNITS_CORRECTION",
        )
        assert replacement["claim_type"] == "ADJUSTMENT"
        assert replacement["original_claim_id"] == env["claim"]["id"]
        assert replacement["status"] == "RECEIVED"
        assert replacement["payment_status"] == "NOT_REMITTED"

        readjudicated = adjudicate(replacement["id"])
        assert readjudicated["total_allowed_cents"] == 80000

        authorization = get_authorization(env["authorization"]["id"])
        assert authorization["units_consumed"] == 2, (
            "Only the replacement's two units are held after the cycle"
        )
        assert authorization["status"] == "PARTIALLY_CONSUMED"
