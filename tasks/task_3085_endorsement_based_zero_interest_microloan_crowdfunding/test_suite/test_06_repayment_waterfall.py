"""Repayment waterfall, lender distribution, and the payment cascade
(PRD §3.7)."""
from test_helpers import (
    TEST_USERS,
    assert_loan_invariants,
    create_trustee,
    get_borrower,
    get_lender,
    get_loan,
    get_trustee,
    installments_by_number,
    make_borrower_headers,
    make_payment,
    set_clock,
    validate_error,
)
from test_helpers import api_client as client
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INVALID_STATE

ADMIN = TEST_USERS["admin_headers"]


def test_payment_waterfall_oldest_installment_first(api):
    """PRD §3.7: "Funds apply oldest-installment-first: walking the
    installments in ascending `installment_number`, skipping any already
    `PAID`, each installment absorbs the smaller of the remaining payment and
    its own `remaining_cents`. An installment fully covered becomes `PAID`
    with `paid_at` stamped and `remaining_cents` zeroed; one partially
    covered becomes `PARTIAL`."
    PRD §3.7: "After the walk, the loan's `outstanding_cents` is recomputed."

    Design: Corner/calculations/payment_waterfall_oldest_installment_first
    """
    set_clock()
    ns = fx.create_trustee_funded_loan(
        principal_cents=300_000,
        term_months=3,
        trustee_endorsement_amount=50_000,
        endorsement_amounts=[50_000, 50_000, 50_000, 50_000],
        contribution_amounts=[50_000],
    )

    make_payment(ns.loan, ns.borrower, 150_000)
    by_number = installments_by_number(ns.loan["id"])

    assert by_number[1]["status"] == "PAID"
    assert by_number[1]["amount_paid_cents"] == 100_000
    assert by_number[1]["remaining_cents"] == 0
    assert by_number[1]["paid_at"] is not None

    assert by_number[2]["status"] == "PARTIAL"
    assert by_number[2]["amount_paid_cents"] == 50_000
    assert by_number[2]["remaining_cents"] == 50_000

    assert by_number[3]["status"] == "PENDING"
    assert by_number[3]["amount_paid_cents"] == 0
    assert by_number[3]["remaining_cents"] == 100_000

    loan = get_loan(ns.loan["id"])
    assert loan["outstanding_cents"] == 150_000
    assert_loan_invariants(loan, list(by_number.values()))


