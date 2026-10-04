"""Rounding order in the subsidy sum and the pinned evaluation order of
program profitability.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    setup_program_with_two_promo_plans,
    setup_settled_month,
    open_settlement_batch,
    program_summary,
    round_half_up,
    TERM_RATE,
    ACQUISITION_COST_PER_ACCOUNT_CENTS,
)


class TestPerPlanRoundingOrder:

    def test_subsidy_is_sum_of_per_plan_rounded_values(self, api, admin_headers):
        """PRD §2.7: "Where a calculation rounds a per-item figure and then sums,
        the per-item rounding happens first and the sum of the already-rounded
        figures is the result; the system never sums unrounded values and rounds
        once at the end."

        Design: Difficulty/combinatorial_formula/settlement_per_plan_rounding_then_sum
        """
        _partner, agreement, _program, _account, _plan12, _plan6 = (
            setup_program_with_two_promo_plans(api)
        )
        batch = open_settlement_batch(api, agreement["id"],
                                      "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
        result = validate_success(api.finalize_settlement_batch(batch["id"], admin_headers), 200)

        assert result["gross_subsidy_cents"] == 34776
        assert result["net_subsidy_cents"] == 4139
        assert result["transaction_count"] == 2

    def test_net_subsidy_is_not_the_round_of_the_unrounded_sum(self, api, admin_headers):
        """PRD §3.7: "the accrued interest is the principal multiplied by the
        plan's term rate, multiplied by that day count, divided by 365, rounded
        half-up; and `net_subsidy_cents` is the sum of those per-plan figures."
        PRD §2.7: "the system never sums unrounded values and rounds once at the
        end." The unrounded per-plan accruals sum to 4139.5068 cents; rounding
        that single total would give 4140.

        Design: Difficulty/combinatorial_formula/settlement_per_plan_rounding_then_sum
        """
        _partner, agreement, _program, _account, _plan12, _plan6 = (
            setup_program_with_two_promo_plans(api)
        )
        batch = open_settlement_batch(api, agreement["id"],
                                      "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
        result = validate_success(api.finalize_settlement_batch(batch["id"], admin_headers), 200)

        unrounded_sum = (120000 * TERM_RATE[12] * 30 / 365) + (240000 * TERM_RATE[6] * 30 / 365)
        sum_then_round = round_half_up(unrounded_sum)
        per_plan_sum = (round_half_up(120000 * TERM_RATE[12] * 30 / 365)
                        + round_half_up(240000 * TERM_RATE[6] * 30 / 365))

        assert sum_then_round == 4140, "the counterfactual total-round is 4140"
        assert per_plan_sum == 4139
        assert result["net_subsidy_cents"] == 4139
        assert result["net_subsidy_cents"] != sum_then_round


class TestProgramProfitabilityEvaluationOrder:

    def test_settled_contribution_is_scored_with_the_post_settlement_balance(
            self, api, admin_headers):
        """PRD §3.6: "It is the sum, over every settled settlement batch of the
        program, of the batch's net contribution, with the total acquisition cost
        of the program's accounts subtracted at the end." PRD §3.6: "A batch's
        average balance is defined after that batch's own profitability pass" and
        "the pinned order is to settle the batch, then recompute balances, then score".

        Design: Difficulty/combinatorial_formula/program_profitability_evaluation_order_settle_then_balance_then_score
        """
        _partner, _agreement, program, _account, _batch = setup_settled_month(api)
        summary = validate_success(api.get_program_summary(program["id"], admin_headers), 200)

        assert summary["program_profitability_cents"] == 21196, (
            f"expected 21196, got {summary['program_profitability_cents']}"
        )
        assert summary["free_look_exposure_cents"] == 0
        assert summary["settled_batch_count"] == 1

    def test_acquisition_cost_is_charged_once_per_account(self, api, admin_headers):
        """PRD §3.6: "The final subtraction is the account count of the program
        multiplied by a per-account acquisition cost of 4,200 cents" and "A
        batch's net contribution is the difference between its
        `gross_subsidy_cents` and its `retailer_liability_cents`, multiplied by a
        revenue-share multiplier" and "with the total acquisition cost of the
        program's accounts subtracted at the end".

        Design: Difficulty/combinatorial_formula/program_profitability_evaluation_order_settle_then_balance_then_score
        """
        _partner, _agreement, program, _account, batch = setup_settled_month(api)
        summary = validate_success(api.get_program_summary(program["id"], admin_headers), 200)

        multiplier = 1 + 0.12 * min(360000 / 1_000_000, 2.5)
        contribution = round_half_up(
            (batch["gross_subsidy_cents"] - batch["retailer_liability_cents"]) * multiplier
        )
        assert batch["gross_subsidy_cents"] == 34776
        assert batch["retailer_liability_cents"] == 10432
        assert contribution == 25396
        assert summary["program_profitability_cents"] == contribution - ACQUISITION_COST_PER_ACCOUNT_CENTS
        assert summary["account_count"] == 1