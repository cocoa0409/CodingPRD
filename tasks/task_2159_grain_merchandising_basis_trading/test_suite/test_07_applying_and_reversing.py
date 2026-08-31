"""Applying, rejecting and reversing graded loads — including the settlement
cascade that a completing delivery drags behind it."""

import pytest

from test_helpers import (
    CLEAN_LOAD,
    TEST_WEIGHT_TIERS,
    ApiErrorId,
    apply_ticket,
    cancel_contract,
    read_contract,
    read_desk,
    read_position,
    read_ticket,
    reject_ticket,
    setup_graded_ticket_scenario,
    setup_settlement_ready,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS


MERCH = TEST_USERS["merchandiser_headers"]
INSPECTOR = TEST_USERS["grain_inspector_headers"]


class TestRejectingAndReversing:

    def test_rejecting_a_graded_load_moves_no_other_row(self, api):
        """PRD §3.8: "Rejecting a load is the simplest disposition and the least
        consequential. It requires only that the ticket be `GRADED`, refusing
        anything else with `ERR_TICKET_NOT_GRADED`, takes a `rejection_reason` which
        is stored on the ticket as `disposition_reason`, and moves the ticket
        `GRADED → REJECTED`. No contract field, no hedge position, no desk aggregate
        and no freight booking changes — the load is simply turned away."

        Design: Corner/state_machines/reject_graded_ticket_leaves_contract_bushels_untouched
        """
        scenario = setup_graded_ticket_scenario(
            desk_code="CD14", desk_name="Corner Desk 14", lots_open=10,
            contract_overrides={"contract_type": "CASH", "bushels": 20000},
            ticket_overrides={"gross_bushels": 5000, **CLEAN_LOAD},
        )

        rejected = validate_success(api.reject_delivery_ticket(
            scenario["ticket"]["id"], {"rejection_reason": "sour odour at the pit"},
            INSPECTOR,
        ), 200)

        assert rejected["status"] == "REJECTED"
        assert rejected["disposition_reason"] == "sour odour at the pit"
        assert rejected["net_bushels"] == pytest.approx(5000.00, abs=0.01), (
            "the grading results survive the rejection"
        )

        contract = read_contract(scenario["contract"]["id"])
        assert contract["delivered_bushels"] == pytest.approx(0.00, abs=0.01)
        assert contract["settled_value_usd"] == pytest.approx(0.00, abs=0.01)
        assert contract["delivery_status"] == "OPEN"
        assert read_desk(scenario["desk"]["id"])[
            "open_bushel_commitment"] == pytest.approx(20000.00, abs=0.01)

    def test_reversing_a_rejected_ticket_is_refused(self, api):
        """PRD §3.8: "Reversal undoes an application that should not have happened.
        It requires the ticket to be `APPLIED`, refusing anything else — including a
        merely `GRADED` ticket — with `ERR_TICKET_NOT_GRADED`, and it requires the
        contract to still be `ACTIVE`, refusing otherwise with
        `ERR_CONTRACT_NOT_ACTIVE`."

        Design: Corner/state_machines/reverse_a_rejected_ticket_is_rejected_with_ticket_not_graded
        """
        scenario = setup_graded_ticket_scenario(
            desk_code="CD15", desk_name="Corner Desk 15", lots_open=10,
            contract_overrides={"contract_type": "CASH", "bushels": 20000},
            ticket_overrides={"gross_bushels": 5000, **CLEAN_LOAD},
        )
        reject_ticket(scenario["ticket"]["id"], "sour odour at the pit")

        validate_error(api.reverse_delivery_ticket(
            scenario["ticket"]["id"], {"reversal_reason": "operator mistake"},
            INSPECTOR,
        ), ApiErrorId.ERR_TICKET_NOT_GRADED.value, 409)

        ticket = read_ticket(scenario["ticket"]["id"])
        assert ticket["status"] == "REJECTED"
        assert ticket["disposition_reason"] == "sour odour at the pit"
        assert read_contract(scenario["contract"]["id"])["status"] == "ACTIVE", (
            "the contract stays ACTIVE so no earlier ladder row can mask the "
            "ticket-state check"
        )

    def test_a_load_larger_than_the_undelivered_balance_is_refused(self, api):
        """PRD §3.8: "The ticket's `net_bushels` must fit inside what the contract
        still has coming — that is, at most the contract's `bushels` less its
        `delivered_bushels` — with an over-large load refused as
        `ERR_BUSHELS_EXCEEDED`."

        Design: Corner/validations/applying_a_ticket_over_the_remaining_balance_returns_bushels_exceeded
        """
        scenario = setup_graded_ticket_scenario(
            desk_code="CD38", desk_name="Corner Desk 38", lots_open=10,
            schedule_tiers=TEST_WEIGHT_TIERS,
            contract_overrides={"contract_type": "CASH", "bushels": 10000},
            ticket_overrides={"gross_bushels": 15000, **CLEAN_LOAD},
        )

        validate_error(api.apply_delivery_ticket(scenario["ticket"]["id"], MERCH),
                       ApiErrorId.ERR_BUSHELS_EXCEEDED.value, 422)

        ticket = read_ticket(scenario["ticket"]["id"])
        assert ticket["status"] == "GRADED"
        assert ticket["net_bushels"] == pytest.approx(15000.00, abs=0.01)

        contract = read_contract(scenario["contract"]["id"])
        assert contract["delivered_bushels"] == pytest.approx(0.00, abs=0.01)
        assert contract["delivery_status"] == "OPEN"


class TestSettlementCascade:
    """Applying the final load settles the contract, lifts the hedge lots and
    forces the desk recompute."""

    def test_the_completing_load_settles_the_contract(self, api):
        """PRD §3.8: "On success the contract's `delivered_bushels` grows by the
        ticket's `net_bushels` and its `settled_value_usd` grows by the ticket's
        `settlement_value_usd`, where a null settlement value is treated as zero."
        PRD §3.8: "Settlement is the consequence, not a separate request. A contract
        whose `delivery_status` has reached `COMPLETE` while its `pricing_status` is
        `FULLY_PRICED` transitions `ACTIVE → SETTLED` on the spot, and that
        transition carries the deep cascade."

        Design: Difficulty/transitive_cascade/delivery_apply_settles_contract_lifts_hedge_recomputes_desk
        """
        scenario = setup_settlement_ready(
            desk_code="GD9", credit_line_usd=100000.00, lots_open=2,
            contract_bushels=10000, gross_bushels=10000,
        )

        applied = validate_success(
            api.apply_delivery_ticket(scenario["ticket"]["id"], MERCH), 200
        )
        assert applied["status"] == "APPLIED"

        contract = read_contract(scenario["contract"]["id"])
        assert contract["delivered_bushels"] == pytest.approx(10000.00, abs=0.01)
        assert contract["delivery_status"] == "COMPLETE"
        assert contract["settled_value_usd"] == pytest.approx(41300.00, abs=0.01), (
            f"10,000 bushels at 413 cents net of the 3.0 cent fee = 41,300.00, got "
            f"{contract['settled_value_usd']}"
        )
        assert contract["status"] == "SETTLED"

    def test_settlement_lifts_the_hedge_and_recomputes_the_desk(self, api):
        """PRD §3.8: "The hedge lots the contract had reserved are lifted from its
        position: `lots_open` on the position decreases by the contract's
        `hedge_lots_assigned`, the position's committed lot count is recomputed, its
        `realized_pnl_usd` grows by the side sign multiplied by the difference
        between the position's `last_settlement_price_cents` and its
        `avg_entry_price_cents`, multiplied by the lifted lot count, multiplied by
        5,000 bushels per lot, divided by 100, rounded half-up to 2 decimal places;
        and its `posted_margin_usd` decreases by the lifted lot count multiplied by
        the commodity's per-lot initial margin."
        PRD §3.8: "Because open lots and posted margin both moved, the desk's
        `margin_requirement_usd`, `committed_hedge_lots`, `open_bushel_commitment`,
        `unpriced_bushels`, `available_credit_usd`, `credit_utilization`,
        `realized_hedge_pnl_usd` and `posture` are all recomputed; and if that
        recomputation pulls the desk out of `FROZEN`, `pricing_locked` is set back
        to false on every `ACTIVE` contract of the desk."

        Design: Difficulty/transitive_cascade/delivery_apply_settles_contract_lifts_hedge_recomputes_desk
        """
        scenario = setup_settlement_ready(
            desk_code="GD9", credit_line_usd=100000.00, lots_open=2,
            contract_bushels=10000, gross_bushels=10000,
        )
        apply_ticket(scenario["ticket"]["id"])

        position = read_position(scenario["position"]["id"])
        assert position["lots_open"] == 0, (
            f"both reserved lots are lifted off the board, got "
            f"{position['lots_open']}"
        )
        assert position["lots_committed"] == 0
        assert position["posted_margin_usd"] == pytest.approx(0.00, abs=0.01)
        assert position["realized_pnl_usd"] == pytest.approx(0.00, abs=0.01), (
            "an unmarked position settles at its own entry price, booking nothing"
        )

        desk = read_desk(scenario["desk"]["id"])
        assert desk["margin_requirement_usd"] == pytest.approx(0.00, abs=0.01)
        assert desk["committed_hedge_lots"] == 0
        assert desk["open_bushel_commitment"] == pytest.approx(0.00, abs=0.01)
        assert desk["available_credit_usd"] == pytest.approx(100000.00, abs=0.01)
        assert desk["credit_utilization"] == pytest.approx(0.0000, abs=0.0001)
        assert desk["posture"] == "NORMAL"


class TestContractStatePrecedesBushelCeiling:
    """An apply request that is both aimed at a terminated contract and larger
    than its balance reports the earlier ladder row (rank 9)."""

    def _cancelled_with_oversized_ticket(self):
        scenario = setup_graded_ticket_scenario(
            desk_code="GD11", desk_name="Ladder A Desk", lots_open=10,
            contract_overrides={"contract_type": "CASH", "bushels": 10000},
            ticket_overrides={"gross_bushels": 15000, **CLEAN_LOAD},
        )
        cancel_contract(scenario["contract"]["id"], damages_method="MARKET_LOSS",
                        cancellation_reason="producer walked")
        return scenario

    def test_the_terminated_contract_is_reported_over_the_bushel_ceiling(self, api):
        """PRD §2.8: "Every request is screened by an ordered sequence of checks,
        and **the first check that fails decides the response**."
        PRD §3.8: "The contract must be `ACTIVE`, or `ERR_CONTRACT_NOT_ACTIVE`
        answers."
        PRD §3.8: "The ticket's `net_bushels` must fit inside what the contract
        still has coming — that is, at most the contract's `bushels` less its
        `delivered_bushels` — with an over-large load refused as
        `ERR_BUSHELS_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_apply_to_cancelled_contract
        """
        scenario = self._cancelled_with_oversized_ticket()

        resp = api.apply_delivery_ticket(scenario["ticket"]["id"], MERCH)
        error = validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, 409)

        assert resp.status_code == 409, (
            f"the priority-9 state rule answers at 409, not the priority-36 fiscal "
            f"rule at 422; got {resp.status_code}"
        )
        assert error["error_id"] != ApiErrorId.ERR_BUSHELS_EXCEEDED.value

    def test_the_refused_apply_leaves_the_ticket_and_contract_untouched(self, api):
        """PRD §3.8: "Applying a ticket moves it `GRADED → APPLIED` and requires
        four things."
        PRD §3.8: "On success the contract's `delivered_bushels` grows by the
        ticket's `net_bushels` and its `settled_value_usd` grows by the ticket's
        `settlement_value_usd`, where a null settlement value is treated as zero."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_apply_to_cancelled_contract
        """
        scenario = self._cancelled_with_oversized_ticket()

        validate_error(api.apply_delivery_ticket(scenario["ticket"]["id"], MERCH),
                       ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, 409)

        assert read_ticket(scenario["ticket"]["id"])["status"] == "GRADED"
        contract = read_contract(scenario["contract"]["id"])
        assert contract["delivered_bushels"] == pytest.approx(0.00, abs=0.01)
        assert contract["status"] == "CANCELLED"


