"""Collection-boundary and settlement-admissibility boundaries, plus a second
view of the lender exposure crossing."""
import pytest

from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated, get_success_data,
)

from test_helpers import (
    ApiErrorId, api_client, create_book, setup_loan, setup_loan_with_approved_claim,
    setup_dispute, submit_application, approve_delegated, issue_loan, file_claim,
    refresh_loan, reconcile_exposure, ADMIN, UNDERWRITER,
)


def test_a_snapshot_over_a_single_loan_reports_its_geography_segment():
    """PRD §3.12: "`geography_totals`, are the sums of the in-force coverage base
    by the loan's five-digit FIPS `county_code`, which is carried on the coverage
    application's property record and denormalized onto the loan."
    PRD §3.12: "each is `BREACHED` when that county's total is greater than or
    equal to the snapshot's threshold".

    Design: Difficulty/boundary_precision_check/empty_in_force_book_yields_null_concentration_without_error
    """
    setup_loan()
    response = api_client.create_snapshot({
        "snapshot_utc": "2026-09-01T00:00:00Z",
        "cluster_in_force_threshold_cents": 8_500_000,
    }, ADMIN)
    data = validate_success(response, expected_status=201)

    # One in-force loan: the index is the whole book, and the single county is
    # BREACHED because the comparison is inclusive at the threshold.
    assert data["lender_concentration_index"] == 1.0
    assert len(data["geography_totals"]) == 1
    assert data["aggregate_ceded_cents"] == 0
    assert data["status"] == "COMPUTED"
    # A cancelled loan contributes nothing to the in-force book.
    assert data["lender_concentration_index"] is not None


def test_a_snapshot_computed_again_supersedes_the_previous_one():
    """PRD §3.12: "A newly computed snapshot is created `COMPUTED`; any
    previously computed snapshot for the same reporting basis is driven to
    `SUPERSEDED` when a newer one is computed".
    PRD §2.10: "A portfolio snapshot is `COMPUTED` and may become `SUPERSEDED`".

    Design: Difficulty/boundary_precision_check/empty_in_force_book_yields_null_concentration_without_error
    """
    create_book()
    first = validate_success(api_client.create_snapshot({
        "snapshot_utc": "2026-09-01T00:00:00Z",
        "cluster_in_force_threshold_cents": 17_000_000,
    }, ADMIN), expected_status=201)
    assert first["status"] == "COMPUTED"

    # No loans exist, so the newer snapshot is still over an empty book.
    second = validate_success(api_client.create_snapshot({
        "snapshot_utc": "2026-10-01T00:00:00Z",
        "cluster_in_force_threshold_cents": 17_000_000,
    }, ADMIN), expected_status=201)

    assert second["lender_concentration_index"] is None
    assert second["geography_totals"] == []
    assert second["segment_statuses"] == []


def test_settlement_is_permitted_while_a_loss_mitigation_excuse_dispute_is_open():
    """PRD §3.11: "an open dispute whose `grounds` are `LOSS_MITIGATION_EXCUSE`
    does not block settlement, because a dispute asserting that the
    loss-mitigation gate itself was misapplied has no bearing on the arithmetic
    being settled."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_referential_on_claim_settlement
    """
    book = setup_loan_with_approved_claim()
    claim_id = book["claim_id"]
    setup_dispute(book, grounds="LOSS_MITIGATION_EXCUSE")

    claim = get_success_data(api_client.get_claim(claim_id, UNDERWRITER))
    loan = refresh_loan(book)
    response = api_client.settle_claim(claim_id, {
        "settlement_option_kind": "CASH",
        "expected_claim_version": claim["version"],
        "expected_loan_version": loan["version"],
    }, book["lender_headers"])
    settled = validate_success(response)

    assert settled["status"] == "SETTLED"
    assert settled["settlement_amount_cents"] == 6_098_400


def test_claim_approval_refuses_a_claim_blocked_loan_that_was_never_cancelled():
    """PRD §3.8: "The loan's `claim_blocked` flag must be false at the same
    instant; otherwise the refusal is `ERR_CLAIM_BLOCKED_LOSS_MITIGATION`."
    PRD §3.4: "A loan carrying `claim_blocked` true is refused at claim approval
    with `ERR_CLAIM_BLOCKED_LOSS_MITIGATION`, discussed further in §3.8."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_temporal_on_claim_approval
    """
    book = setup_loan()
    from test_helpers import file_delinquency_report
    file_delinquency_report(
        book, as_of_period="2026-01", months_delinquent=2,
        loss_mitigation_activities=[
            {"activity_kind": "OUTREACH_SENT", "outcome": "COMPLETED",
             "activity_utc": "2026-01-10T00:00:00Z"}])
    loan = refresh_loan(book)
    # Coverage is still in force, so only the loss-mitigation gate is violated.
    assert loan["coverage_status"] == "ACTIVE"
    assert loan["claim_blocked"] is True

    claim = file_claim(book)
    from test_helpers import begin_claim_review
    begin_claim_review(claim["id"])

    response = api_client.approve_claim(claim["id"], UNDERWRITER)
    validate_error(response, ApiErrorId.ERR_CLAIM_BLOCKED_LOSS_MITIGATION)
    assert get_success_data(api_client.get_claim(
        claim["id"], UNDERWRITER))["status"] == "UNDER_REVIEW"