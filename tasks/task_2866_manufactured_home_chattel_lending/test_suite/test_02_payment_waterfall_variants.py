"""The classification-dependent payment waterfall and its compensating reversal.

One loan's obligation buckets absorb the same 100000 cents in two different
orders depending on the collateral's legal character (PRD §3.7), and a reversal
puts every bucket back exactly where it was.
"""

from test_helpers import (
    assert_allocation_sums_to_amount,
    assert_payment_transaction,
    assert_reversal_negates,
    factories,
    fixtures,
    total_obligation_cents,
    validate_paginated,
    validate_success,
)

FUND_CLOCK = "2026-08-01T00:00:00Z"
FIRST_DUE_DATE = "2026-09-01T00:00:00Z"
ESCROW_TARGET_CENTS = 200000

# Dana Whitfield, credit score 705, so the credit-tier spread is exactly zero.
DANA = {
    "full_name": "Dana Whitfield",
    "credit_score": 705,
    "monthly_income_cents": 520000,
    "state_code": "GA",
}

# ─── The private-land chattel loan of the dual-variant instance ───
# apr_bps 1100 = 875 base + 50 private land + 175 personal property.
# 61 days from 2026-08-01 to 2026-10-01 on 4600000 cents.
CHATTEL_INTEREST_CENTS = 84564
LATE_FEE_CENTS = 3500
FORCE_PLACED_PREMIUM_CENTS = 179515
CHATTEL_TO_FORCE_PLACED_CENTS = 11936
FORCE_PLACED_REMAINING_CENTS = 167579
PAYMENT_CENTS = 100000

# ─── The community loan of the reversal instance ───
# apr_bps 1275; 31 days from 2026-08-01 to 2026-09-01 on 4600000 cents.
COMMUNITY_INTEREST_CENTS = 49812
COMMUNITY_TO_ESCROW_CENTS = 50188
PRINCIPAL_CENTS = 4600000
OBLIGATION_BEFORE_CENTS = 4649812


def _funded_private_land_loan_with_force_placed_premium(api):
    """A funded chattel loan whose borrower policy lapsed, replaced by lender cover."""
    scenario = fixtures.setup_private_land_collateral(
        api, clock=FUND_CLOCK, borrower_overrides=DANA
    )
    scenario = fixtures.setup_approved_loan(api, scenario)
    scenario = fixtures.setup_funded_loan(
        api,
        scenario,
        dwelling_coverage_cents=5400000,
        filing_type="TITLE_LIEN",
        first_due_date=FIRST_DUE_DATE,
        escrow_target_cents=ESCROW_TARGET_CENTS,
        policy_overrides={"expiry_date": "2026-10-01T00:00:00Z"},
    )
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    scenario["loan"] = fixtures.run_servicing_assessment(api, scenario["loan"]["id"])
    scenario["force_placed_policy"] = validate_success(
        api.force_place_insurance(
            scenario["loan"]["id"],
            factories.force_place_payload(
                "2026-10-01T00:00:00Z", "2027-10-01T00:00:00Z"
            ),
            fixtures.SERVICER,
        ),
        201,
    )
    return scenario


def _funded_community_loan_after_one_accrual(api):
    """A funded community chattel loan carrying one month of accrued interest."""
    scenario = fixtures.setup_funded_community_loan(
        api,
        clock=FUND_CLOCK,
        first_due_date=FIRST_DUE_DATE,
        escrow_target_cents=ESCROW_TARGET_CENTS,
    )
    fixtures.set_clock(api, FIRST_DUE_DATE)
    scenario["loan"] = fixtures.run_servicing_assessment(api, scenario["loan"]["id"])
    return scenario