class TestBushelCommitmentIsConserved:
    """Applying a load lowers the desk's open bushel commitment and reversing
    that load restores it exactly."""

    def _invariant_scenario(self):
        return setup_graded_ticket_scenario(
            desk_code="GD22", desk_name="Bushel Invariant Desk", lots_open=10,
            contract_overrides={"contract_type": "CASH", "bushels": 50000,
                                "settlement_basis": "SHRINK_FIRST"},
            ticket_overrides={"gross_bushels": 10000, **CLEAN_LOAD},
        )

    def test_applying_a_load_lowers_the_open_bushel_commitment(self, api):
        """PRD §2.9: "`open_bushel_commitment` is the sum, over the desk's purchase
        contracts whose `status` is `ACTIVE`, of contracted bushels less delivered
        bushels, and it is the conserved quantity behind the delivery
        apply-and-reverse invariant."
        PRD §3.8: "On success the contract's `delivered_bushels` grows by the
        ticket's `net_bushels` and its `settled_value_usd` grows by the ticket's
        `settlement_value_usd`, where a null settlement value is treated as zero."

        Design: Difficulty/compensating_invariant/open_bushel_commitment_conserved_by_ticket_apply_then_reverse
        """
        scenario = self._invariant_scenario()
        before = read_desk(scenario["desk"]["id"])["open_bushel_commitment"]
        assert before == pytest.approx(50000.00, abs=0.01)

        apply_ticket(scenario["ticket"]["id"])

        assert read_desk(scenario["desk"]["id"])[
            "open_bushel_commitment"] == pytest.approx(40000.00, abs=0.01), (
            "50,000 contracted less the 10,000 just delivered"
        )
        assert read_contract(scenario["contract"]["id"])[
            "settled_value_usd"] == pytest.approx(41300.00, abs=0.01)

    def test_reversing_that_load_restores_every_figure_exactly(self, api):
        """PRD §3.8: "The compensation is exact and symmetric: the contract's
        `delivered_bushels` shrinks by the ticket's `net_bushels`, its
        `settled_value_usd` shrinks by the ticket's `settlement_value_usd` (again
        treating null as zero), `delivery_status` is re-derived from the reduced
        figure, and the desk's `open_bushel_commitment` returns to precisely the
        value it held before the application."
        PRD §3.8: "What is *not* undone is the grading itself: `shrink_pct`,
        `net_bushels`, `discount_total_usd`, `gross_contract_value_usd`,
        `service_fee_cents_per_bushel`, `net_unit_price_cents`,
        `settlement_value_usd` and `discount_schedule_id` all remain on the reversed
        ticket exactly as they were computed at the scale."

        Design: Difficulty/compensating_invariant/open_bushel_commitment_conserved_by_ticket_apply_then_reverse
        """
        scenario = self._invariant_scenario()
        apply_ticket(scenario["ticket"]["id"])

        reversed_ticket = validate_success(api.reverse_delivery_ticket(
            scenario["ticket"]["id"],
            {"reversal_reason": "scale ticket voided by the state inspector"},
            INSPECTOR,
        ), 200)

        assert read_desk(scenario["desk"]["id"])[
            "open_bushel_commitment"] == pytest.approx(50000.00, abs=0.01), (
            "the commitment returns to precisely its pre-apply reading"
        )
        contract = read_contract(scenario["contract"]["id"])
        assert contract["delivered_bushels"] == pytest.approx(0.00, abs=0.01)
        assert contract["settled_value_usd"] == pytest.approx(0.00, abs=0.01)
        assert contract["delivery_status"] == "OPEN"
        assert contract["status"] == "ACTIVE"

        assert reversed_ticket["status"] == "REVERSED"
        assert reversed_ticket["net_bushels"] == pytest.approx(10000.00, abs=0.01), (
            "the grading itself is not undone"
        )
        assert reversed_ticket["settlement_value_usd"] == pytest.approx(
            41300.00, abs=0.01
        )
