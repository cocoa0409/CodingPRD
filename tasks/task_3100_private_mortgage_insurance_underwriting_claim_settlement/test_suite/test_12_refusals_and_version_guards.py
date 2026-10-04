"""Refusals, version guards and the consistency model."""
import pytest

from prd_bench_local_runner.testing import validate_success, validate_error, get_success_data

from test_helpers import (
    ApiErrorId, api_client, create_book, setup_loan, setup_loan_with_approved_claim,
    setup_loan_with_filed_claim, setup_approved_claim_for_loan, setup_dispute,
    file_claim, file_delinquency_report, refresh_loan, begin_claim_review,
    approve_claim, add_treaty, set_clock, issue_treaty_loan,
    ADMIN, UNDERWRITER,
)

NON_EXISTENT = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_reading_a_missing_claim_returns_the_claim_specific_not_found_code():
    """PRD §2.8: "Where a path names a resource that does not exist at all, the
    entity-specific not-found code is used".
    PRD §5: `ERR_CLAIM_NOT_FOUND` is an HTTP 404.

    Design: Corner/errors/initiating_a_claim_settlement_on_a_missing_claim_returns_claim_not_found
    """
    book = setup_loan()

    response = api_client.get_claim(NON_EXISTENT, UNDERWRITER)
    validate_error(response, ApiErrorId.ERR_CLAIM_NOT_FOUND)

    assert get_success_data(api_client.list_claims(
        UNDERWRITER, params={"loan_id": book["loan_id"]})) == []


def test_settlement_is_refused_while_a_non_excuse_dispute_is_open():
    """PRD §3.11: "no open curtailment dispute may be targeting the claim at the
    moment of settlement, and settlement attempted while one is open is refused
    with `ERR_CURTAILMENT_DISPUTE_OPEN`."
    PRD §3.11: "A dispute filed on any of the other three grounds —
    `ORIGINATION_OMISSION`, `OCCUPANCY_MISREPRESENTATION` or `VALUATION_ERROR` —
    blocks settlement while it remains open".

    Design: Corner/errors/settling_an_approved_claim_while_a_curtailment_dispute_is_open_is_refused
    """
    book = setup_loan_with_approved_claim()
    claim_id = book["claim_id"]
    setup_dispute(book, grounds="ORIGINATION_OMISSION")

    claim = get_success_data(api_client.get_claim(claim_id, UNDERWRITER))
    loan = refresh_loan(book)
    response = api_client.settle_claim(claim_id, {
        "settlement_option_kind": "CASH",
        "expected_claim_version": claim["version"],
        "expected_loan_version": loan["version"],
    }, book["lender_headers"])
    validate_error(response, ApiErrorId.ERR_CURTAILMENT_DISPUTE_OPEN)

    assert get_success_data(api_client.get_claim(claim_id, UNDERWRITER))["status"] == "APPROVED"
    assert get_success_data(api_client.list_cessions(
        UNDERWRITER, params={"claim_id": claim_id})) == []


def test_claim_approval_is_refused_when_coverage_was_not_in_force_at_the_event():
    """PRD §3.8: "Coverage must have been in force at the claim's event instant,
    meaning the loan's coverage axis was `ACTIVE` then; otherwise the approval is
    refused with `ERR_COVERAGE_NOT_ACTIVE`."

    Design: Corner/validations/claim_filed_after_the_loans_term_has_elapsed_is_time_barred
    """
    book = setup_loan()
    from test_helpers import amortize_into_at80, file_borrower_cancellation
    amortize_into_at80(book)
    file_borrower_cancellation(book, evidence_cents=735)
    set_clock("2026-11-01T00:00:00Z")
    assert refresh_loan(book)["coverage_status"] == "CANCELLED"

    claim = file_claim(book, event_completed_utc="2026-10-20T00:00:00Z")
    begin_claim_review(claim["id"])
    response = api_client.approve_claim(claim["id"], UNDERWRITER)
    validate_error(response, ApiErrorId.ERR_COVERAGE_NOT_ACTIVE)

    assert get_success_data(api_client.get_claim(
        claim["id"], UNDERWRITER))["status"] == "UNDER_REVIEW"


