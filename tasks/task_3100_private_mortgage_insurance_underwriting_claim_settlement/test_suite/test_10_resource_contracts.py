"""Resource contracts: creation defaults, system-stamped fields, pagination and
the loan's child-collection reads."""
import pytest

from prd_bench_local_runner.testing import (
    validate_success, validate_paginated, validate_error, get_success_data,
)

from test_helpers import (
    ApiErrorId, api_client, create_book, setup_loan, setup_two_loans,
    amortize, amortize_into_at80, refresh_loan, set_clock, file_claim,
    create_claim_payload, UNDERWRITER, ADMIN,
)


def test_master_policy_create_applies_the_default_and_starts_active():
    """PRD §3.1: "The policy carries a `coverage_percent_default` — the coverage
    percentage applied when an application pins none — and that value may only
    ever be 12, 25 or 30; it defaults to 25."
    PRD §3.1: "A policy created through this operation starts `ACTIVE`".

    Design: Corner/entities/master_policy_create_applies_defaults_and_starts_active
    """
    response = api_client.create_master_policy({
        "policy_number": "MP-DEFAULT",
        "anniversary_utc": "2026-03-01T00:00:00Z",
        "delegated_curtailment_rate": 0.15,
        "nondelagated_curtailment_rate": 0.10,
        "ltv_variance_tolerance": 0.05,
        "servicer_loss_mitigation_standard": "PARTICIPATION",
        "rescission_relief_cycles": 2,
        "min_third_party_net_bps": 2000,
        "two_year_effective_flag": False,
        "exposure_contribution_rate": 0.50,
    }, ADMIN)
    data = validate_success(response, expected_status=201)

    assert data["coverage_percent_default"] == 25
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1
    assert data["id"] and data["created_at"] and data["updated_at"]


def test_lender_round_trips_through_the_single_resource_read():
    """PRD §3.1: "Lenders arrive under the same administrative authority,
    described by a `lender_name`, a `delegated_underwriting` flag that determines
    which underwriting path they may use, and a `policy_exposure_cap_cents`
    ceiling".
    PRD §2.8: "Where a path names a resource that does not exist at all, the
    entity-specific not-found code is used: `ERR_LENDER_NOT_FOUND`"

    Design: Corner/entities/lender_create_with_delegated_authority_round_trips_through_get
    """
    from prd_bench_local_runner.testing import NON_EXISTENT_UUID

    book = create_book(rate_card_overrides={}, with_rate_card=False)
    lender = get_success_data(api_client.get_lender(book["lender_id"], UNDERWRITER))

    assert lender["lender_name"] == "Cascade Mortgage"
    assert lender["delegated_underwriting"] is True
    assert lender["policy_exposure_cap_cents"] == 200_000_000
    assert lender["status"] == "ACTIVE"
    assert lender["version"] == 1

    missing = api_client.get_lender(NON_EXISTENT_UUID, UNDERWRITER)
    validate_error(missing, ApiErrorId.ERR_LENDER_NOT_FOUND)


