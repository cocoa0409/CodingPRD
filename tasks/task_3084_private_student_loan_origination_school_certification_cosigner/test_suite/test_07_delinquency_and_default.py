"""Payments, delinquency aging, cure, default and rehabilitation."""
from test_helpers import (
    ERR_AMOUNT_OUT_OF_RANGE,
    ERR_DEFAULT_THRESHOLD_NOT_MET,
    ERR_INVALID_STATE,
    ERR_LOAN_DELINQUENT,
    TEST_USERS,
    add_days,
    get_success_data,
    pay_period,
    period_due_date,
    setup_delinquent_loan,
    setup_loan_in_repayment,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client


def _loan(orig):
    return validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))


def test_an_uncleared_period_can_be_declared_in_default_once_arrears_reach_120(api):
    """PRD §3.6: "Default is declared by a servicer once the loan is `DELINQUENT` and
    its `days_past_due`, under the live as-of-clock variant, has reached 120 days."
    PRD §3.6: "Declaring default sets the loan's `notice_obligation_status` to
    `PENDING`, sets the backing cosigner's `underwriting_status` to `INELIGIBLE`...
    sets `disburse_blocked` to true"

    Design: Difficulty/non_linear_state_machine/default_and_rehabilitation_cycle_on_the_loan_column
    """
    orig = setup_delinquent_loan(days_past_due=125)
    declared = get_success_data(
        client.declare_default(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert declared["loan_status"] == "DEFAULT"
    assert declared["days_past_due"] >= 120
    assert declared["disburse_blocked"] is True
    assert declared["notice_obligation_status"] == "PENDING"
    assert validate_success(
        client.get_cosigner(orig.cosigner["id"], TEST_USERS["servicer_headers"])
    )["underwriting_status"] == "INELIGIBLE"


def test_a_defaulted_loan_is_recoverable_by_rehabilitation(api):
    """PRD §3.6: "Default is recoverable: a servicer may rehabilitate the loan by
    supplying a `rehabilitation_amount_cents` of at least three times the active
    plan's `monthly_payment_cents`... which clears `disburse_blocked`, recomputes
    arrears to zero and the stage to `CURRENT`, and returns the loan to
    `REPAYMENT`."

    Design: Difficulty/non_linear_state_machine/default_and_rehabilitation_cycle_on_the_loan_column
    """
    orig = setup_delinquent_loan()
    get_success_data(client.declare_default(orig.loan["id"], TEST_USERS["servicer_headers"]))

    rehabilitated = get_success_data(
        client.rehabilitate(orig.loan["id"], {"rehabilitation_amount_cents": 24165},
                            TEST_USERS["servicer_headers"])
    )
    assert rehabilitated["loan_status"] == "REPAYMENT"
    assert rehabilitated["disburse_blocked"] is False
    assert rehabilitated["days_past_due"] == 0
    assert rehabilitated["delinquency_stage"] == "CURRENT"
    assert rehabilitated["active_plan_type"] == "STANDARD", "the plan is untouched"


def test_rehabilitation_below_three_monthly_payments_is_refused(api):
    """PRD §3.6: "a servicer may rehabilitate the loan by supplying a
    `rehabilitation_amount_cents` of at least three times the active plan's
    `monthly_payment_cents` — a smaller amount is refused with
    `ERR_AMOUNT_OUT_OF_RANGE`"

    Design: Difficulty/non_linear_state_machine/default_and_rehabilitation_cycle_on_the_loan_column
    """
    orig = setup_delinquent_loan()
    get_success_data(client.declare_default(orig.loan["id"], TEST_USERS["servicer_headers"]))
    response = client.rehabilitate(
        orig.loan["id"], {"rehabilitation_amount_cents": 24164}, TEST_USERS["servicer_headers"]
    )
    validate_error(response, ERR_AMOUNT_OUT_OF_RANGE)
    assert _loan(orig)["loan_status"] == "DEFAULT"


def test_default_may_not_be_declared_before_the_arrears_threshold(api):
    """PRD §3.6: "Declaring default before that threshold is refused with
    `ERR_DEFAULT_THRESHOLD_NOT_MET`."
    PRD §3.6: "Default is declared by a servicer once the loan is `DELINQUENT` and
    its `days_past_due`, under the live as-of-clock variant, has reached 120 days."

    Design: Corner/errors/declaring_default_below_the_arrears_threshold_is_rejected
    """
    early = setup_delinquent_loan(days_past_due=100)
    assert _loan(early)["days_past_due"] == 100
    response = client.declare_default(early.loan["id"], TEST_USERS["servicer_headers"])
    validate_error(response, ERR_DEFAULT_THRESHOLD_NOT_MET)

    due2 = period_due_date(early.loan["id"], 2)
    set_clock(add_days(due2, 128))
    declared = get_success_data(
        client.declare_default(early.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert declared["loan_status"] == "DEFAULT"


def test_declaring_default_twice_is_refused(api):
    """PRD §2.12: "an operation that is not a declared transition out of the
    resource's current state, including any operation attempted on a resource
    already in a terminal state, yields `ERR_INVALID_STATE`"

    Design: Corner/state_machines/default_declaration_is_not_idempotent
    """
    orig = setup_delinquent_loan()
    first = get_success_data(
        client.declare_default(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert first["loan_status"] == "DEFAULT"

    response = client.declare_default(orig.loan["id"], TEST_USERS["servicer_headers"])
    validate_error(response, ERR_INVALID_STATE)
    loan = _loan(orig)
    assert loan["loan_status"] == "DEFAULT"
    assert loan["notice_obligation_status"] == "PENDING"


def test_delinquency_stage_boundaries_are_exact_at_twenty_nine_and_thirty_days(api):
    """PRD §3.6: "The `as_of_clock` variant, used for live reads and for every
    payment write, counts every elapsed day, so a period three days past due already
    reports three days."
    PRD §3.6: "`LATE` at 29 days or fewer, `DELINQUENT` at 119 days or fewer, and
    `DEFAULT_ELIGIBLE` beyond that."

    Design: Difficulty/non_linear_state_machine/default_and_rehabilitation_cycle_on_the_loan_column
    """
    orig = setup_delinquent_loan(days_past_due=29)
    at_29 = _loan(orig)
    assert at_29["days_past_due"] == 29
    assert at_29["delinquency_stage"] == "LATE"

    set_clock(add_days(period_due_date(orig.loan["id"], 2), 30))
    at_30 = _loan(orig)
    assert at_30["days_past_due"] == 30
    assert at_30["delinquency_stage"] == "DELINQUENT"


def test_a_missed_period_advances_the_loan_from_repayment_to_delinquent(api):
    """PRD §3.6: "A payment left uncleared is matured to `MISSED` once the logical
    clock passes its `scheduled_due_date` plus the notice threshold; that resets the
    borrower's run to zero, recomputes arrears, and advances the loan from
    `REPAYMENT` to `DELINQUENT`."

    Design: Difficulty/non_linear_state_machine/default_and_rehabilitation_cycle_on_the_loan_column
    """
    orig = setup_loan_in_repayment(periods=30)
    pay_period(orig.loan["id"], 1, "2026-10-05T00:00:00Z", "2026-10-05T00:00:00Z",
               borrower_headers=orig.applicant_headers)
    assert validate_success(
        client.get_borrower(orig.borrower["id"], TEST_USERS["servicer_headers"])
    )["on_time_payment_run_count"] == 1

    set_clock(add_days(period_due_date(orig.loan["id"], 2), 40))
    loan = _loan(orig)
    assert loan["loan_status"] == "DELINQUENT"
    assert validate_success(
        client.get_borrower(orig.borrower["id"], TEST_USERS["servicer_headers"])
    )["on_time_payment_run_count"] == 0


def test_a_late_payment_sets_whole_day_arrears_and_strips_qualifying_status(api):
    """PRD §3.6: "A late payment records its `arrear_days` as the whole-day gap
    between the scheduled due date and the paid date, sets `is_qualifying` to false,
    resets the borrower's `on_time_payment_run_count` to zero"

    Design: Difficulty/non_linear_state_machine/default_and_rehabilitation_cycle_on_the_loan_column
    """
    orig = setup_loan_in_repayment(periods=30)
    on_time = get_success_data(
        client.record_payment(
            orig.loan["id"],
            {"due_period_index": 1, "paid_date": "2026-10-05T00:00:00Z", "amount_cents": 8055},
            orig.applicant_headers,
        )
    )
    assert on_time["payment_status"] == "PAID_ON_TIME"
    assert on_time["arrear_days"] == 0
    assert on_time["is_qualifying"] is True

    due2 = period_due_date(orig.loan["id"], 2)
    late_date = add_days(due2, 63)
    set_clock(add_days(due2, 70))
    late = get_success_data(
        client.record_payment(
            orig.loan["id"],
            {"due_period_index": 2, "paid_date": late_date, "amount_cents": 8055},
            orig.applicant_headers,
        )
    )
    assert late["payment_status"] == "PAID_LATE"
    assert late["arrear_days"] == 63
    assert late["is_qualifying"] is False


def test_a_delinquent_loan_cannot_accept_an_automatic_debit_enrolment(api):
    """PRD §3.9: "A loan that is `DELINQUENT` or `DEFAULT` cannot accept an
    automatic-debit enrolment, which is refused with `ERR_LOAN_DELINQUENT`."

    Design: Difficulty/non_linear_state_machine/default_and_rehabilitation_cycle_on_the_loan_column
    """
    orig = setup_delinquent_loan()
    response = client.set_autodebit(
        orig.loan["id"], {"enrolled": True}, orig.applicant_headers
    )
    validate_error(response, ERR_LOAN_DELINQUENT)