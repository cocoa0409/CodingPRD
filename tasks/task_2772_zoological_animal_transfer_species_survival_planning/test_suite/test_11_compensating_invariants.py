"""The two system-wide invariants survive an execute and its compensating terminate."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money, assert_slot_counts


def _slot_sum(world) -> int:
    sender = world.read_institution(world.sender_id)
    receiver = world.read_institution(world.receiver_id)
    return sum(row["occupied_slots"] + row["reserved_slots"]
               for row in (sender, receiver))


def _balance_sum(world) -> float:
    sender = world.read_institution(world.sender_id)
    receiver = world.read_institution(world.receiver_id)
    return round(float(sender["transfer_credit_balance"])
                 + float(receiver["transfer_credit_balance"]), 2)


def _terminate(world, reason):
    return validate_success(
        world.api.terminate_agreement(world.ta_id, world.sender,
                                      f.termination_payload(reason=reason))
    )


class TestSlotConservation:
    """Slot counts are recomputed, so a compensated cycle leaves no drift."""

    def test_execution_moves_the_slot_from_sender_to_receiver(self, api):
        """The sender's occupied count falls and the receiver's reserved count rises.

        PRD: "The animal's `location_status` moves from `HELD` to `RESERVED`. The
        sending institution's `occupied_slots` therefore drops by one and the
        receiving institution's `reserved_slots` rises by one, and both
        institutions' slot counts are recomputed."

        Design: Difficulty/compensating_invariant/slot_conservation_across_execute_and_terminate
        """
        world = fx.world_with_accepted_agreement(api)
        assert_slot_counts(world.read_institution(world.sender_id), 1, 0)
        assert_slot_counts(world.read_institution(world.receiver_id), 1, 0)
        assert _slot_sum(world) == 2

        fx.executed_agreement(world)
        assert_slot_counts(world.read_institution(world.sender_id), 0, 0)
        assert_slot_counts(world.read_institution(world.receiver_id), 1, 1)
        assert _slot_sum(world) == 2
        animal = world.read_animal()
        assert animal["location_status"] == "RESERVED"
        assert animal["owning_institution_id"] == world.receiver_id

    def test_termination_restores_every_slot_count_without_drift(self, api):
        """The invariant sum is 2 again and the sender holds its animal once more.

        PRD: "summing `occupied_slots` and `reserved_slots` across all
        institutions equals the number of animals whose `location_status` is
        anything other than `DISPOSED`"

        Design: Difficulty/compensating_invariant/slot_conservation_across_execute_and_terminate
        """
        world = fx.world_with_executed_agreement(api)
        reason = "Receiving institution withdrew the holding space"
        terminated = _terminate(world, reason)
        assert terminated["status"] == "TERMINATED"
        assert terminated["termination_reason"] == reason

        assert_slot_counts(world.read_institution(world.sender_id), 1, 0)
        assert_slot_counts(world.read_institution(world.receiver_id), 1, 0)
        assert _slot_sum(world) == 2
        animal = world.read_animal()
        assert animal["location_status"] == "HELD"
        assert animal["holding_institution_id"] == world.sender_id
        assert animal["owning_institution_id"] == world.sender_id

    def test_the_reopened_directive_returns_to_the_open_set(self, api):
        """The recommendation is pulled back to ENDORSED and the cycle reopens.

        PRD: "Because that recommendation has re-entered the open set, the
        programme's `open_recommendation_count` is recomputed, and a programme
        sitting at `CYCLE_CLOSED` reopens to `PUBLISHED` with `cycle_closed_on`
        cleared to null."

        Design: Difficulty/compensating_invariant/slot_conservation_across_execute_and_terminate
        """
        world = fx.world_with_executed_agreement(api)
        assert world.read_program()["plan_status"] == "CYCLE_CLOSED"
        _terminate(world, "Receiving institution withdrew the holding space")

        assert world.read_recommendation()["status"] == "ENDORSED"
        assert world.read_animal()["pending_recommendation_id"] == world.rec_id
        program = world.read_program()
        assert program["plan_status"] == "PUBLISHED"
        assert program["open_recommendation_count"] == 1
        assert program["cycle_closed_on"] is None


class TestCreditLedgerZeroSum:
    """Every posting is double-entry, so the signed balances always sum to zero."""

    def test_execution_posts_the_provisional_value_to_both_parties(self, api):
        """The sender is credited 62.23 and the receiver debited the same amount.

        PRD: "Execution adds `provisional_credit_points` to the sending
        institution's balance and subtracts the same amount from the receiving
        institution's balance — the sender is credited for giving up the animal,
        the receiver debited for gaining it."

        Design: Difficulty/compensating_invariant/credit_ledger_zero_sum_across_execute_and_terminate
        """
        world = fx.world_with_accepted_agreement(api)
        assert_money(world.read_institution(world.sender_id)
                     ["transfer_credit_balance"], 0.00, "sender balance")
        assert_money(world.read_institution(world.receiver_id)
                     ["transfer_credit_balance"], 0.00, "receiver balance")

        executed = fx.executed_agreement(world)
        assert_money(executed["provisional_credit_points"], 62.23,
                     "provisional_credit_points")
        assert executed["final_credit_points"] is None
        assert_money(world.read_institution(world.sender_id)
                     ["transfer_credit_balance"], 62.23, "sender balance")
        assert_money(world.read_institution(world.receiver_id)
                     ["transfer_credit_balance"], -62.23, "receiver balance")
        assert _balance_sum(world) == 0.00

    def test_termination_reverses_the_ledger_leaving_no_residue(self, api):
        """Both balances return to 0.00 and the system-wide sum is exactly 0.00.

        PRD: "That net is subtracted from the sending institution's
        `transfer_credit_balance` and added back to the receiving institution's,
        returning both balances to their pre-execution values."

        Design: Difficulty/compensating_invariant/credit_ledger_zero_sum_across_execute_and_terminate
        """
        world = fx.world_with_executed_agreement(api)
        terminated = _terminate(world, "Import permit revoked by the "
                                       "destination authority")
        assert terminated["status"] == "TERMINATED"
        assert_money(world.read_institution(world.sender_id)
                     ["transfer_credit_balance"], 0.00, "sender balance")
        assert_money(world.read_institution(world.receiver_id)
                     ["transfer_credit_balance"], 0.00, "receiver balance")
        assert _balance_sum(world) == 0.00

    def test_the_recorded_valuation_survives_the_reversal(self, api):
        """The agreement still carries 62.23 provisional and a null final value.

        PRD: "The reversal never recomputes the valuation, so neither a birthday
        nor a temperature record falling between execution and termination can
        leave residue behind."

        Design: Difficulty/compensating_invariant/credit_ledger_zero_sum_across_execute_and_terminate
        """
        world = fx.world_with_executed_agreement(api)
        _terminate(world, "Import permit revoked by the destination authority")
        agreement = world.read_agreement()
        assert_money(agreement["provisional_credit_points"], 62.23,
                     "provisional_credit_points")
        assert agreement["final_credit_points"] is None
        assert agreement["status"] == "TERMINATED"
