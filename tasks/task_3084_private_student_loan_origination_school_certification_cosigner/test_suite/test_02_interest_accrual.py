"""In-school interest accrual — the per-period and consolidated variants."""
from test_helpers import (
    TEST_USERS,
    assert_capitalized_within_cap,
    assert_loan,
    book_accrual,
    schedule_and_release,
    setup_certified_loan,
    setup_loan_in_repayment,
    validate_success,
)
from test_helpers import api_client as client


def _projection(orig, window_months):
    return validate_success(
        client.deferment_projection(
            orig.loan["id"], {"window_months": window_months}, orig.applicant_headers
        )
    )


def test_per_period_accrual_books_six_independent_monthly_roundings(api):
    """PRD §3.5: "The *per-period* variant, which is used to book ledger rows and to
    serve the live unpaid-interest figure, rounds each month independently and then
    sums. For each month of the window, in order, the interest for that single month
    is the principal multiplied by the monthly rate, rounded half up to a whole
    cent; the unpaid interest is the sum of those per-month roundings across the
    window."

    Design: Difficulty/dual_variant_calc/in_school_accrual_per_period_vs_consolidated_divergence
    """
    orig = setup_certified_loan(
        disburse=True, interest_accrual_option="IMMEDIATE", certified_amount_cents=805000,
        disbursement_amount_cents=805000,
    )
    assert orig.loan["effective_rate_pct"] == 3.75
    assert orig.loan["principal_cents"] == 805000

    book_accrual(orig.loan["id"], window_months=6)
    loan = validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))
    # 805000 * 0.0375 / 12 = 2515.625 -> 2516 per month, six times.
    assert loan["unpaid_interest_cents"] == 15096
    assert loan["loan_status"] == "IN_SCHOOL"
    assert loan["principal_cents"] == 805000, "accrual does not move principal"
    assert_loan(loan)


def test_consolidated_projection_rounds_the_whole_window_once(api):
    """PRD §3.5: "The *consolidated* variant, which is used for projections only,
    rounds exactly once over the whole window: the unpaid interest is the principal
    multiplied by the annual rate, multiplied by the window length in months,
    divided by twelve, and then rounded half up to a whole cent — a single rounding
    for the entire window."
    PRD §3.5: "this projection is answered under the consolidated variant, books
    nothing, and reports the projected figure as `projected_unpaid_interest_cents`
    alongside the `projection_variant` that produced it."

    Design: Difficulty/dual_variant_calc/in_school_accrual_per_period_vs_consolidated_divergence
    """
    orig = setup_certified_loan(
        disburse=True, interest_accrual_option="IMMEDIATE", certified_amount_cents=805000,
        disbursement_amount_cents=805000,
    )
    book_accrual(orig.loan["id"], window_months=6)
    loan = validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))
    assert loan["unpaid_interest_cents"] == 15096

    projection = _projection(orig, 6)
    # 805000 * 0.0375 * 6 / 12 = 15093.75 -> 15094, one rounding.
    assert projection["projected_unpaid_interest_cents"] == 15094
    assert projection["projection_variant"] == "accrued_consolidated"

    after = validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))
    assert after["unpaid_interest_cents"] == 15096, "a projection books nothing"


def test_the_two_accrual_variants_diverge_on_the_same_window(api):
    """PRD §3.5: "Because one rounds many times and the other once, the two variants
    are never equal whenever the principal-times-monthly-rate product has a
    fractional part."

    Design: Difficulty/dual_variant_calc/in_school_accrual_per_period_vs_consolidated_divergence
    """
    orig = setup_certified_loan(
        disburse=True, interest_accrual_option="IMMEDIATE", certified_amount_cents=805000,
        disbursement_amount_cents=805000,
    )
    book_accrual(orig.loan["id"], window_months=6)
    booked = validate_success(
        client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"])
    )["unpaid_interest_cents"]
    projected = _projection(orig, 6)["projected_unpaid_interest_cents"]
    assert booked - projected == 2, f"booked {booked} vs projected {projected}"