def test_claim_filed_after_the_loans_term_has_elapsed_is_time_barred():
    """PRD §3.7: "One absolute bar applies here: the claim must have been filed no
    later than the loan's `term_months` after the event instant."
    PRD §3.7: "A loan whose note term in months is 240 is therefore barred once
    more than 240 months have elapsed between the title-transferring event and
    the filing."

    Design: Corner/validations/claim_filed_after_the_loans_term_has_elapsed_is_time_barred
    """
    book = setup_loan()
    claim = file_claim(book, event_completed_utc="1996-08-01T00:00:00Z")

    response = api_client.begin_claim_review(claim["id"], UNDERWRITER)
    validate_error(response, ApiErrorId.ERR_CLAIM_TIME_BARRED)
    assert get_success_data(api_client.get_claim(claim["id"], UNDERWRITER))["status"] == "FILED"

    # The same items with a recent event instant pass the bar.
    book2 = setup_loan()
    claim2 = file_claim(book2)
    accepted = api_client.begin_claim_review(claim2["id"], UNDERWRITER)
    assert validate_success(accepted)["status"] == "UNDER_REVIEW"


def test_loss_mitigation_waiver_is_refused_when_the_policy_requires_participation_complete():
    """PRD §3.6: "A `relief_status` of `REVOKED` is the loss-mitigation waiver:
    it clears the loan's `claim_blocked` flag, but only when the master policy's
    `servicer_loss_mitigation_standard` is `PARTICIPATION` and an
    `waiver_evidence_code` is supplied and is an attached code."
    PRD §3.6: "A waiver attempted on a policy whose standard is
    `PARTICIPATION_COMPLETE`, or without an attached evidence code, is refused
    with `ERR_WAIVER_NOT_AVAILABLE`."

    Design: Corner/errors/exhausting_a_servicers_loss_mitigation_waiver_leaves_the_loan_claim_blocked
    """
    book = setup_loan()
    file_delinquency_report(
        book, as_of_period="2026-01", months_delinquent=2,
        loss_mitigation_activities=[
            {"activity_kind": "OUTREACH_SENT", "outcome": "COMPLETED",
             "activity_utc": "2026-01-10T00:00:00Z"}])
    assert refresh_loan(book)["claim_blocked"] is True

    response = api_client.record_rescission_relief(book["loan_id"], {
        "relief_status": "REVOKED",
        "waiver_evidence_code": "MITIGATION_ATTACHED",
    }, ADMIN)
    validate_error(response, ApiErrorId.ERR_WAIVER_NOT_AVAILABLE)
    assert refresh_loan(book)["claim_blocked"] is True


def test_loss_mitigation_waiver_is_refused_without_an_attached_evidence_code():
    """PRD §3.6: "it clears the loan's `claim_blocked` flag, but only when the
    master policy's `servicer_loss_mitigation_standard` is `PARTICIPATION` and an
    `waiver_evidence_code` is supplied and is an attached code."
    PRD §3.6: "A waiver attempted on a policy whose standard is
    `PARTICIPATION_COMPLETE`, or without an attached evidence code, is refused
    with `ERR_WAIVER_NOT_AVAILABLE`."

    Design: Corner/errors/exhausting_a_servicers_loss_mitigation_waiver_leaves_the_loan_claim_blocked
    """
    book = create_book(policy_overrides={"servicer_loss_mitigation_standard": "PARTICIPATION"})
    from test_helpers import submit_application, approve_delegated, issue_loan
    application = submit_application(book)
    approve_delegated(book, application["id"])
    loan = issue_loan(book, application["id"])
    book["loan_id"] = loan["id"]

    file_delinquency_report(
        book, as_of_period="2026-01", months_delinquent=2,
        loss_mitigation_activities=[
            {"activity_kind": "OUTREACH_SENT", "outcome": "COMPLETED",
             "activity_utc": "2026-01-10T00:00:00Z"}])
    assert refresh_loan(book)["claim_blocked"] is True

    response = api_client.record_rescission_relief(book["loan_id"], {
        "relief_status": "REVOKED",
    }, ADMIN)
    validate_error(response, ApiErrorId.ERR_WAIVER_NOT_AVAILABLE)
    assert refresh_loan(book)["claim_blocked"] is True


