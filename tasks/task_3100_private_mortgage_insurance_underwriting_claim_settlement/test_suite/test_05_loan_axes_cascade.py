"""Loans, delinquency reporting and the coverage-termination cascade."""
import pytest

from prd_bench_local_runner.testing import validate_success, validate_error, get_success_data

from test_helpers import (
    ApiErrorId, api_client, setup_loan, setup_loan_with_deficient_reports,
    file_delinquency_report, refresh_loan, amortize, set_clock, UNDERWRITER,
    ADMIN, assert_instant_equals,
)


def test_amortization_and_coverage_axes_move_independently_on_one_loan():
    """PRD §2.10: "Reaching a milestone never by itself ends coverage, and ending
    coverage never resets the milestone axis."
    PRD §3.5: "at `AT_80` when the balance is above that 78 percent line but at
    or below the 80 percent line".
    PRD §3.5: "This automatic transition is skipped when a cancellation is already
    pending on the loan."

    Design: Difficulty/non_linear_state_machine/loan_coverage_and_amortization_axes_evolve_independently
    """
    book = setup_loan()
    # 31500000 is above the 78 percent line (31200000) and at or below the 80
    # percent line (32000000), so the loan takes AT_80 and no termination trigger
    # is satisfied: reaching a milestone has not by itself ended coverage.
    amortize(book, 31_500_000)
    at_80 = refresh_loan(book)
    assert at_80["amortization_status"] == "AT_80"
    assert at_80["coverage_status"] == "ACTIVE"
    assert at_80["termination_reason"] == "NONE"
    assert at_80["cancellation_effective_utc"] is None

    # The deeper milestone line does schedule the end of coverage, but that is the
    # LTV_MILESTONE trigger acting, not the milestone axis: the axis simply moves
    # to AT_78 and the earlier stamp is preserved.
    amortize(book, 31_190_000)
    at_78 = refresh_loan(book)
    assert at_78["amortization_status"] == "AT_78"
    assert at_78["milestone_78_reached_utc"] is not None
    assert at_78["coverage_status"] == "PENDING_CANCELLATION"
    assert at_78["termination_reason"] == "LTV_MILESTONE"


def test_a_balance_reaching_the_seventy_eight_percent_line_moves_the_coverage_axis():
    """PRD §3.5: "Because the balance has reached the seventy-eight percent
    amortized line, the loan's coverage is scheduled to end automatically: the
    coverage axis moves from `ACTIVE` to `PENDING_CANCELLATION`, the
    `termination_reason` becomes `LTV_MILESTONE`, and the `cancellation_effective_utc`
    is set to whichever is later — the current logical clock, or
    `milestone_78_reached_utc` plus thirty days."
    PRD §2.10: "A loan also carries a `termination_reason` drawn from `NONE`,
    `BORROWER_REQUEST`, `LTV_MILESTONE` and `SERVICER_LOSS_MITIGATION_FAILURE`".

    Design: Difficulty/non_linear_state_machine/loan_coverage_and_amortization_axes_evolve_independently
    """
    book = setup_loan()
    amortize(book, 31_190_000)
    loan = refresh_loan(book)

    assert loan["coverage_status"] == "PENDING_CANCELLATION"
    assert loan["termination_reason"] == "LTV_MILESTONE"
    # The clock is the 2026-09-01 default and the milestone was stamped at that
    # same instant, so the later of the clock and milestone + 30 days is 2026-10-01.
    assert_instant_equals(loan["cancellation_effective_utc"],
                          "2026-10-01T00:00:00Z", "cancellation_effective_utc")

    # The axis resolves when the logical clock reaches the effective instant.
    set_clock("2026-10-02T00:00:00Z")
    assert refresh_loan(book)["coverage_status"] == "CANCELLED"


def test_cancelling_a_loan_leaves_the_amortization_axis_where_it_was():
    """PRD §2.10: "The amortization axis, carried on the loan as
    `amortization_status`, takes the values `IN_AMORTIZATION`, `AT_78` and
    `AT_80`."
    PRD §3.5: "A loan's life is described on two axes that never interfere with
    each other."

    Design: Difficulty/non_linear_state_machine/loan_coverage_and_amortization_axes_evolve_independently
    """
    book = setup_loan()
    # A balance of 31500000 is above the 78 percent line (31190000) and at or
    # below the 80 percent line (32000000), so the loan sits at AT_80 and no
    # automatic termination trigger is satisfied.
    amortize(book, 31_500_000)
    loan_before = refresh_loan(book)
    assert loan_before["amortization_status"] == "AT_80"
    assert loan_before["coverage_status"] == "ACTIVE"

    # A borrower request terminates coverage; the balance axis is untouched.
    get_success_data(api_client.create_cancellation_notice(book["loan_id"], {
        "request_kind": "BORROWER_REQUEST",
        "requested_by_role": "BORROWER",
        "notice_utc": "2026-09-01T00:00:00Z",
        "evidence_cents": 1_000_000,
        "applied_utc": "2026-10-15T00:00:00Z",
    }, book["lender_headers"]))
    set_clock("2026-11-01T00:00:00Z")
    loan_after = refresh_loan(book)

    assert loan_after["coverage_status"] == "CANCELLED"
    assert loan_after["amortization_status"] == "AT_80"
    assert loan_after["termination_reason"] == "BORROWER_REQUEST"