def test_booking_an_accrual_entry_creates_one_accrued_ledger_row(api):
    """PRD §3.5: "Booking an actual accrual entry requires an `entry_date` and a
    `window_months`, creates an `InterestAccrualEntry` in `ACCRUED` status sourced
    from `PERIOD_ACCRUAL`, and recomputes the loan's `unpaid_interest_cents` under
    the per-period variant together with `current_balance_cents`."

    Design: Difficulty/dual_variant_calc/in_school_accrual_per_period_vs_consolidated_divergence
    """
    orig = setup_certified_loan(
        disburse=True, interest_accrual_option="IMMEDIATE", certified_amount_cents=805000,
        disbursement_amount_cents=805000,
    )
    book_accrual(orig.loan["id"], window_months=1)
    entries = validate_success(
        client.list_accrual_entries(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert len(entries) == 1
    assert entries[0]["entry_status"] == "ACCRUED"
    assert entries[0]["source_event"] == "PERIOD_ACCRUAL"


def test_booking_continues_the_running_unpaid_interest_window(api):
    """PRD §3.5: "Neither variant may include a month already covered by an
    `InterestAccrualEntry` in `CAPITALIZED` status, because capitalization zeroes
    the un-capitalized balance and restarts the accrual window."

    Design: Difficulty/dual_variant_calc/in_school_accrual_per_period_vs_consolidated_divergence
    """
    orig = setup_certified_loan(
        disburse=True, interest_accrual_option="IMMEDIATE", certified_amount_cents=805000,
        disbursement_amount_cents=805000,
    )
    book_accrual(orig.loan["id"], window_months=32)
    loan = validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))
    # No capitalization yet, so the window keeps accruing month by month.
    assert loan["unpaid_interest_cents"] == 32 * 2516
    assert loan["earned_capitalization_count"] == 0

    book_accrual(orig.loan["id"], window_months=32)
    grown = validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))
    assert grown["unpaid_interest_cents"] == 64 * 2516, (
        "a second accrual adds to the running figure"
    )


def test_one_month_accrual_rounds_half_up_to_a_whole_cent(api):
    """PRD §3.5: "For each month of the window, in order, the interest for that
    single month is the principal multiplied by the monthly rate, rounded half up
    to a whole cent"
    PRD §2.7: "Round-half-up means that a value whose discarded portion is exactly
    one half is rounded away from zero to the next cent or next integer, not to the
    nearer even value."

    Design: Difficulty/dual_variant_calc/in_school_accrual_per_period_vs_consolidated_divergence
    """
    orig = setup_certified_loan(
        disburse=True, interest_accrual_option="IMMEDIATE", certified_amount_cents=805000,
        disbursement_amount_cents=805000,
    )
    book_accrual(orig.loan["id"], window_months=1)
    loan = validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))
    assert loan["unpaid_interest_cents"] == 2516, "805000 * 0.003125 = 2515.625"
    assert loan["max_allowed_capitalization_cents"] == 80500, "10 percent of 805000"


def test_capitalization_is_capped_at_ten_percent_of_disbursed_principal(api):
    """PRD §3.5: "the loan's `unpaid_interest_cents` as of the transition is
    compared against a cap equal to ten percent of the loan's disbursed principal,
    rounded half up to the cent, and the amount actually capitalized is the lesser
    of the two."
    PRD §3.5: "Any excess beyond the cap is *not* capitalized: it remains in
    `unpaid_interest_cents` and continues to accrue."

    Design: Difficulty/dual_variant_calc/in_school_accrual_per_period_vs_consolidated_divergence
    """
    orig = setup_loan_in_repayment(book_accrual=True)
    loan = validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))
    assert loan["max_allowed_capitalization_cents"] == 80500
    assert loan["lifetime_capitalized_interest_cents"] == 15096, (
        "the booked 15096 is below the 80500 cap, so it capitalizes whole"
    )
    assert loan["unpaid_interest_cents"] == 0
    assert_capitalized_within_cap(loan)