"""Applying money: contingency accounting, satisfaction and the money-in guards."""

from test_helpers import (
    ApiErrorId,
    book_payment,
    create_county_filing_payload,
    create_creditor,
    create_debtor,
    create_judgment,
    create_payment_payload,
    make_case_manager_headers,
    read_filing,
    read_judgment,
    read_payment,
    record_county_filing,
    setup_judgment,
    validate_error,
    validate_paginated,
)

CM = make_case_manager_headers()


# ==========================================================================
# Rounding order: per payment, then summed
# ==========================================================================
def test_each_payment_carries_its_own_half_up_rounded_slice(api):
    """PRD §2.6: "The recovery firm's contingency fee is rounded to a whole number
    of cents, half up, **once per payment**, and the per-payment slices are then
    summed; multiplying the aggregate collection by the fee rate and rounding once
    produces a different and incorrect figure."
    PRD §3.8: "Each payment's own `contingency_fee_cents` is then its
    `amount_cents` multiplied by that tier rate and divided by ten thousand,
    rounded half up to a whole cent, and the judgment's `contingency_fee_cents` is
    the sum of those per-payment slices."

    Design: Difficulty/combinatorial_formula/contingency_fee_rounded_per_payment_then_summed
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-0201",
        original_principal_cents=5_000_000,
        interest_rate_bps=0,
        filing_costs_cents=0,
    )

    first = book_payment(ctx["judgment"]["id"], 1_000_050)
    second = book_payment(ctx["judgment"]["id"], 500_050)

    assert read_payment(first["id"])["contingency_fee_cents"] == 330_017
    assert second["contingency_fee_cents"] == 165_017


def test_the_judgment_fee_is_the_sum_of_slices_not_a_single_rounding(api):
    """PRD §3.8: "Keying the tier on the gross less filing costs is a different
    and wrong answer, and multiplying the aggregate gross by the tier rate and
    rounding once instead of rounding each payment is likewise a different and
    wrong answer."
    PRD §3.8: "Only then are advanced costs reimbursed: the judgment's
    `net_to_creditor_cents` is `collected_to_date_cents` less
    `contingency_fee_cents` less `filing_costs_cents`."

    Design: Difficulty/combinatorial_formula/contingency_fee_rounded_per_payment_then_summed
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-0202",
        original_principal_cents=5_000_000,
        interest_rate_bps=0,
        filing_costs_cents=0,
    )
    book_payment(ctx["judgment"]["id"], 1_000_050)
    book_payment(ctx["judgment"]["id"], 500_050)

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["collected_to_date_cents"] == 1_500_100
    assert judgment["contingency_fee_cents"] == 495_034
    assert judgment["contingency_fee_cents"] != 495_033, (
        "rounding the 1,500,100-cent aggregate once would give 495033"
    )
    assert judgment["net_to_creditor_cents"] == 1_005_066


# ==========================================================================
# Tier selection is keyed on gross, before cost reimbursement
# ==========================================================================
def test_the_tier_is_keyed_on_the_gross_collection(api):
    """PRD §3.8: "The fee tier is selected from that gross figure **before any
    cost reimbursement**: 4,000 basis points when the gross collection is below
    1,000,000 cents, 3,300 basis points when it is below 5,000,000 cents, and
    2,500 basis points at or above 5,000,000 cents — the boundaries are exclusive
    on the upper end of each lower tier, so a gross of exactly 5,000,000 cents
    sits in the top tier."

    Design: Difficulty/combinatorial_formula/contingency_tier_keyed_on_gross_before_cost_reimbursement
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-0203",
        original_principal_cents=6_000_000,
        interest_rate_bps=0,
        filing_costs_cents=45_000,
    )

    payment = book_payment(ctx["judgment"]["id"], 5_000_000, source="SETTLEMENT")
    assert payment["contingency_fee_cents"] == 1_250_000

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["contingency_fee_cents"] == 1_250_000
    assert judgment["contingency_fee_cents"] != 1_650_000, (
        "keying the tier on gross minus the 45,000 cents of advanced costs would "
        "have picked the 3,300 bps tier"
    )


def test_advanced_costs_are_reimbursed_only_after_the_fee_is_taken(api):
    """PRD §3.8: "Only then are advanced costs reimbursed: the judgment's
    `net_to_creditor_cents` is `collected_to_date_cents` less
    `contingency_fee_cents` less `filing_costs_cents`."
    PRD §3.8: "The evaluation order is pinned and the apparent circularity is
    illusory — the tier depends only on the gross collection and nothing
    downstream feeds back into it."

    Design: Difficulty/combinatorial_formula/contingency_tier_keyed_on_gross_before_cost_reimbursement
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-0204",
        original_principal_cents=6_000_000,
        interest_rate_bps=0,
        filing_costs_cents=45_000,
    )
    book_payment(ctx["judgment"]["id"], 5_000_000, source="SETTLEMENT")

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["net_to_creditor_cents"] == 3_705_000
    assert judgment["net_to_creditor_cents"] != 3_305_000


