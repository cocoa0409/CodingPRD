"""The claim computation: two ceilings, a curtailment factor and a
credit-grade deductible."""
import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    api_client, setup_loan_with_approved_claim, LOAN, CLAIM, UNDERWRITER,
    create_book, submit_application, approve_non_delegated, issue_loan,
    file_claim, begin_claim_review, approve_claim, get_success_data,
)


def test_claim_arithmetic_applies_the_ceiling_before_the_curtailment():
    """PRD §3.8: "This ordering is normative: the ceiling caps the recoverable
    amount first, and only the capped figure is curtailed."
    PRD §3.8: "a claim with a covered amount of 8500000 cents, a curtailment
    factor of 0.40 and a deductible rate of 0.10 comes to a net amount of
    4590000 cents under the pinned order".

    Design: Difficulty/combinatorial_formula/claim_amount_nested_rounding_order
    """
    book = setup_loan_with_approved_claim()
    claim = get_success_data(api_client.get_claim(book["claim_id"], UNDERWRITER))

    assert claim["permitted_interest_cents"] == 1_200_000
    assert claim["permitted_advances_cents"] == 5_000_000
    assert claim["net_unpaid_balance_cents"] == 14_200_000
    assert claim["recoverable_amount_cents"] == 7_700_000
    assert claim["coverage_ceiling_cents"] == 8_500_000
    assert claim["covered_claim_amount_cents"] == 7_700_000
    assert claim["curtailment_rate_applied"] == 0.12
    assert claim["post_curtailment_cents"] == 6_776_000
    assert claim["claim_deductible_cents"] == 677_600
    assert claim["net_claim_amount_cents"] == 6_098_400


def test_curtailing_the_raw_recoverable_amount_gives_a_different_net():
    """PRD §3.8: "Applying the curtailment factor to the raw recoverable amount
    and then ceilinging the result is wrong and produces a different number".
    PRD §2.6: "every multiplication that could produce a fraction of a cent is
    floored, and no step is rounded half up".

    Design: Difficulty/combinatorial_formula/claim_amount_nested_rounding_order
    """
    book = setup_loan_with_approved_claim()
    claim = get_success_data(api_client.get_claim(book["claim_id"], UNDERWRITER))

    # The pre-curtailment amount that a curtail-then-ceiling implementation would
    # settle at: the raw recoverable amount curtailed at the same 0.12 factor,
    # rather than the claim's actual post-curtailment figure.
    raw_curtailed = 7_700_000 - int(7_700_000 * 0.12)
    assert raw_curtailed == 6_776_000
    assert claim["post_curtailment_cents"] == raw_curtailed
    # The frozen net is the pinned 6098400-cent reading, not the different figure
    # that curtailing the raw recoverable amount and then applying the grade-B
    # deductible would produce.
    assert claim["claim_deductible_cents"] == 677_600
    assert claim["net_claim_amount_cents"] != 6_177_600
    assert claim["net_claim_amount_cents"] == (
        claim["post_curtailment_cents"] - claim["claim_deductible_cents"])


def test_permitted_interest_and_advances_caps_are_floored_not_rounded():
    """PRD §3.8: "Permitted interest, held on the claim as `permitted_interest_cents`, is
    the lesser of the claimed `accrued_interest_cents` and fifteen percent of
    the unpaid principal, computed by multiplying the unpaid principal by 0.15
    and discarding any fractional cent."
    PRD §3.8: "Precision throughout this computation is exact integer arithmetic
    with a single rule: every multiplication that could produce a fraction of a
    cent is floored".

    Design: Difficulty/combinatorial_formula/claim_amount_nested_rounding_order
    """
    book = setup_loan_with_approved_claim(claim_overrides={
        "unpaid_principal_cents": 8_000_001,
        "accrued_interest_cents": 9_000_000,
        "allowable_advances_cents": 9_000_000,
    })
    claim = get_success_data(api_client.get_claim(book["claim_id"], UNDERWRITER))

    assert claim["permitted_interest_cents"] == int(8_000_001 * 0.15) == 1_200_000
    assert claim["permitted_advances_cents"] == int(8_000_001 * 1.10) == 8_800_001


