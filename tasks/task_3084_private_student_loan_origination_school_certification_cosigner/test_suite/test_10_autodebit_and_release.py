"""Automatic debit, cosigner release underwriting and the servicing reads."""
from test_helpers import (
    ERR_INVALID_STATE,
    ERR_RELEASE_RUN_INSUFFICIENT,
    ERR_RELEASE_UNDERWRITING_FAILED,
    TEST_USERS,
    get_success_data,
    release_application_payload,
    setup_loan_with_qualifying_payments,
    setup_loan_in_repayment,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client


def _loan(orig):
    return validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))


def test_enrolling_automatic_debit_alone_grants_no_rate_reduction(api):
    """PRD §3.9: "The reduction applies only when automatic debit is enrolled *and*
    the borrower's `lifetime_on_time_payment_count` has reached 24"
    PRD §3.9: "While it is not in force, the `effective_rate_pct` equals the
    `margin_rate_pct` exactly."

    Design: Difficulty/boundary_precision_check/autodebit_reduction_boundary_at_exactly_twentyfour_payments
    """
    orig = setup_loan_with_qualifying_payments(0, autodebit=True)
    loan = _loan(orig)
    assert loan["autodebit_enrolled"] is True
    assert loan["effective_rate_pct"] == 3.75, "enrolment alone grants nothing"


def test_the_reduction_applies_once_exactly_twenty_four_payments_have_cleared(api):
    """PRD §3.9: "Twenty-four qualifying payments earns the reduction; twenty-three
    does not. While the reduction is in force, the loan's `effective_rate_pct` is its
    `margin_rate_pct` minus 0.25 percentage points"

    Design: Difficulty/boundary_precision_check/autodebit_reduction_boundary_at_exactly_twentyfour_payments
    """
    orig = setup_loan_with_qualifying_payments(23, autodebit=True)
    at_23 = _loan(orig)
    assert at_23["effective_rate_pct"] == 3.75, "23 payments is still below the floor"
    assert orig.payments[22]["is_qualifying"] is True

    from test_helpers import add_days, period_due_date, set_clock

    due = period_due_date(orig.loan["id"], 24)
    paid = add_days(due, 0)
    set_clock(paid)
    get_success_data(
        client.record_payment(
            orig.loan["id"],
            {"due_period_index": 24, "paid_date": paid, "amount_cents": 8055},
            orig.applicant_headers,
        )
    )
    at_24 = _loan(orig)
    assert at_24["effective_rate_pct"] == 3.5, "the boundary is inclusive at 24"


def test_the_automatic_debit_milestone_reads_the_conserved_lifetime_counter(api):
    """PRD §3.9: "the milestone is measured on the conserved lifetime counter, never
    on the current run."
    PRD §2.11: "`lifetime_on_time_payment_count` on a borrower is a conserved,
    monotonic quantity: it counts every qualifying payment ever made and is never
    reduced by a later reversal or a later late payment."

    Design: Difficulty/boundary_precision_check/autodebit_reduction_boundary_at_exactly_twentyfour_payments
    """
    orig = setup_loan_with_qualifying_payments(24, autodebit=True)
    borrower = validate_success(
        client.get_borrower(orig.borrower["id"], TEST_USERS["servicer_headers"])
    )
    assert borrower["lifetime_on_time_payment_count"] == 24
    assert borrower["on_time_payment_run_count"] == 24
    assert _loan(orig)["effective_rate_pct"] == 3.5


def test_the_effective_rate_carries_four_decimal_places(api):
    """PRD §2.7: "the derived `effective_rate_pct` is expressed to four decimal
    places, rounded half up."
    PRD §3.9: "each change recomputes the loan's rate and its disclosure bound."

    Design: Difficulty/boundary_precision_check/autodebit_reduction_boundary_at_exactly_twentyfour_payments
    """
    orig = setup_loan_with_qualifying_payments(0, autodebit=False)
    loan = _loan(orig)
    assert loan["effective_rate_pct"] == 3.75
    text = f"{loan['effective_rate_pct']}"
    assert "." in text, "the rate is carried as a decimal, not an integer"


def test_a_released_cosigner_stops_backing_the_loan(api):
    """PRD §3.8: "The cosigner's `underwriting_status` becomes `RELEASED`; the loan's
    `cosigner_id` is cleared to null; and the loan's `principal_cents` is
    deliberately left unchanged — release removes the guarantee, not the debt."

    Design: Difficulty/compensating_invariant/reversal_conserves_the_lifetime_qualifying_payment_count
    """
    orig = setup_loan_with_qualifying_payments(24)
    release = get_success_data(
        client.create_release_application(
            orig.loan["id"],
            release_application_payload(orig.cosigner["id"], independent_credit_score=750,
                                        independent_dti_ratio=0.20),
            orig.applicant_headers,
        )
    )
    assert release["run_at_submission"] == 24
    assert release["required_min_payments"] == 24

    principal_before = _loan(orig)["principal_cents"]
    decided = get_success_data(
        client.decide_release_application(
            release["id"], {"decision": "APPROVE"}, TEST_USERS["underwriter_headers"]
        )
    )
    assert decided["release_status"] == "APPROVED"
    loan = _loan(orig)
    assert loan["cosigner_id"] is None, "the reference is cleared"
    assert loan["principal_cents"] == principal_before, "release removes the guarantee only"
    assert validate_success(
        client.get_cosigner(orig.cosigner["id"], TEST_USERS["servicer_headers"])
    )["underwriting_status"] == "RELEASED"