# ==========================================================================
# The tier breakpoint itself
# ==========================================================================
def test_one_cent_below_five_million_stays_in_the_middle_tier(api):
    """PRD §3.8: "The fee tier is selected from that gross figure **before any
    cost reimbursement**: 4,000 basis points when the gross collection is below
    1,000,000 cents, 3,300 basis points when it is below 5,000,000 cents, and
    2,500 basis points at or above 5,000,000 cents — the boundaries are exclusive
    on the upper end of each lower tier, so a gross of exactly 5,000,000 cents
    sits in the top tier."

    Design: Difficulty/boundary_precision_check/contingency_tier_boundary_at_exactly_five_million_gross
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-0603",
        original_principal_cents=6_000_000,
        interest_rate_bps=0,
        filing_costs_cents=0,
    )

    payment = book_payment(ctx["judgment"]["id"], 4_999_999, source="SETTLEMENT")
    assert payment["contingency_fee_cents"] == 1_650_000

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["contingency_fee_cents"] == 1_650_000
    assert judgment["net_to_creditor_cents"] == 3_349_999


def test_exactly_five_million_gross_crosses_into_the_top_tier(api):
    """PRD §3.8: "The fee tier is selected from that gross figure **before any
    cost reimbursement**: 4,000 basis points when the gross collection is below
    1,000,000 cents, 3,300 basis points when it is below 5,000,000 cents, and
    2,500 basis points at or above 5,000,000 cents — the boundaries are exclusive
    on the upper end of each lower tier, so a gross of exactly 5,000,000 cents
    sits in the top tier."
    PRD §3.8: "Only then are advanced costs reimbursed: the judgment's
    `net_to_creditor_cents` is `collected_to_date_cents` less
    `contingency_fee_cents` less `filing_costs_cents`."

    Design: Difficulty/boundary_precision_check/contingency_tier_boundary_at_exactly_five_million_gross
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-0604",
        original_principal_cents=6_000_000,
        interest_rate_bps=0,
        filing_costs_cents=0,
    )

    payment = book_payment(ctx["judgment"]["id"], 5_000_000, source="SETTLEMENT")
    assert payment["contingency_fee_cents"] == 1_250_000

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["contingency_fee_cents"] == 1_250_000
    assert judgment["net_to_creditor_cents"] == 3_750_000


