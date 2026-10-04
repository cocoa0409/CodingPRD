"""Temporal occupation semantics: the treaty window and the reporting month."""
import pytest

from prd_bench_local_runner.testing import validate_success, validate_error, get_success_data

from test_helpers import (
    ApiErrorId, api_client, setup_loan, issue_treaty_loan, file_claim,
    begin_claim_review, approve_claim, file_delinquency_report, set_clock,
    refresh_loan, ADMIN, UNDERWRITER, assert_instant_equals,
)

WINDOW = {
    "treaty_number": "TR-WINDOW",
    "inception_utc": "2026-01-01T00:00:00Z",
    "expiration_utc": "2027-01-01T00:00:00Z",
    "retention_per_claim_cents": 1_000_000,
    "exhaustion_per_claim_cents": 6_000_000,
    "aggregate_ceded_cap_cents": 5_000_000,
}


def test_treaty_event_exactly_at_inception_is_inside_the_window():
    """PRD §3.10: "In-force window means the treaty's `inception_utc` is at or
    before the claim's `event_completed_utc` and that instant is strictly before
    the treaty's `expiration_utc`; the inception bound is inclusive and the
    expiration bound is exclusive."

    Design: Difficulty/resource_temporal_overlap/reinsurance_treaty_occupation_is_half_open_at_the_upper_bound
    """
    book = issue_treaty_loan(WINDOW)
    claim = file_claim(book, event_completed_utc="2026-01-01T00:00:00Z")
    begin_claim_review(claim["id"])
    approved = approve_claim(claim["id"])
    loan = refresh_loan(book)

    settled = validate_success(api_client.settle_claim(claim["id"], {
        "settlement_option_kind": "CASH",
        "expected_claim_version": approved["version"],
        "expected_loan_version": loan["version"],
    }, book["lender_headers"]))
    assert settled["status"] == "SETTLED"
    assert settled["settlement_amount_cents"] == 6_098_400

    cessions = get_success_data(api_client.list_cessions(
        UNDERWRITER, params={"claim_id": claim["id"]}))
    assert len(cessions) == 1
    assert cessions[0]["status"] == "ACCEPTED"
    # The 6098400 net less the 1000000 retention exceeds the 5000000 capacity,
    # so the cession is capped rather than refused.
    final = refresh_loan(book)
    assert final["aggregate_ceded_cents"] == 5_000_000


def test_treaty_event_exactly_at_expiration_is_outside_the_window():
    """PRD §3.10: "the ceded amount is zero when that reference is absent, when
    the treaty's status is not `ACTIVE`, or when the treaty is not in force at
    the claim's event instant."
    PRD §2.10: "a rejected cession records exactly one of `NO_TREATY`,
    `TREATY_NOT_IN_FORCE_AT_EVENT` or `AGGREGATE_CAP_EXHAUSTED` as its reason".

    Design: Difficulty/resource_temporal_overlap/reinsurance_treaty_occupation_is_half_open_at_the_upper_bound
    """
    book = issue_treaty_loan(WINDOW)
    # The event instant equals the expiration bound, so the clock must reach it.
    set_clock("2027-06-01T00:00:00Z")
    claim = file_claim(book, event_completed_utc="2027-01-01T00:00:00Z")
    begin_claim_review(claim["id"])
    approved = approve_claim(claim["id"])
    loan = refresh_loan(book)

    settled = validate_success(api_client.settle_claim(claim["id"], {
        "settlement_option_kind": "CASH",
        "expected_claim_version": approved["version"],
        "expected_loan_version": loan["version"],
    }, book["lender_headers"]))
    assert settled["status"] == "SETTLED"

    cessions = get_success_data(api_client.list_cessions(
        UNDERWRITER, params={"claim_id": claim["id"]}))
    assert len(cessions) == 1
    assert cessions[0]["status"] == "REJECTED"
    assert cessions[0]["rejected_reason"] == "TREATY_NOT_IN_FORCE_AT_EVENT"

    final = refresh_loan(book)
    assert final["aggregate_ceded_cents"] == 0


def test_a_second_report_for_the_same_month_is_refused():
    """PRD §3.4: "only one report may exist per loan per reporting month, so
    filing a report whose `as_of_period` duplicates one already on file for that
    loan is refused with `ERR_DUPLICATE_PERIOD`."

    Design: Difficulty/resource_temporal_overlap/delinquency_report_occupation_is_a_calendar_month_gap_free_adjacency
    """
    book = setup_loan()
    file_delinquency_report(book, as_of_period="2026-01", delinquency_class="A",
                            months_delinquent=2)

    response = api_client.create_delinquency_report({
        "loan_id": book["loan_id"],
        "servicer_id": book["servicer_id"],
        "as_of_period": "2026-01",
        "delinquency_class": "B",
        "months_delinquent": 0,
        "loss_mitigation_activities": [],
    }, book["servicer_headers"])
    validate_error(response, ApiErrorId.ERR_DUPLICATE_PERIOD)


