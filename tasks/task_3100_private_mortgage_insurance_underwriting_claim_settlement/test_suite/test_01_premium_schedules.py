"""Premium plan divergence: borrower-paid monthly versus lender-paid, and the
pinned true-up instalment schedule.

Covers difficulty rule dual_variant_calc (queue A, rule 1); the per-test
citation lines appear on each test below.
"""
import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import (
    api_client, setup_bpm_and_lpm_loans, setup_loan, UNDERWRITER,
    assert_premium_schedule, LOAN, RATE_CARD,
)


def test_borrower_paid_monthly_loan_bills_the_pinned_schedule():
    """PRD §3.3: "The canonical illustration is a loan whose coverage base is
    8500000 cents priced at 62 basis points: the annual premium rounds to 52700
    cents, the periodic amount is the ceiling of 52700 divided by twelve, or 4392
    cents, and the final period is 52700 less eleven times 4392, or 4388 cents".
    PRD §2.7: "the borrower is billed eleven periods of the ceiling-derived
    monthly amount, and the twelfth period absorbs whatever remainder is left so
    that the twelve periods sum exactly to the annual amount."

    Design: Difficulty/dual_variant_calc/lender_paid_versus_borrower_paid_premium_divergence
    """
    book = setup_bpm_and_lpm_loans()
    loan = get_success_data(api_client.get_loan(book["loan_bpm_id"], UNDERWRITER))

    assert loan["coverage_base_upb_cents"] == 8_500_000
    assert loan["rate_bps_applied"] == 62
    assert loan["annual_premium_cents"] == 52_700
    assert loan["monthly_period_cents"] == 4_392
    assert loan["final_period_cents"] == 4_388
    assert_premium_schedule(loan)


def test_lender_paid_loan_is_zero_premium_with_an_identical_coverage_base():
    """PRD §3.3: "Every period under it bills zero, and the applied rate is
    forced to zero at approval, so the loan is a zero-premium loan."
    PRD §2.11: "The rate that the card carries becomes the application's
    `rate_bps_applied`, frozen at that moment, and the resulting loan inherits
    it."

    Design: Difficulty/dual_variant_calc/lender_paid_versus_borrower_paid_premium_divergence
    """
    book = setup_bpm_and_lpm_loans()
    loan = get_success_data(api_client.get_loan(book["loan_lpm_id"], UNDERWRITER))

    # Identical coverage percentage and base: the divergence is the plan alone.
    assert loan["coverage_percent"] == 25
    assert loan["coverage_base_upb_cents"] == 8_500_000
    assert loan["premium_plan"] == "LPM"
    assert loan["borrower_paid"] is False
    # The zero-premium plan forces the applied rate and every period to zero.
    assert loan["rate_bps_applied"] == 0
    assert loan["annual_premium_cents"] == 0
    assert loan["monthly_period_cents"] == 0
    assert loan["final_period_cents"] == 0


def test_true_up_schedule_sums_to_the_annual_premium_and_rejects_per_period_rounding():
    """PRD §2.7: "the borrower is billed eleven periods of the ceiling-derived
    monthly amount, and the twelfth period absorbs whatever remainder is left so
    that the twelve periods sum exactly to the annual amount."
    PRD §3.3: "Rounding each period independently against the unrounded annual
    would instead produce twelve periods of 4391 cents, eight cents light of the
    true total".

    Design: Difficulty/dual_variant_calc/true_up_versus_per_period_rounding_divergence
    """
    book = setup_loan()
    loan = get_success_data(api_client.get_loan(book["loan_id"], UNDERWRITER))

    assert loan["annual_premium_cents"] == 52_700
    assert loan["monthly_period_cents"] == 4_392
    assert loan["final_period_cents"] == 4_388
    assert (11 * loan["monthly_period_cents"] + loan["final_period_cents"]) == 52_700
    # The per-period-independent-rounding reading is rejected outright.
    assert loan["monthly_period_cents"] != 4_391
    assert_premium_schedule(loan)


def test_final_period_absorbs_the_remainder_rather_than_a_redistributed_amount():
    """PRD §2.7: "The twelfth period is consequently the only period whose amount
    may differ from the other eleven, and it may be larger or smaller than them."
    PRD §3.3: "distributing the remainder any other way would produce a schedule
    that totals correctly but carries a different twelfth instalment. Only the
    pinned reading is acceptable."

    Design: Difficulty/dual_variant_calc/true_up_versus_per_period_rounding_divergence
    """
    book = setup_loan()
    loan = get_success_data(api_client.get_loan(book["loan_id"], UNDERWRITER))

    assert loan["final_period_cents"] != 4_408
    assert loan["final_period_cents"] == (
        loan["annual_premium_cents"] - 11 * loan["monthly_period_cents"])
    assert loan["final_period_cents"] < loan["monthly_period_cents"]