# ==========================================================================
# Corner coverage
# ==========================================================================
def test_paying_the_payoff_in_full_satisfies_and_releases_the_lien(api):
    """PRD §3.9: "A judgment moves `ACTIVE → SATISFIED` at the end of a payment
    booking or a payment reversal, whenever the replayed balances leave
    `principal_balance_cents`, `accrued_interest_cents` and `costs_balance_cents`
    all at zero, and also when an installment agreement completes."
    PRD §3.9: "Its `enforcement_posture` is driven to `NONE` in the same way, as
    `LIEN_PERFECTED → NONE`, `ENFORCING → NONE` or `STAYED → NONE`."
    PRD §3.9: "Every `RECORDED` county filing on it moves `RECORDED → RELEASED`,
    in `created_at` ascending order, and because those filings have left
    `RECORDED` the judgment's `perfected_county_count` is recomputed to 0."

    Design: Corner/state_machines/full_payment_auto_satisfies_judgment_and_releases_recorded_filing
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-2011",
        original_principal_cents=100_000,
        interest_rate_bps=0,
        filing_costs_cents=0,
    )
    filing = record_county_filing(ctx["judgment"]["id"], fee_cents=0)

    payment = book_payment(ctx["judgment"]["id"], 100_000)
    assert payment["applied_to_principal_cents"] == 100_000
    assert payment["contingency_fee_cents"] == 40_000

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["status"] == "SATISFIED"
    assert judgment["enforcement_posture"] == "NONE"
    assert judgment["total_payoff_cents"] == 0
    assert judgment["collected_to_date_cents"] == 100_000
    assert judgment["contingency_fee_cents"] == 40_000
    assert judgment["net_to_creditor_cents"] == 60_000
    assert judgment["perfected_county_count"] == 0
    assert read_filing(filing["id"])["status"] == "RELEASED"


def test_a_payment_dated_outside_the_judgments_life_is_refused(api):
    """PRD §3.8: "`received_on` must fall on or after the judgment's `entered_on`
    and on or before the current clock date, inclusive at both ends, and anything
    else is `ERR_PAYMENT_DATE_INVALID`."

    Design: Corner/validations/payment_dated_before_the_judgment_was_entered_is_rejected
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-4006", interest_rate_bps=0, filing_costs_cents=0
    )

    validate_error(
        api.create_payment(
            create_payment_payload(ctx["judgment"]["id"], 100_000, "2025-12-31"), CM
        ),
        ApiErrorId.ERR_PAYMENT_DATE_INVALID.value,
        422,
    )
    validate_error(
        api.create_payment(
            create_payment_payload(ctx["judgment"]["id"], 100_000, "2026-08-02"), CM
        ),
        ApiErrorId.ERR_PAYMENT_DATE_INVALID.value,
        422,
    )
    assert read_judgment(ctx["judgment"]["id"])["collected_to_date_cents"] == 0


def test_a_payment_larger_than_the_payoff_is_refused(api):
    """PRD §3.8: "It also refuses money the judgment cannot absorb: `amount_cents`
    may not exceed the `total_payoff_cents` produced by a replay whose reference
    date is the payment's own `received_on` — a point-in-time test, not a test
    against today's balance — and an overpayment is `ERR_PAYMENT_EXCEEDS_PAYOFF`."

    Design: Corner/validations/payment_exceeding_the_payoff_is_rejected
    """
    ctx = setup_judgment(
        court_case_number="CV-2026-4007",
        original_principal_cents=100_000,
        interest_rate_bps=0,
        filing_costs_cents=0,
    )

    validate_error(
        api.create_payment(
            create_payment_payload(ctx["judgment"]["id"], 100_001, "2026-08-01"), CM
        ),
        ApiErrorId.ERR_PAYMENT_EXCEEDS_PAYOFF.value,
        422,
    )

    book_payment(ctx["judgment"]["id"], 100_000)
    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["collected_to_date_cents"] == 100_000
    assert judgment["status"] == "SATISFIED"


def test_writing_to_a_satisfied_judgment_is_locked_down(api):
    """PRD §3.9: "Both `SATISFIED` and `EXPIRED` are terminal; no operation
    revives a judgment from either, and every write endpoint touching a dead
    judgment or any of its children answers `ERR_JUDGMENT_SATISFIED` or
    `ERR_JUDGMENT_EXPIRED` as appropriate."
    PRD §2.8: "The governing judgment's `status` is not `SATISFIED` — otherwise
    `ERR_JUDGMENT_SATISFIED` and HTTP 409, with the same breadth as the previous
    check."

    Design: Corner/state_machines/writing_to_a_satisfied_judgment_returns_judgment_satisfied
    """
    creditor = create_creditor()
    debtor = create_debtor()
    judgment = create_judgment(
        creditor["id"], debtor["id"],
        court_case_number="CV-2026-2015",
        original_principal_cents=100_000,
        interest_rate_bps=0,
        filing_costs_cents=0,
    )
    book_payment(judgment["id"], 100_000)
    assert read_judgment(judgment["id"])["status"] == "SATISFIED"

    validate_error(
        api.create_county_filing(
            create_county_filing_payload(judgment["id"], fee_cents=3_500), CM
        ),
        ApiErrorId.ERR_JUDGMENT_SATISFIED.value,
        409,
    )
    _rows, meta = validate_paginated(
        api.list_county_filings(CM, {"judgment_id": judgment["id"]})
    )
    assert meta["total_count"] == 0