def test_the_adjacent_reporting_month_is_accepted_and_a_class_b_report_ends_the_streak():
    """PRD §3.4: "only one report may exist per loan per reporting month, so filing a
    report whose `as_of_period` duplicates one already on file for that loan is
    refused with `ERR_DUPLICATE_PERIOD`."
    PRD §3.4: "A class B report stops the count wherever it falls, so a loan with
    a class A report, a class B report and another class A report has a run of
    one."

    Design: Difficulty/resource_temporal_overlap/delinquency_report_occupation_is_a_calendar_month_gap_free_adjacency
    """
    book = setup_loan()
    file_delinquency_report(book, as_of_period="2026-01", delinquency_class="A",
                            months_delinquent=2)

    accepted = validate_success(api_client.create_delinquency_report({
        "loan_id": book["loan_id"],
        "servicer_id": book["servicer_id"],
        "as_of_period": "2026-02",
        "delinquency_class": "B",
        "months_delinquent": 0,
        "loss_mitigation_activities": [],
    }, book["servicer_headers"]), expected_status=201)
    assert_instant_equals(accepted["effective_utc"],
                          "2026-02-05T00:00:00Z", "effective_utc")

    reports = get_success_data(api_client.list_loan_delinquency_reports(
        book["loan_id"], UNDERWRITER))
    assert len(reports) == 2

    loan = refresh_loan(book)
    assert loan["delinquency_streak"] == 0


def test_a_cession_recorded_when_the_treaty_is_cancelled_is_rejected():
    """PRD §3.12: "Ceding is tested against the treaty's status and its in-force
    window at the moment of cession, so cancelling a treaty stops all further
    cessions against it even for loans already referencing it."
    PRD §3.10: "the ceded amount is zero when that reference is absent, when the
    treaty's status is not `ACTIVE`, or when the treaty is not in force at the
    claim's event instant."

    Design: Difficulty/resource_temporal_overlap/reinsurance_treaty_occupation_is_half_open_at_the_upper_bound
    """
    book = issue_treaty_loan(WINDOW)
    claim = file_claim(book)
    begin_claim_review(claim["id"])
    approved = approve_claim(claim["id"])

    get_success_data(api_client.cancel_treaty(book["treaty_id"], ADMIN))
    from test_helpers import ADMIN as _ADMIN
    treaty = get_success_data(api_client.get_treaty(book["treaty_id"], _ADMIN))
    assert treaty["status"] == "CANCELLED"

    loan = refresh_loan(book)
    resolved = validate_success(api_client.settle_claim(claim["id"], {
        "settlement_option_kind": "CASH",
        "expected_claim_version": approved["version"],
        "expected_loan_version": loan["version"],
    }, book["lender_headers"]))
    assert resolved["status"] == "SETTLED"

    cessions = get_success_data(api_client.list_cessions(
        UNDERWRITER, params={"claim_id": claim["id"]}))
    assert cessions[0]["status"] == "REJECTED"
    assert cessions[0]["rejected_reason"] == "TREATY_NOT_IN_FORCE_AT_EVENT"
    assert refresh_loan(book)["aggregate_ceded_cents"] == 0


def test_a_claim_event_inside_the_window_cannot_reference_a_treaty_that_was_never_created():
    """PRD §3.3: "that last identifier may name a treaty that is not yet in
    force, because cession is tested at settlement time against the treaty's
    window rather than at issuance."
    PRD §3.10: "The treaty is the one named by the loan's `reinsurance_treaty_id`,
    and the ceded amount is zero when that reference is absent".

    Design: Difficulty/resource_temporal_overlap/reinsurance_treaty_occupation_is_half_open_at_the_upper_bound
    """
    book = setup_loan()
    claim = file_claim(book)
    begin_claim_review(claim["id"])
    approved = approve_claim(claim["id"])
    loan = refresh_loan(book)

    resolved = validate_success(api_client.settle_claim(claim["id"], {
        "settlement_option_kind": "CASH",
        "expected_claim_version": approved["version"],
        "expected_loan_version": loan["version"],
    }, book["lender_headers"]))
    assert resolved["status"] == "SETTLED"
    assert resolved["settlement_amount_cents"] == 6_098_400

    cessions = get_success_data(api_client.list_cessions(
        UNDERWRITER, params={"claim_id": claim["id"]}))
    assert len(cessions) == 1
    assert cessions[0]["status"] == "REJECTED"
    assert cessions[0]["rejected_reason"] == "NO_TREATY"
    assert refresh_loan(book)["aggregate_ceded_cents"] == 0


def test_report_effective_instant_is_the_fifth_calendar_day_of_the_reporting_month():
    """PRD §3.4: "It is the fifth calendar day of the report's `as_of_period`
    month at midnight UTC, and this is the instant at which the report enters the
    loan's timeline — not the instant it was filed".

    Design: Difficulty/resource_temporal_overlap/delinquency_report_occupation_is_a_calendar_month_gap_free_adjacency
    """
    book = setup_loan()
    report = file_delinquency_report(book, as_of_period="2026-03", months_delinquent=1)

    assert_instant_equals(report["effective_utc"],
                          "2026-03-05T00:00:00Z", "effective_utc")
    assert report["as_of_period"] == "2026-03"
    assert report["status"] == "FILED"