def test_three_deficient_class_a_reports_cascade_to_pending_cancellation():
    """PRD §3.4: "A class A report whose `participation_standard_met` is false
    sets the loan's `claim_blocked` flag to true and stamps the loan's
    `last_loss_mitigation_deficient_utc` with that report's effective instant."
    PRD §3.5: "When a loan's `delinquency_streak` reaches three or more and the
    loan's `claim_blocked` flag is true, the coverage axis moves from `ACTIVE`
    to `PENDING_CANCELLATION` with a `termination_reason` of
    `SERVICER_LOSS_MITIGATION_FAILURE`".

    Design: Difficulty/transitive_cascade/delinquency_report_chain_reaches_coverage_cancellation
    """
    book = setup_loan()
    # Two deficient reports first, then the third which completes the streak.
    for period in ("2026-01", "2026-02"):
        file_delinquency_report(book, as_of_period=period, months_delinquent=3)
    file_delinquency_report(book, as_of_period="2026-03", months_delinquent=4)

    # hop 1: the eligibility flag and the deficiency instant.
    loan = refresh_loan(book)
    assert loan["claim_blocked"] is True
    assert_instant_equals(loan["last_loss_mitigation_deficient_utc"],
                          "2026-03-05T00:00:00Z", "last_loss_mitigation_deficient_utc")
    # hop 2: the streak satisfied the automatic termination trigger.
    assert loan["delinquency_streak"] == 3
    assert loan["coverage_status"] == "PENDING_CANCELLATION"
    assert loan["termination_reason"] == "SERVICER_LOSS_MITIGATION_FAILURE"
    # 2026-03-05 plus sixty days.
    assert_instant_equals(loan["cancellation_effective_utc"],
                          "2026-05-04T00:00:00Z", "cancellation_effective_utc")

    # hop 3: the separate expiry transition resolves the pending cancellation.
    set_clock("2026-05-05T00:00:00Z")
    final = refresh_loan(book)
    assert final["coverage_status"] == "CANCELLED"


def test_the_automatic_servicer_termination_records_its_own_notice():
    """PRD §3.5: "it also records a cancellation notice against the loan, of kind
    `SERVICER_LOSS_MITIGATION_FAILURE` and with a requesting party of
    `SERVICER`, so that the termination has a documentary trail."

    Design: Difficulty/transitive_cascade/delinquency_report_chain_reaches_coverage_cancellation
    """
    book = setup_loan()
    for period in ("2026-01", "2026-02", "2026-03"):
        file_delinquency_report(book, as_of_period=period, months_delinquent=4)

    notices = get_success_data(api_client.list_cancellation_notices(
        book["loan_id"], UNDERWRITER))
    assert len(notices) == 1
    assert notices[0]["request_kind"] == "SERVICER_LOSS_MITIGATION_FAILURE"
    assert notices[0]["requested_by_role"] == "SERVICER"


def test_a_deficient_servicer_cancellation_with_no_refund_basis_is_refused():
    """PRD §3.6: "Where the computed maximum refund is zero, the notice is refused
    with `ERR_CANCELLATION_NOT_PERMITTED` rather than applied with a zero refund;
    a factor of zero is not a cancellation ground."

    Design: Difficulty/transitive_cascade/delinquency_report_chain_reaches_coverage_cancellation
    """
    book = setup_loan()
    file_delinquency_report(
        book, as_of_period="2026-01", months_delinquent=2,
        loss_mitigation_activities=[
            {"activity_kind": "OUTREACH_SENT", "outcome": "COMPLETED",
             "activity_utc": "2026-01-10T00:00:00Z"}])
    assert refresh_loan(book)["claim_blocked"] is True

    # Nothing has amortized away, so the computed maximum refund is zero.
    response = api_client.create_cancellation_notice(book["loan_id"], {
        "request_kind": "SERVICER_LOSS_MITIGATION_FAILURE",
        "requested_by_role": "SERVICER",
        "notice_utc": "2026-01-20T00:00:00Z",
        "evidence_cents": 0,
        "applied_utc": "2026-02-20T00:00:00Z",
    }, book["servicer_headers"])
    validate_error(response, ApiErrorId.ERR_CANCELLATION_NOT_PERMITTED)
    assert refresh_loan(book)["coverage_status"] == "ACTIVE"
    assert get_success_data(api_client.list_cancellation_notices(
        book["loan_id"], UNDERWRITER)) == []