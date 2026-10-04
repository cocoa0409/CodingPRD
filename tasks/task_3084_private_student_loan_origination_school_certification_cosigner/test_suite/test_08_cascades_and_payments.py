"""Default cascades, cosigner notification and conserved payment counters."""
from test_helpers import (
    ERR_INVALID_STATE,
    ERR_NOTICE_OBLIGATION_PENDING,
    TEST_USERS,
    add_days,
    get_success_data,
    period_due_date,
    release_application_payload,
    setup_delinquent_loan,
    setup_loan_with_qualifying_payments,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client


def _loan(orig):
    return validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))


def test_default_cascade_reaches_the_cosigner_and_declines_open_release(api):
    """PRD §3.6: "Declaring default sets the loan's `notice_obligation_status` to
    `PENDING`, sets the backing cosigner's `underwriting_status` to `INELIGIBLE`,
    declines every open cosigner release application child with the `DELINQUENT_LOAN`
    deficiency reason, sets `disburse_blocked` to true"

    Design: Difficulty/transitive_cascade/default_cascade_reaches_cosigner_then_release_application
    """
    orig = setup_loan_with_qualifying_payments(24)
    # A release can only be filed once the 24-payment run qualifies, so it is
    # open (UNDER_REVIEW) before the loan is driven into default.
    release = get_success_data(
        client.create_release_application(
            orig.loan["id"],
            release_application_payload(orig.cosigner["id"], independent_credit_score=690,
                                        independent_dti_ratio=0.30),
            orig.applicant_headers,
        )
    )
    assert release["release_status"] == "UNDER_REVIEW"

    next_due = period_due_date(orig.loan["id"], 25)
    set_clock(add_days(next_due, 130))
    loan = get_success_data(
        client.declare_default(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert loan["loan_status"] == "DEFAULT"
    assert loan["notice_obligation_status"] == "PENDING"
    assert loan["disburse_blocked"] is True

    assert validate_success(
        client.get_cosigner(orig.cosigner["id"], TEST_USERS["servicer_headers"])
    )["underwriting_status"] == "INELIGIBLE"

    declined = validate_success(
        client.get_release_application(release["id"], TEST_USERS["underwriter_headers"])
    )
    assert declined["release_status"] == "DECLINED"
    assert declined["deficiency_reason"] == "DELINQUENT_LOAN"


def test_default_reverts_the_automatic_debit_rate_reduction(api):
    """PRD §3.9: "a default, however, does revoke it, reverting `effective_rate_pct`
    to the margin."
    PRD §3.6: "reverts the loan's `effective_rate_pct` to its `margin_rate_pct` — the
    automatic-debit reduction is removed."

    Design: Difficulty/transitive_cascade/default_cascade_reaches_cosigner_then_release_application
    """
    orig = setup_loan_with_qualifying_payments(24, autodebit=True)
    assert _loan(orig)["effective_rate_pct"] == 3.5, "the reduction is in force"

    next_due = period_due_date(orig.loan["id"], 25)
    set_clock(add_days(next_due, 130))
    assert _loan(orig)["loan_status"] == "DELINQUENT"

    declared = get_success_data(
        client.declare_default(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert declared["effective_rate_pct"] == 3.75, "the reduction was revoked"


def test_a_pending_notification_obligation_blocks_a_release_approval(api):
    """PRD §3.8: "In addition, approval may not be granted while the loan's
    `notice_obligation_status` is `PENDING`; the notification obligation must first
    be recorded as `SATISFIED`, and until it is, the attempt is refused with
    `ERR_NOTICE_OBLIGATION_PENDING`."

    Design: Difficulty/transitive_cascade/default_cascade_reaches_cosigner_then_release_application
    """
    orig = setup_loan_with_qualifying_payments(24, autodebit=True)
    release = get_success_data(
        client.create_release_application(
            orig.loan["id"],
            release_application_payload(orig.cosigner["id"], independent_credit_score=750,
                                        independent_dti_ratio=0.20),
            orig.applicant_headers,
        )
    )
    assert release["release_status"] == "UNDER_REVIEW"

    # Arrears crossing the notice threshold raise the notification obligation. Six
    # days past due sits below the 120-day default floor, so the loan stays
    # DELINQUENT and the notice gate is the rule that blocks the approval.
    next_due = period_due_date(orig.loan["id"], 25)
    set_clock(add_days(next_due, 6))
    assert _loan(orig)["notice_obligation_status"] == "PENDING"

    response = client.decide_release_application(
        release["id"], {"decision": "APPROVE"}, TEST_USERS["underwriter_headers"]
    )
    validate_error(response, ERR_NOTICE_OBLIGATION_PENDING)


def test_reversing_a_cleared_payment_conserves_the_lifetime_count(api):
    """PRD §2.11: "`lifetime_on_time_payment_count` on a borrower is a conserved,
    monotonic quantity: it counts every qualifying payment ever made and is never
    reduced by a later reversal or a later late payment."
    PRD §3.6: "but the borrower's `lifetime_on_time_payment_count` is deliberately
    left unchanged, because it is conserved."

    Design: Difficulty/compensating_invariant/reversal_conserves_the_lifetime_qualifying_payment_count
    """
    orig = setup_loan_with_qualifying_payments(24, autodebit=True)
    before = _loan(orig)
    assert before["effective_rate_pct"] == 3.5
    last_payment = orig.payments[-1]

    reversed_payment = get_success_data(
        client.reverse_payment(last_payment["id"], {"reason": "RETURNED_ACH"},
                               TEST_USERS["servicer_headers"])
    )
    assert reversed_payment["payment_status"] == "REVERSED"
    assert reversed_payment["is_qualifying"] is False

    after = _loan(orig)
    assert after["current_balance_cents"] == before["current_balance_cents"] + 8055
    assert after["effective_rate_pct"] == 3.5, "the earned reduction survives its compensation"

    borrower = validate_success(
        client.get_borrower(orig.borrower["id"], TEST_USERS["servicer_headers"])
    )
    assert borrower["lifetime_on_time_payment_count"] == 24, "never decremented"
    assert borrower["on_time_payment_run_count"] == 23, "the run lost exactly one member"


def test_a_reversed_payment_cannot_be_reversed_again(api):
    """PRD §2.12: "an operation that is not a declared transition out of the
    resource's current state, including any operation attempted on a resource
    already in a terminal state, yields `ERR_INVALID_STATE`"

    Design: Corner/endpoints/reversed_payment_is_refused_on_an_already_reversed_row
    """
    orig = setup_loan_with_qualifying_payments(1)
    payment = orig.payments[0]
    first = get_success_data(
        client.reverse_payment(payment["id"], {"reason": "RETURNED_ACH"},
                               TEST_USERS["servicer_headers"])
    )
    assert first["payment_status"] == "REVERSED"

    balance = _loan(orig)["current_balance_cents"]
    response = client.reverse_payment(payment["id"], {"reason": "RETURNED_ACH"},
                                      TEST_USERS["servicer_headers"])
    validate_error(response, ERR_INVALID_STATE)
    assert _loan(orig)["current_balance_cents"] == balance, "credited exactly once"


def test_an_on_time_payment_extends_both_borrower_counters(api):
    """PRD §3.6: "An on-time payment records `arrear_days` of 0, sets its
    `is_qualifying` flag to true, increments both the borrower's
    `on_time_payment_run_count` and the borrower's `lifetime_on_time_payment_count`,
    and reduces the loan's `current_balance_cents` by the paid amount."

    Design: Difficulty/compensating_invariant/reversal_conserves_the_lifetime_qualifying_payment_count
    """
    orig = setup_loan_with_qualifying_payments(3)
    borrower = validate_success(
        client.get_borrower(orig.borrower["id"], TEST_USERS["servicer_headers"])
    )
    assert borrower["on_time_payment_run_count"] == 3
    assert borrower["lifetime_on_time_payment_count"] == 3


def test_withdrawing_a_release_application_leaves_the_cosigner_reference_alone(api):
    """PRD §3.8: "A release application that has not yet been decided may instead be
    withdrawn, which sets it to `WITHDRAWN` and leaves the loan's cosigner reference
    unchanged."

    Design: Corner/endpoints/withdrawing_a_decided_release_application_is_rejected
    """
    orig = setup_loan_with_qualifying_payments(24)
    release = get_success_data(
        client.create_release_application(
            orig.loan["id"],
            release_application_payload(orig.cosigner["id"]),
            orig.applicant_headers,
        )
    )
    withdrawn = get_success_data(
        client.withdraw_release_application(release["id"], orig.applicant_headers)
    )
    assert withdrawn["release_status"] == "WITHDRAWN"
    assert _loan(orig)["cosigner_id"] == orig.cosigner["id"]

    response = client.withdraw_release_application(release["id"], orig.applicant_headers)
    validate_error(response, ERR_INVALID_STATE)