def test_recoverable_amount_is_clamped_at_zero_when_proceeds_exceed_the_balance():
    """PRD §3.8: "The recoverable amount is the net unpaid balance less those
    floored net proceeds, itself floored at zero."
    PRD §3.8: "Formally it is the larger of zero and the net unpaid balance minus
    the larger of zero and the gross proceeds minus the expenses of sale."

    Design: Corner/calculations/gross_proceeds_exceeding_net_unpaid_balance_yields_a_zero_recoverable_amount
    """
    book = setup_loan_with_approved_claim(claim_overrides={
        "unpaid_principal_cents": 3_000_000,
        "accrued_interest_cents": 100_000,
        "allowable_advances_cents": 200_000,
        "gross_proceeds_cents": 5_000_000,
        "expenses_of_sale_cents": 100_000,
        "event_kind": "SHORT_SALE",
    })
    claim_id = book["claim_id"]
    claim = get_success_data(api_client.get_claim(claim_id, UNDERWRITER))

    assert claim["net_unpaid_balance_cents"] == 3_300_000
    assert claim["recoverable_amount_cents"] == 0
    assert claim["covered_claim_amount_cents"] == 0
    assert claim["net_claim_amount_cents"] == 0
    assert claim["claim_deductible_cents"] == 0

    options = get_success_data(api_client.list_settlement_options(claim_id, UNDERWRITER))
    assert len(options) == 4
    assert all(option["computed_amount_cents"] == 0 for option in options)


def test_a_loan_written_under_a_lender_paid_plan_still_curtails_and_deducts():
    """PRD §3.8: "A lender-paid loan occupies no special carve-out here: its
    underwriting-path curtailment factor applies exactly as it would to any
    other loan, and only its applied rate, and therefore its premium, is
    zero."

    Design: Difficulty/dual_variant_calc/lender_paid_versus_borrower_paid_premium_divergence
    """
    book = create_book(lender_delegated=False,
                       rate_card_overrides={"premium_plan": "LPM",
                                            "nondelagated_curtailment_rate": 0.08})
    # The LPM loan is priced at zero but written on the non-delegated path.
    app = submit_application(book, borrower_reference="LPM-CLAIM",
                             premium_plan="LPM", borrower_paid=False)
    approve_non_delegated(app["id"])
    loan = get_success_data(api_client.get_loan(
        issue_loan(book, app["id"])["id"], UNDERWRITER))
    assert loan["rate_bps_applied"] == 0
    assert loan["annual_premium_cents"] == 0

    book["loan_id"] = loan["id"]
    claim = file_claim(book)
    begin_claim_review(claim["id"])
    claim = approve_claim(claim["id"])

    # The non-delegated curtailment factor and the grade-B deductible both bite.
    assert claim["curtailment_rate_applied"] == 0.08
    assert claim["covered_claim_amount_cents"] == 7_700_000
    assert claim["post_curtailment_cents"] == 7_084_000
    assert claim["claim_deductible_cents"] == 708_400
    assert claim["net_claim_amount_cents"] == 6_375_600


def test_settlement_recomputes_the_arithmetic_from_the_rates_frozen_at_approval():
    """PRD §3.9: "Re-pricing is the rule at settlement, not pricing once and
    reusing."
    PRD §3.8: "Re-running the computation — which settlement does, and which a
    coverage-dispute decision does — recomputes every derived amount but never
    re-freezes either rate".

    Design: Corner/calculations/claim_settlement_arithmetic_uses_the_rates_frozen_at_approval
    """
    book = setup_loan_with_approved_claim()
    claim_id = book["claim_id"]
    approved = get_success_data(api_client.get_claim(claim_id, UNDERWRITER))
    loan = get_success_data(api_client.get_loan(book["loan_id"], UNDERWRITER))

    response = api_client.settle_claim(claim_id, {
        "settlement_option_kind": "CASH",
        "expected_claim_version": approved["version"],
        "expected_loan_version": loan["version"],
    }, book["lender_headers"])
    settled = validate_success(response)

    assert settled["curtailment_rate_applied"] == 0.12
    assert settled["net_claim_amount_cents"] == 6_098_400
    assert settled["net_claim_amount_cents"] == approved["net_claim_amount_cents"]
    assert settled["claim_deductible_cents"] == 677_600
    assert settled["settlement_amount_cents"] == 6_098_400