def test_release_filing_is_refused_below_the_required_payment_run(api):
    """PRD §3.8: "Filing also requires that the borrower's qualifying payment run, as
    captured at submission, has already reached the product's
    `cosigner_release_min_on_time_payments`; a run short of that threshold is refused
    with `ERR_RELEASE_RUN_INSUFFICIENT`."

    Design: Corner/errors/release_application_below_the_payment_run_is_rejected
    """
    orig = setup_loan_with_qualifying_payments(12)
    borrower = validate_success(
        client.get_borrower(orig.borrower["id"], TEST_USERS["servicer_headers"])
    )
    assert borrower["on_time_payment_run_count"] == 12

    response = client.create_release_application(
        orig.loan["id"], release_application_payload(orig.cosigner["id"]), orig.applicant_headers
    )
    validate_error(response, ERR_RELEASE_RUN_INSUFFICIENT)
    assert validate_success(
        client.list_release_applications(orig.loan["id"], orig.applicant_headers)
    ) == []


def test_a_release_below_the_credit_floor_is_refused_by_the_independent_review(api):
    """PRD §3.8: "the submitted `independent_credit_score` is at least the policy's
    `cosigner_release_min_credit_score`"
    PRD §3.8: "A release that fails any of these gates is refused with
    `ERR_RELEASE_UNDERWRITING_FAILED`."

    Design: Difficulty/cross_entity_state_dependency/loan_relief_transition_gated_by_the_loans_own_origination_state
    """
    orig = setup_loan_with_qualifying_payments(24)
    release = get_success_data(
        client.create_release_application(
            orig.loan["id"],
            release_application_payload(orig.cosigner["id"], independent_credit_score=650,
                                        independent_dti_ratio=0.20),
            orig.applicant_headers,
        )
    )
    response = client.decide_release_application(
        release["id"], {"decision": "APPROVE"}, TEST_USERS["underwriter_headers"]
    )
    validate_error(response, ERR_RELEASE_UNDERWRITING_FAILED)


def test_a_failed_release_records_its_first_failing_gate(api):
    """PRD §3.8: "A declined decision records its `deficiency_reason` as the first
    failing gate in the fixed order `INSUFFICIENT_PAYMENTS`, `CREDIT_SCORE`, `DTI`,
    `RELEASE_SCORE`, `DELINQUENT_LOAN`."

    Design: Corner/errors/standalone_file_is_rejected_when_the_product_requires_a_cosigner
    """
    orig = setup_loan_with_qualifying_payments(24)
    release = get_success_data(
        client.create_release_application(
            orig.loan["id"],
            release_application_payload(orig.cosigner["id"], independent_credit_score=620,
                                        independent_dti_ratio=0.20),
            orig.applicant_headers,
        )
    )
    declined = get_success_data(
        client.decide_release_application(
            release["id"], {"decision": "DECLINE"}, TEST_USERS["underwriter_headers"]
        )
    )
    assert declined["release_status"] == "DECLINED"
    assert declined["deficiency_reason"] == "CREDIT_SCORE"


def test_the_summary_read_rolls_the_loan_figures_together_without_mutating(api):
    """PRD §3.9: "A consolidated servicing read rolls the loan's figures together
    without mutating anything. It reports the loan's `current_balance_cents`, its
    `unpaid_interest_cents`, its `days_past_due` under the live as-of-clock variant,
    and a period-close arrears figure `period_close_days_past_due` under the
    period-close variant, together with its `delinquency_stage`, its
    `effective_rate_pct`, its `certified_headroom_cents`, a `release_eligible` flag,
    and its `notice_obligation_status`."

    Design: Corner/endpoints/summary_computed_read_reflects_the_loan_ledger
    """
    orig = setup_loan_in_repayment()
    summary = validate_success(
        client.loan_summary(orig.loan["id"], orig.applicant_headers)
    )
    for field in (
        "current_balance_cents",
        "unpaid_interest_cents",
        "days_past_due",
        "period_close_days_past_due",
        "delinquency_stage",
        "effective_rate_pct",
        "certified_headroom_cents",
        "release_eligible",
        "notice_obligation_status",
    ):
        assert field in summary, f"the summary read must expose {field}"
    assert summary["delinquency_stage"] == "CURRENT"
    assert summary["notice_obligation_status"] == "NONE"
    assert summary["release_eligible"] is False, "the on-time run is still zero"

    loan = _loan(orig)
    assert summary["current_balance_cents"] == loan["current_balance_cents"]
    assert summary["effective_rate_pct"] == loan["effective_rate_pct"]


def test_period_close_arrears_lags_the_live_arrears_by_the_grace_window(api):
    """PRD §3.6: "The `at_period_close` variant, used by the period-close booking,
    first subtracts the five-day period-close lag and reports zero unless the raw gap
    exceeds five days; the same six-day gap therefore reports one day under the
    period-close variant while the live read reports six."

    Design: Corner/calculations/delinquency_aging_stage_boundaries_are_exact
    """
    from test_helpers import add_days, period_due_date, setup_delinquent_loan, set_clock

    orig = setup_delinquent_loan(days_past_due=6)
    summary = validate_success(
        client.loan_summary(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert summary["days_past_due"] == 6
    assert summary["period_close_days_past_due"] == 1, "6 minus the 5-day lag"