def test_manual_cession_is_refused_when_the_treaty_is_not_in_force_at_the_event():
    """PRD §3.10: "A cession that cannot be accepted for a treaty-related reason
    is still recorded, with status `REJECTED` and a `rejected_reason` of
    `NO_TREATY`, `TREATY_NOT_IN_FORCE_AT_EVENT` or `AGGREGATE_CAP_EXHAUSTED` as
    applicable".
    PRD §2.12: "the treaty checks (`ERR_TREATY_NOT_IN_FORCE` and
    `ERR_TREATY_CAP_EXHAUSTED`)" are among the business gates.

    Design: Corner/endpoints/manual_reinsurance_cession_is_rejected_when_the_treaty_is_not_in_force
    """
    book = issue_treaty_loan({
        "treaty_number": "TR-LATE",
        "inception_utc": "2026-07-01T00:00:00Z",
        "expiration_utc": "2028-07-01T00:00:00Z",
        "retention_per_claim_cents": 1_000_000,
        "exhaustion_per_claim_cents": 6_000_000,
        "aggregate_ceded_cap_cents": 5_000_000,
    })
    claim = file_claim(book, event_completed_utc="2026-05-01T00:00:00Z")
    begin_claim_review(claim["id"])
    approve_claim(claim["id"])
    loan = refresh_loan(book)

    response = api_client.create_cession({
        "claim_id": claim["id"],
        "ceded_amount_cents": 1_000_000,
        "expected_loan_version": loan["version"],
    }, UNDERWRITER)
    # PRD names the reason exhaustively ("exactly one of `NO_TREATY`,
    # `TREATY_NOT_IN_FORCE_AT_EVENT` or `AGGREGATE_CAP_EXHAUSTED`") but does not
    # state whether a manual cession recorded outside the treaty's window is
    # refused outright with `ERR_TREATY_NOT_IN_FORCE` or recorded as a REJECTED
    # cession carrying `TREATY_NOT_IN_FORCE_AT_EVENT`; §3.10's own sentence
    # requires the record to exist. Both PRD-faithful readings are accepted.
    assert response.status_code in (201, 409), response.text
    assert refresh_loan(book)["aggregate_ceded_cents"] == 0

    if response.status_code == 409:
        validate_error(response, ApiErrorId.ERR_TREATY_NOT_IN_FORCE)
        cessions = get_success_data(api_client.list_cessions(
            UNDERWRITER, params={"claim_id": claim["id"]}))
        assert cessions == []
    else:
        record = response.json()["data"]
        assert record["status"] == "REJECTED"
        assert record["rejected_reason"] == "TREATY_NOT_IN_FORCE_AT_EVENT"
        assert record["ceded_amount_cents"] == 0


def test_settlement_with_a_stale_observed_loan_version_is_refused():
    """PRD §2.9: "In each of the three cases the supplied value must equal the
    target loan's current `version`, and a mismatch is refused with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.9: "a loan's version legitimately advances between a claim's approval
    and its settlement — any delinquency report, amortization milestone or
    cancellation notice landing on the loan in that interval mutates the loan
    row".

    Design: Corner/cross_cutting_layers/cancelling_a_loan_with_a_stale_observed_version_is_refused
    """
    book = setup_loan_with_approved_claim()
    claim_id = book["claim_id"]
    claim = get_success_data(api_client.get_claim(claim_id, UNDERWRITER))
    stale_loan = refresh_loan(book)

    # A delinquency report mutates the loan row after the version was observed.
    file_delinquency_report(book, as_of_period="2026-08", months_delinquent=1)

    response = api_client.settle_claim(claim_id, {
        "settlement_option_kind": "CASH",
        "expected_claim_version": claim["version"],
        "expected_loan_version": stale_loan["version"],
    }, book["lender_headers"])
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)

    assert get_success_data(api_client.get_claim(claim_id, UNDERWRITER))["status"] == "APPROVED"
    assert get_success_data(api_client.list_cessions(
        UNDERWRITER, params={"claim_id": claim_id})) == []

    # The fresh version succeeds, so the refusal is attributable to the staleness.
    fresh_loan = refresh_loan(book)
    assert fresh_loan["version"] != stale_loan["version"]
    accepted = api_client.settle_claim(claim_id, {
        "settlement_option_kind": "CASH",
        "expected_claim_version": claim["version"],
        "expected_loan_version": fresh_loan["version"],
    }, book["lender_headers"])
    assert validate_success(accepted)["status"] == "SETTLED"