def test_loans_list_paginates_and_counts_the_filtered_set():
    """PRD §2.3: "`limit` caps the number of items returned; it defaults to 10,
    and any supplied value must lie between 1 and 100 inclusive."
    PRD §2.3: "The list endpoints that accept a `status` filter — master policies,
    reinsurance treaties, servicers, lenders, coverage applications, claims,
    coverage disputes, reinsurance cessions and portfolio snapshots — apply it
    before pagination, so `total_count` reflects the filtered set."

    Design: Corner/entities/loans_list_paginates_and_filters_by_coverage_status
    """
    book = setup_two_loans()
    from test_helpers import (
        submit_application, approve_delegated, issue_loan, file_borrower_cancellation,
    )
    app_c = submit_application(book, borrower_reference="PAGE-C")
    approve_delegated(book, app_c["id"])
    loan_c = issue_loan(book, app_c["id"])
    amortize_into_at80(book, loan_id=loan_c["id"])
    file_borrower_cancellation(book, evidence_cents=735, loan_id=loan_c["id"])

    page_one = api_client.list_loans(UNDERWRITER, params={"limit": 2, "offset": 0})
    rows, meta = validate_paginated(page_one)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    page_two = api_client.list_loans(UNDERWRITER, params={"limit": 2, "offset": 2})
    rows_two, meta_two = validate_paginated(page_two)
    assert len(rows_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    active = api_client.list_loans(UNDERWRITER, params={"coverage_status": "ACTIVE"})
    active_rows, active_meta = validate_paginated(active)
    assert len(active_rows) == 2
    assert active_meta["total_count"] == 2

    pending = api_client.list_loans(UNDERWRITER,
                                    params={"coverage_status": "PENDING_CANCELLATION"})
    pending_rows, _ = validate_paginated(pending)
    assert len(pending_rows) == 1

    default_rows, default_meta = validate_paginated(api_client.list_loans(UNDERWRITER))
    assert len(default_rows) == 3
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0


def test_claim_create_stamps_system_fields_and_leaves_the_arithmetic_absent():
    """PRD §3.7: "The claim is created at `FILED` with `filed_utc` stamped from
    the logical clock, and it also receives a server-minted `trace_number` used
    purely for path addressing rather than for any ranking."
    PRD §3.7: "Its `curtailment_rate_applied`, `settlement_option_kind` and
    `settlement_amount_cents` are all absent at this point".

    Design: Corner/entities/claim_create_stamps_system_fields_and_leaves_arithmetic_null
    """
    book = setup_loan()
    response = api_client.create_claim(
        dict({"loan_id": book["loan_id"]}, **create_claim_payload()),
        book["lender_headers"])
    claim = validate_success(response, expected_status=201)

    assert claim["status"] == "FILED"
    assert claim["version"] == 1
    assert isinstance(claim["trace_number"], str) and claim["trace_number"]
    assert claim["settlement_option_kind"] is None
    assert claim["settlement_amount_cents"] is None
    assert claim["curtailment_rate_applied"] is None


def test_claim_create_rejects_an_event_instant_in_the_future():
    """PRD §2.12: "A required field that is absent, a value of the wrong type, a
    negative monetary amount, or an event instant set in the future is refused
    with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/claim_create_rejects_a_future_event_instant
    """
    book = setup_loan()
    from test_helpers import create_claim_payload as _claim_payload
    payload = _claim_payload(event_completed_utc="2026-12-01T00:00:00Z")
    payload["loan_id"] = book["loan_id"]

    response = api_client.create_claim(payload, book["lender_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    rows = get_success_data(api_client.list_loan_claims(book["loan_id"], UNDERWRITER))
    assert rows == []


def test_portfolio_snapshot_is_a_frozen_computed_record():
    """PRD §3.12: "`geography_totals`, are the sums of the in-force coverage base
    by the loan's five-digit FIPS `county_code`".
    PRD §3.12: "each is `BREACHED` when that county's total is greater than or
    equal to the snapshot's threshold — the comparison is inclusive at the
    threshold".

    Design: Corner/entities/portfolio_snapshot_is_a_frozen_computed_record
    """
    book = setup_loan()
    snapshot = validate_success(api_client.create_snapshot({
        "snapshot_utc": "2026-09-01T00:00:00Z",
        "cluster_in_force_threshold_cents": 8_000_000,
    }, ADMIN), expected_status=201)

    assert snapshot["status"] == "COMPUTED"
    assert snapshot["aggregate_ceded_cents"] == 0

    # The in-force book then changes: the loan amortizes and is cancelled.
    amortize_into_at80(book)
    from test_helpers import file_borrower_cancellation
    file_borrower_cancellation(book, evidence_cents=735)
    set_clock("2026-11-01T00:00:00Z")

    reread = get_success_data(api_client.get_snapshot(snapshot["id"], ADMIN))
    assert reread["id"] == snapshot["id"]
    assert reread["version"] == 1


def test_loans_child_collection_reads_return_only_that_loans_children():
    """PRD §2.3: "The collection reads that hang off a loan (its cancellation
    notices, its delinquency reports, its claims, its external reports and its
    coverage disputes) are scoped to that loan".
    PRD §2.8: "Where a request names a resource that itself belongs to a larger
    one — a cancellation notice, a delinquency report, a claim, an external
    report or a coverage dispute under a loan".

    Design: Corner/endpoints/loan_fk_reads_return_the_loans_reports_claims_and_disputes
    """
    book = setup_two_loans()
    from test_helpers import file_delinquency_report, create_dispute_payload

    file_delinquency_report(book, loan_id=book["loan_a_id"], as_of_period="2026-01",
                            months_delinquent=2)
    claim = file_claim(book, loan_id=book["loan_a_id"])
    dispute_payload = create_dispute_payload()
    dispute_payload.update({
        "loan_id": book["loan_a_id"],
        "lender_id": book["lender_id"],
        "target_claim_id": claim["id"],
    })
    get_success_data(api_client.create_dispute(dispute_payload, book["lender_headers"]))

    assert len(get_success_data(api_client.list_loan_delinquency_reports(
        book["loan_a_id"], UNDERWRITER))) == 1
    assert len(get_success_data(api_client.list_loan_claims(
        book["loan_a_id"], UNDERWRITER))) == 1
    assert len(get_success_data(api_client.list_loan_coverage_disputes(
        book["loan_a_id"], UNDERWRITER))) == 1

    assert get_success_data(api_client.list_loan_claims(
        book["loan_b_id"], UNDERWRITER)) == []
    assert get_success_data(api_client.list_loan_delinquency_reports(
        book["loan_b_id"], UNDERWRITER)) == []

    filtered = get_success_data(api_client.list_claims(
        UNDERWRITER, params={"loan_id": book["loan_b_id"]}))
    assert filtered == []


def test_validation_report_recomputes_the_rescission_review_on_the_loan():
    """PRD §3.6: "a boolean `occupancy_materially_differs` that is true exactly
    when the reported occupancy is `INVESTMENT`."
    PRD §3.6: "A value-reset pathway is present when `post_origination_value_cents`
    exceeds the loan's `origination_property_value_cents`."

    Design: Difficulty/transitive_cascade/validation_report_chain_changes_dispute_decision_outcome
    """
    book = setup_loan()
    before = refresh_loan(book)
    assert before["verified_property_value_cents"] is None

    report = get_success_data(api_client.create_external_report(book["loan_id"], {
        "verified_loan_amount_cents": 34_000_000,
        "verified_property_value_cents": 39_000_000,
        "post_origination_value_cents": 41_000_000,
        "occupancy_reported": "INVESTMENT",
        "independent_validation_completed_utc": "2026-09-01T00:00:00Z",
    }, UNDERWRITER))

    assert report["occupancy_materially_differs"] is True
    assert report["validated_ltv"] == 87.1795

    after = refresh_loan(book)
    assert after["verified_property_value_cents"] == 39_000_000
    assert after["verified_loan_amount_cents"] == 34_000_000
    assert after["version"] > before["version"]