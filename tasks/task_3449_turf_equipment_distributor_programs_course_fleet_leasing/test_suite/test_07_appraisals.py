"""Trade-in appraisal valuation: the BOOK and MARKET variants diverge on
identical inputs, `policy` selects `valued_cents`, and the dispute loop
re-runs the full valuation with overrides (PRD §3.5).
"""
from test_helpers import (
    assert_appraisal,
    assert_appraisal_valuation_consistency,
    create_appraisal_for,
    dispute_appraisal,
    revalue_appraisal,
    setup_lease_scenario,
)


def test_book_policy_selects_book_value(api):
    """PRD §3.5: "The appraisal's `age_months` is derived from usage: the
    reported `hours` divided by a monthly usage norm of 50 hours per month,
    rounded down to a whole month count. Under the book variant, the raw figure
    is the model's `list_price_cents` scaled by one minus the ratio of
    `age_months` to an 84-month depreciation schedule, and `book_value_cents`
    is the larger of that raw figure and a residual floor of 15 percent of
    `list_price_cents`, rounded half-up to integer cents; the book variant
    ignores condition grade entirely."
    PRD §3.5: "`valued_cents` then selects between them: the book figure when
    `policy` is `BOOK`, the market figure when `policy` is `MARKET`."

    Design: Difficulty/dual_variant_calc/trade_in_book_vs_market_divergence
    """
    ctx = setup_lease_scenario()
    appraisal = create_appraisal_for(
        ctx["lease"], ctx["model"], external_serial="OLD-001",
        hours=2200, condition_grade="B", policy="BOOK",
    )
    assert_appraisal(appraisal)
    # age_months = floor(2200 / 50) = 44; book =
    # round_half_up(7,500,000 x (1 - 44/84)) = round_half_up(3,571,428.57...) =
    # 3,571,429, above the 15% residual floor (1,125,000).
    assert appraisal["book_value_cents"] == 3571429
    # market = round_half_up(7,500,000 x 0.60 x 0.85 x (1 - 0.5 x 2200/4000))
    #        = round_half_up(2,773,125.0) = 2,773,125.
    assert appraisal["market_value_cents"] == 2773125
    assert appraisal["valued_cents"] == 3571429
    assert_appraisal_valuation_consistency(appraisal)


def test_market_policy_selects_market_value(api):
    """PRD §3.5: "Under the market variant, an hours factor starts at 1 and
    decays by half across the first 4,000 hours of use — precisely, one minus
    the product of 0.50 and the ratio of the smaller of `hours` and 4,000 to
    4,000 — and a condition multiplier of 1.00 for grade `A`, 0.85 for `B`,
    0.70 for `C`, or 0.50 for `D` applies; `market_value_cents` is
    `list_price_cents` times 60 percent times the condition multiplier times
    the hours factor, rounded half-up to integer cents, and the market variant
    ignores the depreciation schedule entirely."
    PRD §3.5: "`valued_cents` then selects between them: the book figure when
    `policy` is `BOOK`, the market figure when `policy` is `MARKET`."

    Design: Difficulty/dual_variant_calc/trade_in_book_vs_market_divergence
    """
    ctx = setup_lease_scenario()
    appraisal = create_appraisal_for(
        ctx["lease"], ctx["model"], external_serial="OLD-002",
        hours=2200, condition_grade="B", policy="MARKET",
    )
    assert_appraisal(appraisal)
    assert appraisal["market_value_cents"] == 2773125
    assert appraisal["valued_cents"] == 2773125, (
        "MARKET policy selects the market figure"
    )
    assert appraisal["book_value_cents"] != appraisal["market_value_cents"], (
        "identical hours/grade/model inputs diverge across the two variants"
    )
    assert_appraisal_valuation_consistency(appraisal)


def test_dispute_revalue_round_applies_policy_override(api):
    """PRD §3.5: "The owning `DistributorManager` answers a dispute in one of
    two ways: voiding the appraisal outright (`DISPUTED` to `VOIDED`), or
    re-opening valuation by moving it back to `VALUED` with any combination of
    override inputs — new `hours`, a revised `condition_grade`, or a changed
    `policy`. When overrides accompany the return to `VALUED`, they are applied
    first and then the full valuation re-runs, refreshing `book_value_cents`,
    `market_value_cents`, and `valued_cents`"

    Design: Difficulty/non_linear_state_machine/appraisal_dispute_revaluation_rounds
    """
    ctx = setup_lease_scenario()
    appraisal = create_appraisal_for(
        ctx["lease"], ctx["model"], external_serial="OLD-001",
        hours=2200, condition_grade="B", policy="BOOK",
    )
    assert appraisal["valued_cents"] == 3571429
    appraisal = dispute_appraisal(appraisal, ctx["course"])
    assert appraisal["status"] == "DISPUTED"
    appraisal = revalue_appraisal(appraisal, ctx["lease"], policy="MARKET")
    assert appraisal["status"] == "VALUED"
    assert appraisal["valued_cents"] == 2773125, (
        f"the policy override flips valued_cents to the market figure; got "
        f"{appraisal['valued_cents']}"
    )


def test_second_round_restores_book_value(api):
    """PRD §3.5: "this negotiation loop between `VALUED` and `DISPUTED` is
    deliberately cyclic, allowing repeated rounds."
    PRD §3.5: "When overrides accompany the return to `VALUED`, they are
    applied first and then the full valuation re-runs, refreshing
    `book_value_cents`, `market_value_cents`, and `valued_cents`"

    Design: Difficulty/non_linear_state_machine/appraisal_dispute_revaluation_rounds
    """
    ctx = setup_lease_scenario()
    appraisal = create_appraisal_for(
        ctx["lease"], ctx["model"], external_serial="OLD-001",
        hours=2200, condition_grade="B", policy="BOOK",
    )
    appraisal = dispute_appraisal(appraisal, ctx["course"])
    appraisal = revalue_appraisal(appraisal, ctx["lease"], policy="MARKET")
    assert appraisal["valued_cents"] == 2773125
    appraisal = dispute_appraisal(appraisal, ctx["course"])
    appraisal = revalue_appraisal(appraisal, ctx["lease"], policy="BOOK")
    assert appraisal["status"] == "VALUED"
    assert appraisal["valued_cents"] == 3571429, (
        "switching the policy override back to BOOK restores the book figure"
    )
    # Both variants are recomputed on every round.
    assert appraisal["book_value_cents"] == 3571429
    assert appraisal["market_value_cents"] == 2773125