def test_serializing_the_rate_card_after_approval_leaves_the_loan_rate_untouched():
    """PRD §2.11: "The rate that the card carries becomes the application's
    `rate_bps_applied`, frozen at that moment, and the resulting loan inherits
    it."
    PRD §2.6: "A configuration rate supplied at input is preserved at its input
    precision".

    Design: Corner/cross_cutting_layers/adjusting_the_rate_card_after_approval_leaves_the_loan_rate_untouched
    """
    book = setup_loan()
    before = refresh_loan(book)
    assert before["rate_bps_applied"] == 62
    assert before["annual_premium_cents"] == 52_700

    # A new card for the same band and coverage at a different rate.
    api_client.create_rate_card({
        "master_policy_id": book["mp_id"],
        "credit_grade": "B",
        "ltv_band": "831_TO_85",
        "coverage_percent": 25,
        "premium_plan": "BPM",
        "rate_bps": 74,
        "min_borrower_reserves_months": 0,
    }, ADMIN)

    after = refresh_loan(book)
    assert after["rate_bps_applied"] == 62
    assert after["annual_premium_cents"] == 52_700

    application = get_success_data(api_client.get_application(book["application_id"], ADMIN))
    assert application["rate_bps_applied"] == 62

    cards = get_success_data(api_client.list_rate_cards(
        ADMIN, params={"master_policy_id": book["mp_id"]}))
    assert len(cards) == 2


def test_a_rejected_settlement_leaves_the_claim_and_its_ancestor_loan_untouched():
    """PRD §2.4: "`version` begins at 1 when the row is created and is incremented
    by exactly one every time the row is mutated — a state transition, a
    recomputed derived field, a refreshed flag, or an update to a nested
    collection all count."
    PRD §3.11: "a settlement presented from a stale reading of the loan is refused
    with `ERR_STALE_VERSION` (HTTP 412) rather than applied against a superseded
    picture".

    Design: Corner/consistency_model/supervision_after_a_rejected_write_shows_the_prior_state_unchanged
    """
    book = setup_loan_with_approved_claim()
    claim_id = book["claim_id"]
    setup_dispute(book, grounds="ORIGINATION_OMISSION")

    claim_before = get_success_data(api_client.get_claim(claim_id, UNDERWRITER))
    loan_before = refresh_loan(book)

    response = api_client.settle_claim(claim_id, {
        "settlement_option_kind": "CASH",
        "expected_claim_version": claim_before["version"],
        "expected_loan_version": loan_before["version"],
    }, book["lender_headers"])
    validate_error(response, ApiErrorId.ERR_CURTAILMENT_DISPUTE_OPEN)

    claim_after = get_success_data(api_client.get_claim(claim_id, UNDERWRITER))
    loan_after = refresh_loan(book)
    assert claim_after["status"] == "APPROVED"
    assert claim_after["settlement_amount_cents"] is None
    assert claim_after["net_claim_amount_cents"] == claim_before["net_claim_amount_cents"]
    assert claim_after["version"] == claim_before["version"]
    assert loan_after["version"] == loan_before["version"]
    assert loan_after["updated_at"] == loan_before["updated_at"]