def test_chattel_contract_order_clears_interest_then_fees_then_force_placed(api):
    """PRD §3.7: "When the loan's `collateral_classification` is
    `PERSONAL_PROPERTY` the order is `CHATTEL_CONTRACT_ORDER`: accrued interest,
    then outstanding fees, then the force-placed premium, then the escrow
    shortfall, then principal."
    PRD §3.7: "Each bucket in turn absorbs the smaller of the cash still
    unallocated and its own outstanding amount, and the cash remaining is
    reduced by what was absorbed."

    Design: Difficulty/dual_variant_calc/payment_allocation_chattel_order_vs_real_property_escrow_first
    """
    scenario = _funded_private_land_loan_with_force_placed_premium(api)
    loan_id = scenario["loan"]["id"]

    payment = validate_success(
        api.create_payment(
            loan_id, factories.payment_payload(PAYMENT_CENTS, "PARTIAL"), fixtures.SERVICER
        ),
        201,
    )

    assert_payment_transaction(payment)
    assert payment["allocation_variant"] == "CHATTEL_CONTRACT_ORDER"
    assert payment["accrual_days"] == 0, (
        "the servicing assessment already accrued to this instant"
    )
    assert payment["to_interest_cents"] == CHATTEL_INTEREST_CENTS
    assert payment["to_fees_cents"] == LATE_FEE_CENTS
    assert payment["to_force_placed_cents"] == CHATTEL_TO_FORCE_PLACED_CENTS
    assert payment["to_escrow_cents"] == 0, (
        "the escrow shortfall sits behind the force-placed premium on the "
        "chattel order and the cash ran out first"
    )
    assert payment["to_principal_cents"] == 0
    assert_allocation_sums_to_amount(payment)

    loan = fixtures.read_loan(api, loan_id)
    assert loan["interest_accrued_unpaid_cents"] == 0
    assert loan["fees_outstanding_cents"] == 0
    assert loan["force_placed_premium_outstanding_cents"] == FORCE_PLACED_REMAINING_CENTS
    assert loan["escrow_balance_cents"] == 0
    assert loan["principal_balance_cents"] == PRINCIPAL_CENTS


def test_real_property_escrow_first_order_funds_escrow_before_any_other_bucket(api):
    """PRD §3.7: "When the classification is `REAL_PROPERTY` the order is
    `REAL_PROPERTY_ESCROW_FIRST`: the escrow shortfall, then the force-placed
    premium, then accrued interest, then outstanding fees, then principal."
    PRD §3.8: "Every non-terminal loan on the unit has its
    `collateral_classification` rewritten to `REAL_PROPERTY`, and any such loan
    whose lien dimension stood at `PERFECTED` is moved to
    `RE_PERFECTION_REQUIRED` — the loan is now unsecured in substance until a
    deed of trust is recorded."

    Design: Difficulty/dual_variant_calc/payment_allocation_chattel_order_vs_real_property_escrow_first
    """
    scenario = _funded_private_land_loan_with_force_placed_premium(api)
    loan_id = scenario["loan"]["id"]
    fixtures.post_payment(api, loan_id, PAYMENT_CENTS, "PARTIAL")

    fixtures.complete_conversion(api, scenario["unit"]["id"])
    loan = fixtures.read_loan(api, loan_id)
    assert loan["collateral_classification"] == "REAL_PROPERTY"

    payment = validate_success(
        api.create_payment(
            loan_id, factories.payment_payload(PAYMENT_CENTS, "PARTIAL"), fixtures.SERVICER
        ),
        201,
    )

    assert payment["allocation_variant"] == "REAL_PROPERTY_ESCROW_FIRST"
    assert payment["accrual_days"] == 0
    assert payment["to_escrow_cents"] == PAYMENT_CENTS
    assert payment["to_force_placed_cents"] == 0, (
        "the escrow shortfall is funded ahead of the force-placed premium"
    )
    assert payment["to_interest_cents"] == 0
    assert payment["to_fees_cents"] == 0
    assert payment["to_principal_cents"] == 0
    assert_allocation_sums_to_amount(payment)

    loan = fixtures.read_loan(api, loan_id)
    assert loan["escrow_balance_cents"] == PAYMENT_CENTS
    assert loan["force_placed_premium_outstanding_cents"] == FORCE_PLACED_REMAINING_CENTS
    assert loan["principal_balance_cents"] == PRINCIPAL_CENTS


def test_force_placed_premium_rounds_the_annual_figure_before_prorating(api):
    """PRD §3.6: "The annual premium is `required_coverage_cents` multiplied by
    the sum of a base rate of 185 basis points and a wind surcharge read off the
    unit's `wind_zone` — zero basis points in zone 1, 150 in zone 2 and 400 in
    zone 3 — divided by ten thousand, rounded half up."
    PRD §3.6: "Then `premium_cents` is that already-rounded annual figure
    multiplied by `coverage_days` and divided by 365, rounded half up again."

    Design: Difficulty/dual_variant_calc/payment_allocation_chattel_order_vs_real_property_escrow_first
    """
    scenario = _funded_private_land_loan_with_force_placed_premium(api)
    policy = scenario["force_placed_policy"]

    assert policy["source"] == "FORCE_PLACED"
    assert policy["coverage_days"] == 365
    assert policy["premium_cents"] == FORCE_PLACED_PREMIUM_CENTS
    loan = fixtures.read_loan(api, scenario["loan"]["id"])
    assert loan["force_placed_premium_outstanding_cents"] == FORCE_PLACED_PREMIUM_CENTS