def test_payment_cascade_pays_off_and_updates_borrower_and_trustee(api):
    """PRD §3.7: "If `outstanding_cents` reaches 0, the loan becomes
    `PAID_OFF` — from `REPAYING` or from `DELINQUENT` alike — the borrower's
    `completed_loan_count` increments, and, when a trustee endorsed the
    underlying application, the trustee's `endorsed_terminal_count`
    increments and its `default_rate_bps` is recomputed."
    PRD §3.7: "Each lender's lent total on the loan is the sum of their
    `CONVERTED` endorsement and contribution amounts."
    PRD §3.7: "each receives a share equal to the payment amount times their
    lent total divided by the loan's `principal_cents`, floored to whole
    cents, credited to `lending_balance_cents` and accumulated into
    `lifetime_repaid_cents`."

    Design: Difficulty/transitive_cascade/payment_cascade_installment_loan_borrower_trustee
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=1_000_000)
    # Build the pipeline manually so the first endorser also makes the final
    # contribution: 4 x 25000 endorsements + 50000 trustee endorsement
    # (private 150000), then a 50000 contribution from endorsers[0] lands
    # exactly on the 200000 request and flips the application FUNDED.
    ns = fx.create_private_fundraising_application(
        trustee=trustee, requested_amount_cents=200_000, term_months=3
    )
    application, endorsers = fx.meet_quorum_with_endorsements(
        ns, [25_000, 25_000, 25_000, 25_000], trustee_amount=50_000
    )
    application = fx.open_public(application, ns.borrower)
    double_dipper = endorsers[0]
    # Deposit max(25000*4, 100000) = 100000 at creation minus the 25000
    # endorsement leaves 75000 — enough for the 50000 contribution.
    fx.contribute(application, double_dipper, 50_000)
    application = fx.get_application(application["id"])
    assert application["status"] == "FUNDED"
    loan = fx.disburse(application)
    # The first endorser also made the 50000 contribution, so their lent
    # total on the loan is 75000 of 200000.
    ns_loan = loan

    set_clock("2026-09-15T00:00:00Z")
    make_payment(ns_loan, ns.borrower, 100_000)
    make_payment(ns_loan, ns.borrower, 100_000)

    loan = get_loan(ns_loan["id"])
    assert loan["status"] == "PAID_OFF"
    assert loan["outstanding_cents"] == 0

    borrower = get_borrower(ns.borrower["id"])
    assert borrower["completed_loan_count"] == 1

    trustee_after = get_trustee(trustee["id"])
    assert trustee_after["endorsed_terminal_count"] == 1
    assert trustee_after["default_rate_bps"] == 0

    lender = get_lender(double_dipper["id"])
    # Deposit 100000 (endorsement fixture default max(25000*4, 100000)) minus
    # the 25000 endorsement and the 50000 contribution, plus two repayment
    # shares of floor(100000 * 75000/200000) = 37500 each.
    assert lender["lifetime_lent_cents"] == 75_000
    assert lender["lifetime_repaid_cents"] == 75_000
    assert lender["lending_balance_cents"] == 100_000 - 25_000 - 50_000 + 75_000


def test_paid_off_cascade_counts_borrower_and_trustee_terminal_progress(api):
    """PRD §3.7: "If `outstanding_cents` reaches 0, the loan becomes
    `PAID_OFF` — from `REPAYING` or from `DELINQUENT` alike — the borrower's
    `completed_loan_count` increments, and, when a trustee endorsed the
    underlying application, the trustee's `endorsed_terminal_count`
    increments and its `default_rate_bps` is recomputed."
    PRD §3.8: "The `default_rate_bps` is 0 while the trustee has no
    terminally resolved endorsed loans, and otherwise ten thousand times
    `endorsed_defaulted_count` divided by `endorsed_terminal_count`, rounded
    half-up to integer basis points"

    Design: Difficulty/transitive_cascade/payment_cascade_installment_loan_borrower_trustee
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=1_000_000)
    ns = fx.create_trustee_funded_loan(
        principal_cents=100_000, term_months=3, trustee=trustee
    )
    assert get_borrower(ns.borrower["id"])["completed_loan_count"] == 0
    assert get_trustee(trustee["id"])["endorsed_terminal_count"] == 0

    make_payment(ns.loan, ns.borrower, 100_000)

    assert get_loan(ns.loan["id"])["status"] == "PAID_OFF"
    borrower = get_borrower(ns.borrower["id"])
    assert borrower["completed_loan_count"] == 1
    assert borrower["status"] == "REGISTERED", "payoff does not restrict"
    trustee_after = get_trustee(trustee["id"])
    assert trustee_after["endorsed_terminal_count"] == 1
    assert trustee_after["endorsed_defaulted_count"] == 0
    assert trustee_after["default_rate_bps"] == 0, "0 defaults over 1 terminal"


def test_paid_off_loan_is_terminal_for_payments(api):
    """PRD §3.7: "If `outstanding_cents` reaches 0, the loan becomes
    `PAID_OFF`"
    PRD §2.9: "Fourth, state permissibility of the target resource
    (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/paid_off_loan_is_terminal
    """
    set_clock()
    ns = fx.create_trustee_funded_loan(principal_cents=100_000, term_months=3)
    make_payment(ns.loan, ns.borrower, 100_000)
    assert get_loan(ns.loan["id"])["status"] == "PAID_OFF"

    resp = client.make_payment(
        ns.loan["id"],
        {"amount_cents": 2_500},
        make_borrower_headers(ns.borrower["id"]),
    )
    validate_error(resp, ERR_INVALID_STATE, expected_status=409)


