"""Transfer credit valuation: provisional at execution, final at delivery."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_success
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money


class TestProvisionalVersusFinalCreditPoints:
    """The same agreement is valued twice and the ledger moves by the delta."""

    def test_execution_stores_the_provisional_valuation_only(self, api):
        """Execution stores 62.23 provisionally and leaves the final figure null.

        PRD: "At execution the valuation stops there and the result is stored as
        `provisional_credit_points`. No transport penalty is applied, because no
        temperature record exists yet."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_transfer_credit_points
        """
        world = fx.world_with_executed_agreement(api)
        agreement = world.read_agreement()
        assert_money(agreement["provisional_credit_points"], 62.23,
                     "provisional_credit_points")
        assert agreement["final_credit_points"] is None
        assert_money(world.read_institution(world.sender_id)["transfer_credit_balance"],
                     62.23, "sender transfer_credit_balance")
        assert_money(world.read_institution(world.receiver_id)["transfer_credit_balance"],
                     -62.23, "receiver transfer_credit_balance")

    def test_delivery_revalues_downward_by_the_thermal_penalty(self, api):
        """Four out-of-envelope readings cost 120 minutes and 6.00 points.

        PRD: "And a thermal penalty is subtracted: `thermal_excursion_minutes`
        multiplied by 0.05 points per minute, rounded half up to two decimal
        places, is taken off the credit points, and the result — rounded half up
        to two decimal places and floored at 0.00, never negative — is stored as
        `final_credit_points`."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_transfer_credit_points
        """
        world = fx.world_delivered(
            api, temperature_samples=[12.0, 26.0, 27.0, 25.0, 26.0, 14.0, 15.0]
        )
        booking = world.read_booking()
        assert booking["thermal_excursion_minutes"] == 120
        agreement = world.read_agreement()
        assert_money(agreement["provisional_credit_points"], 62.23,
                     "provisional_credit_points")
        assert_money(agreement["final_credit_points"], 56.23,
                     "final_credit_points")
        assert float(agreement["provisional_credit_points"]) != \
            float(agreement["final_credit_points"])

    def test_the_ledger_is_adjusted_by_the_difference_not_reposted(self, api):
        """Both balances settle at 56.23 / -56.23 and still sum to 0.00.

        PRD: "The ledger is then **adjusted by the difference rather than posted
        afresh**: the amount by which `final_credit_points` exceeds
        `provisional_credit_points` is added to the sending institution's
        `transfer_credit_balance` and subtracted from the receiving
        institution's, so a downward re-valuation moves credit back the other way
        and the system-wide sum stays 0.00."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_transfer_credit_points
        """
        world = fx.world_delivered(
            api, temperature_samples=[12.0, 26.0, 27.0, 25.0, 26.0, 14.0, 15.0]
        )
        sender_balance = float(
            world.read_institution(world.sender_id)["transfer_credit_balance"]
        )
        receiver_balance = float(
            world.read_institution(world.receiver_id)["transfer_credit_balance"]
        )
        assert_money(sender_balance, 56.23, "sender transfer_credit_balance")
        assert_money(receiver_balance, -56.23, "receiver transfer_credit_balance")
        assert round(sender_balance + receiver_balance, 2) == 0.00

    def test_an_in_envelope_journey_leaves_the_two_valuations_equal(self, api):
        """Readings sitting on both envelope edges record zero excursion minutes.

        PRD: "The envelope is inclusive at both ends — a reading exactly equal to
        `temp_min_c` or exactly equal to `temp_max_c` is inside it and
        contributes nothing — and an empty array yields zero minutes."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_transfer_credit_points
        """
        world = fx.world_delivered(api, temperature_samples=[10.0, 24.0, 17.0])
        booking = world.read_booking()
        assert booking["thermal_excursion_minutes"] == 0
        agreement = world.read_agreement()
        assert_money(agreement["provisional_credit_points"], 62.23,
                     "provisional_credit_points")
        assert_money(agreement["final_credit_points"], 62.23,
                     "final_credit_points")
        assert_money(world.read_institution(world.sender_id)["transfer_credit_balance"],
                     62.23, "sender transfer_credit_balance")


class TestCreditComponentRoundingOrder:
    """Each component rounds before the sum, so the cents differ from a late round."""

    def test_the_three_components_round_before_they_are_added(self, api):
        """47.97 + 7.88 + 6.38 gives 62.23, never the late-rounded 62.22.

        PRD: "Three components are then computed, and **each is rounded half up
        to two decimal places before any of them are added together**"

        Design: Difficulty/combinatorial_formula/credit_component_rounding_order_pinned_round_then_sum
        """
        world = fx.world_with_executed_agreement(api)
        agreement = world.read_agreement()
        assert_money(agreement["provisional_credit_points"], 62.23,
                     "provisional_credit_points")
        assert float(agreement["provisional_credit_points"]) != 62.22

    def test_the_execution_posting_carries_the_pinned_cents_to_both_ledgers(
            self, api):
        """The double-entry postings are exactly +62.23 and -62.23.

        PRD: "Execution adds `provisional_credit_points` to the sending
        institution's balance and subtracts the same amount from the receiving
        institution's balance — the sender is credited for giving up the animal,
        the receiver debited for gaining it."

        Design: Difficulty/combinatorial_formula/credit_component_rounding_order_pinned_round_then_sum
        """
        world = fx.world_with_executed_agreement(api)
        assert_money(world.read_institution(world.sender_id)["transfer_credit_balance"],
                     62.23, "sender transfer_credit_balance")
        assert_money(world.read_institution(world.receiver_id)["transfer_credit_balance"],
                     -62.23, "receiver transfer_credit_balance")

    def test_a_breeding_loan_multiplies_the_pinned_subtotal_by_one_half(self, api):
        """62.23 under a BREEDING_LOAN rounds to 31.12, not 31.11.

        PRD: "Those three rounded values are summed to a subtotal, the subtotal
        is multiplied by the ownership multiplier for the agreement's
        `ownership_disposition` — 1.00 for `OWNERSHIP_TRANSFER`, 0.50 for
        `BREEDING_LOAN`, 0.65 for `LOAN_WITH_RETAINED_OWNERSHIP` — and that
        product is rounded half up to two decimal places again."

        Design: Difficulty/combinatorial_formula/credit_component_rounding_order_pinned_round_then_sum
        """
        world = fx.world_with_executed_agreement(
            api, agreement_overrides={"ownership_disposition": "BREEDING_LOAN"}
        )
        assert_money(world.read_agreement()["provisional_credit_points"], 31.12,
                     "provisional_credit_points")

    def test_a_retained_ownership_loan_multiplies_the_subtotal_by_0_65(self, api):
        """62.23 under LOAN_WITH_RETAINED_OWNERSHIP rounds to 40.45.

        PRD: "The rounding order is part of the rule, not an optimisation: the
        husbandry rate of 1.125 and the transport base of 12.5 are chosen
        precisely so that summing the unrounded components and rounding once at
        the end diverges by 0.01 from the specified order on ordinary inputs."

        Design: Difficulty/combinatorial_formula/credit_component_rounding_order_pinned_round_then_sum
        """
        world = fx.world_with_executed_agreement(
            api,
            agreement_overrides={
                "ownership_disposition": "LOAN_WITH_RETAINED_OWNERSHIP"
            },
        )
        agreement = world.read_agreement()
        assert_money(agreement["provisional_credit_points"], 40.45,
                     "provisional_credit_points")
        assert world.read_animal(world.m1_id)["owning_institution_id"] == \
            world.sender_id