def test_reversal_restores_every_obligation_bucket_to_its_pre_payment_amount(api):
    """PRD §3.7: "Applying those negatives restores every loan obligation bucket
    to its pre-payment amount, and it does so *without* re-accruing interest —
    the reversal undoes an allocation, it does not rewind the clock."
    PRD §3.7: "The escrow bucket for this purpose is the shortfall — the
    `escrow_target_cents` less the current `escrow_balance_cents`, floored at
    zero, so a fully funded escrow absorbs nothing."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_obligation_total
    """
    scenario = _funded_community_loan_after_one_accrual(api)
    loan_id = scenario["loan"]["id"]

    before = fixtures.read_loan(api, loan_id)
    assert before["interest_accrued_unpaid_cents"] == COMMUNITY_INTEREST_CENTS
    assert before["fees_outstanding_cents"] == 0
    assert before["force_placed_premium_outstanding_cents"] == 0
    assert before["escrow_balance_cents"] == 0
    assert before["principal_balance_cents"] == PRINCIPAL_CENTS
    assert total_obligation_cents(before) == OBLIGATION_BEFORE_CENTS

    payment = fixtures.post_payment(api, loan_id, PAYMENT_CENTS, "SCHEDULED")
    assert payment["to_interest_cents"] == COMMUNITY_INTEREST_CENTS
    assert payment["to_escrow_cents"] == COMMUNITY_TO_ESCROW_CENTS
    assert payment["to_fees_cents"] == 0
    assert payment["to_force_placed_cents"] == 0
    assert payment["to_principal_cents"] == 0

    after_payment = fixtures.read_loan(api, loan_id)
    assert after_payment["interest_accrued_unpaid_cents"] == 0
    assert after_payment["escrow_balance_cents"] == COMMUNITY_TO_ESCROW_CENTS
    assert after_payment["principal_balance_cents"] == PRINCIPAL_CENTS
    assert (
        total_obligation_cents(after_payment)
        == OBLIGATION_BEFORE_CENTS - PAYMENT_CENTS
    )

    validate_success(
        api.reverse_payment(
            payment["id"], fixtures.SERVICER, {"reversal_reason": "ACH_RETURN_R01"}
        ),
        201,
    )

    restored = fixtures.read_loan(api, loan_id)
    assert restored["interest_accrued_unpaid_cents"] == COMMUNITY_INTEREST_CENTS
    assert restored["escrow_balance_cents"] == 0
    assert restored["fees_outstanding_cents"] == 0
    assert restored["force_placed_premium_outstanding_cents"] == 0
    assert restored["principal_balance_cents"] == PRINCIPAL_CENTS
    assert total_obligation_cents(restored) == OBLIGATION_BEFORE_CENTS
    assert restored["servicing_state"] == "CURRENT"
    borrower = fixtures.read_borrower(api, scenario["borrower"]["id"])
    assert borrower["total_outstanding_principal_cents"] == PRINCIPAL_CENTS


def test_reversal_is_an_additional_row_negating_the_original_allocation(api):
    """PRD §3.7: "A `Servicer` reverses a posted payment with an optional
    `reversal_reason`, and the platform writes a new row whose `payment_kind` is
    `REVERSAL`, whose `reverses_payment_id` points at the original, whose
    `amount_cents` is negative, and whose five allocation fields are the exact
    negatives of the original row's five."
    PRD §3.7: "The original row's `reversed` flag is set to true, and the loan's
    `version` increments."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_obligation_total
    """
    scenario = _funded_community_loan_after_one_accrual(api)
    loan_id = scenario["loan"]["id"]
    original = fixtures.post_payment(api, loan_id, PAYMENT_CENTS, "SCHEDULED")

    reversal = validate_success(
        api.reverse_payment(
            original["id"], fixtures.SERVICER, {"reversal_reason": "ACH_RETURN_R01"}
        ),
        201,
    )

    assert_payment_transaction(reversal)
    assert_reversal_negates(original, reversal)
    assert reversal["to_interest_cents"] == -COMMUNITY_INTEREST_CENTS
    assert reversal["to_escrow_cents"] == -COMMUNITY_TO_ESCROW_CENTS
    assert reversal["reversed"] is False
    assert fixtures.read_payment(api, original["id"])["reversed"] is True

    rows, meta = validate_paginated(
        api.list_payments(fixtures.SERVICER, {"loan_id": loan_id})
    )
    assert meta["total_count"] == 2, (
        "the reversal is an additional row, never an edit of the original"
    )
    assert [row["id"] for row in rows] == [original["id"], reversal["id"]]