def test_paid_off_loan_accepts_no_schedule_finalize(api):
    """PRD §3.6: "A `PlatformAdmin` may replace the provisional schedule with
    the final schedule exactly once, guarded by `expected_loan_version`, and
    only while the loan is `REPAYING`, the `schedule_status` is still
    `PROVISIONAL`, and no payment has touched any installment (every
    `amount_paid_cents` still 0) — otherwise the request fails with
    `ERR_SCHEDULE_ALREADY_FINAL` (HTTP 409)."

    Design: Corner/state_machines/paid_off_loan_is_terminal
    """
    set_clock()
    ns = fx.create_trustee_funded_loan(principal_cents=100_000, term_months=3)
    make_payment(ns.loan, ns.borrower, 100_000)
    loan = get_loan(ns.loan["id"])
    assert loan["status"] == "PAID_OFF"

    from test_helpers.api_errors import ERR_SCHEDULE_ALREADY_FINAL

    resp = client.finalize_schedule(
        loan["id"], {"expected_loan_version": loan["version"]}, ADMIN
    )
    validate_error(resp, ERR_SCHEDULE_ALREADY_FINAL, expected_status=409)


def test_principal_conserved_across_disburse_and_full_repayment(api):
    """PRD §2.6: "The platform is strictly zero-interest. A lender's return
    on any loan can never exceed the principal they lent: repayment
    distribution credits each lender's `lending_balance_cents` with a
    pro-rata share of each borrower payment, and the platform — not any
    lender — keeps whatever rounding remainder the shares leave behind."
    PRD §3.4: "Trustee endorsements move no money — no lender balance is
    debited"

    Design: Difficulty/compensating_invariant/principal_conserved_across_disburse_and_full_repayment
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=500_000)
    ns = fx.create_disbursed_loan(
        principal_cents=200_000,
        term_months=3,
        trustee=trustee,
        endorsement_amounts=[50_000, 50_000, 25_000, 25_000, 25_000],
        trustee_endorsement_amount=None,
        contribution_amounts=[25_000],
    )
    assert ns.application["status"] == "FUNDED"

    make_payment(ns.loan, ns.borrower, 200_000)
    assert get_loan(ns.loan["id"])["status"] == "PAID_OFF"

    expected = [50_000, 50_000, 25_000, 25_000, 25_000]
    pairs = list(zip(ns.endorsers, expected)) + [(ns.contributors[0], 25_000)]
    total_repaid = 0
    for lender, lent in pairs:
        after = get_lender(lender["id"])
        # floor(200000 * lent/200000) = lent exactly.
        assert after["lifetime_repaid_cents"] == lent
        assert after["lifetime_lent_cents"] == lent
        total_repaid += after["lifetime_repaid_cents"]
        # Zero interest: balance ends exactly at deposit - lent + repaid.
        deposited = max(lent * 4, 100_000)
        assert after["lending_balance_cents"] == deposited - lent + lent
    assert total_repaid == 200_000, "shares divide evenly; no interest paid"

    trustee_after = get_trustee(trustee["id"])
    assert trustee_after["endorsed_terminal_count"] == 1


def test_trustee_endorsement_receives_no_repayment_credit(api):
    """PRD §3.4: "Trustee endorsements move no money — no lender balance is
    debited"
    PRD §3.7: "Each lender's lent total on the loan is the sum of their
    `CONVERTED` endorsement and contribution amounts."
    PRD §2.6: "There is no interest field, no yield field, and no collections
    referral anywhere in the system."

    Design: Difficulty/compensating_invariant/principal_conserved_across_disburse_and_full_repayment
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=500_000)
    ns = fx.create_disbursed_loan(
        principal_cents=100_000,
        term_months=3,
        trustee=trustee,
        endorsement_amounts=[12_500, 12_500, 12_500, 12_500],
        trustee_endorsement_amount=25_000,
        contribution_amounts=[25_000],
    )
    make_payment(ns.loan, ns.borrower, 100_000)

    trustee_after = get_trustee(trustee["id"])
    # The trustee's own books carry no repayment-credit field; the only
    # observable effect is exposure release bookkeeping staying consistent.
    assert trustee_after["endorsed_terminal_count"] == 1
    for lender, lent in zip(ns.endorsers, [12_500, 12_500, 12_500, 12_500]):
        assert get_lender(lender["id"])["lifetime_repaid_cents"] == lent
