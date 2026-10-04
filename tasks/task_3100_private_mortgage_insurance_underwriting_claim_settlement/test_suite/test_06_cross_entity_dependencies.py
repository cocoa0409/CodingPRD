"""Cross-entity state dependencies: the delinquency gate, the relief bar and
the validation-report cascade."""
import pytest

from prd_bench_local_runner.testing import validate_success, validate_error, get_success_data

from test_helpers import (
    ApiErrorId, api_client, setup_loan, setup_two_loans, file_delinquency_report,
    file_servicer_cancellation, refresh_loan, add_servicer, setup_dispute,
    setup_approved_claim_for_loan, setup_guaranteed_relief_loan,
    make_servicer_headers, amortize, begin_claim_review, file_claim,
    AT80_UPB_CENTS, AT80_MAX_REFUND_CENTS, ADMIN, UNDERWRITER,
)

FULL_ACTIVITIES = [
    {"activity_kind": "OUTREACH_SENT", "outcome": "COMPLETED",
     "activity_utc": "2026-01-10T00:00:00Z"},
    {"activity_kind": "INTAKE_COMPLETE", "outcome": "COMPLETED",
     "activity_utc": "2026-01-20T00:00:00Z"},
    {"activity_kind": "EVALUATION_COMPLETE", "outcome": "COMPLETED",
     "activity_utc": "2026-01-25T00:00:00Z"},
    {"activity_kind": "PROGRAM_ACCEPTED", "outcome": "COMPLETED",
     "activity_utc": "2026-02-01T00:00:00Z"},
]


def test_servicer_cancellation_requires_the_flag_written_by_reporting():
    """PRD §3.6: "A notice whose `request_kind` is `SERVICER_LOSS_MITIGATION_FAILURE`
    requires the loan's `claim_blocked` flag to be true; a servicer-loss-mitigation
    cancellation of a loan that has not actually failed its loss-mitigation
    standard is refused with `ERR_CANCELLATION_NOT_PERMITTED`."

    Design: Difficulty/cross_entity_state_dependency/loan_cancellation_requires_eligibility_flag_written_by_reporting
    """
    book = setup_two_loans()
    # Both loans must be in the AT_80 window before a servicer cancellation is
    # admissible: PRD §3.6 refuses a notice whose "computed maximum refund is
    # zero", so the flag is the only remaining variable that can separate them.
    amortize(book, AT80_UPB_CENTS, loan_id=book["loan_a_id"])
    amortize(book, AT80_UPB_CENTS, loan_id=book["loan_b_id"])
    # One loan fails the PARTICIPATION_COMPLETE standard, the other does not.
    file_delinquency_report(
        book, loan_id=book["loan_a_id"], as_of_period="2026-01", months_delinquent=2,
        loss_mitigation_activities=[
            {"activity_kind": "OUTREACH_SENT", "outcome": "COMPLETED",
             "activity_utc": "2026-01-10T00:00:00Z"}])
    file_delinquency_report(
        book, loan_id=book["loan_b_id"], as_of_period="2026-01", months_delinquent=2,
        loss_mitigation_activities=FULL_ACTIVITIES)

    deficient = refresh_loan(book, book["loan_a_id"])
    clean = refresh_loan(book, book["loan_b_id"])
    assert deficient["claim_blocked"] is True
    assert clean["claim_blocked"] is False

    # The deficient loan's cancellation is admissible.
    file_servicer_cancellation(book, loan_id=book["loan_a_id"],
                               evidence_cents=AT80_MAX_REFUND_CENTS)
    assert refresh_loan(book, book["loan_a_id"])["coverage_status"] == "PENDING_CANCELLATION"

    # The clean loan's identical cancellation is refused on the flag alone.
    response = api_client.create_cancellation_notice(
        book["loan_b_id"], {
            "request_kind": "SERVICER_LOSS_MITIGATION_FAILURE",
            "requested_by_role": "SERVICER",
            "notice_utc": "2026-09-01T00:00:00Z",
            "evidence_cents": AT80_MAX_REFUND_CENTS,
            "applied_utc": "2026-09-01T00:00:00Z",
        }, book["servicer_headers"])
    validate_error(response, ApiErrorId.ERR_CANCELLATION_NOT_PERMITTED)

    final = refresh_loan(book, book["loan_b_id"])
    assert final["coverage_status"] == "ACTIVE"
    assert len(get_success_data(
        api_client.list_cancellation_notices(book["loan_b_id"], UNDERWRITER))) == 0


def test_delinquency_report_from_a_non_designated_servicer_is_refused():
    """PRD §3.4: "The reporting servicer must also be the loan's own designated
    servicer; a report from any other organization is refused with
    `ERR_SERVICER_NOT_DESIGNATED`."

    Design: Difficulty/cross_entity_state_dependency/loan_cancellation_requires_eligibility_flag_written_by_reporting
    """
    book = setup_loan()
    other = add_servicer(servicer_name="Redline Servicing")

    response = api_client.create_delinquency_report({
        "loan_id": book["loan_id"],
        "servicer_id": other["id"],
        "as_of_period": "2026-01",
        "delinquency_class": "A",
        "months_delinquent": 2,
        "loss_mitigation_activities": [],
    }, make_servicer_headers(other["id"]))
    validate_error(response, ApiErrorId.ERR_SERVICER_NOT_DESIGNATED)

    assert len(get_success_data(api_client.list_loan_delinquency_reports(
        book["loan_id"], UNDERWRITER))) == 0


def test_rescission_decision_is_barred_when_relief_has_attached():
    """PRD §3.11: "It is barred absolutely on a loan whose relief has attached: a
    `RESCISSION_GRANTED` decision attempted where the loan's
    `rescission_relief_status` is `GUARANTEED` is refused with
    `ERR_RESCISSION_BARRED_RELIEF_ATTACHED`".

    Design: Difficulty/cross_entity_state_dependency/rescission_decision_requires_relief_status_from_the_loan_domain
    """
    book = setup_guaranteed_relief_loan()
    claim = file_claim(book)
    # UNDER_REVIEW is the only state from which PRD 3.7 declares a denial, and a
    # denial is the precondition the rescission decision itself requires.
    begin_claim_review(claim["id"])
    get_success_data(api_client.deny_claim(
        claim["id"], {"denial_reason": "Origination defect asserted"}, UNDERWRITER))
    dispute = setup_dispute(book, grounds="ORIGINATION_OMISSION", in_review=True,
                           claim_id=claim["id"])

    loan = refresh_loan(book)
    assert loan["rescission_relief_status"] == "GUARANTEED"

    response = api_client.decide_dispute(dispute["id"], {
        "decision": "RESCISSION_GRANTED",
        "decision_reason": "Origination omission established",
    }, ADMIN)
    validate_error(response, ApiErrorId.ERR_RESCISSION_BARRED_RELIEF_ATTACHED)

    assert get_success_data(api_client.get_claim(claim["id"], UNDERWRITER))["status"] == "DENIED"
    assert get_success_data(api_client.get_dispute(dispute["id"], ADMIN))["status"] == "UNDER_REVIEW"


def test_rescission_decision_resolves_when_relief_status_is_none():
    """PRD §3.11: "A decision of `RESCISSION_GRANTED` carries an additional
    precondition of its own: the targeted claim must currently be in `DENIED` or
    in `SETTLED`".
    PRD §3.11: "It drives the targeted claim into `RESCINDED`, drives the loan's
    coverage axis into `CANCELLED`".

    Design: Difficulty/cross_entity_state_dependency/rescission_decision_requires_relief_status_from_the_loan_domain
    """
    book = setup_loan()
    claim = file_claim(book)
    # UNDER_REVIEW is the only state from which PRD 3.7 declares a denial, and a
    # denial is the precondition the rescission decision itself requires.
    begin_claim_review(claim["id"])
    get_success_data(api_client.deny_claim(
        claim["id"], {"denial_reason": "Origination defect asserted"}, UNDERWRITER))
    dispute = setup_dispute(book, grounds="ORIGINATION_OMISSION", in_review=True,
                           claim_id=claim["id"])

    loan = refresh_loan(book)
    assert loan["rescission_relief_status"] == "NONE"

    resolved = validate_success(api_client.decide_dispute(dispute["id"], {
        "decision": "RESCISSION_GRANTED",
        "decision_reason": "Origination omission established",
    }, ADMIN))
    assert resolved["status"] == "RESOLVED"
    assert resolved["decision"] == "RESCISSION_GRANTED"

    assert get_success_data(api_client.get_claim(claim["id"], UNDERWRITER))["status"] == "RESCINDED"
    final = refresh_loan(book)
    assert final["coverage_status"] == "CANCELLED"
    assert final["termination_reason"] == "NONE"


def test_validation_report_rewrites_the_verified_value_and_feeds_the_dispute_decision():
    """PRD §3.6: "Filing the report writes the verified figures onto the loan as
    `verified_property_value_cents` and `verified_loan_amount_cents`".
    PRD §3.11: "`UPHELD` is the lender's case succeeding on the arithmetic: the
    insurer re-runs the whole claim computation against the targeted claim and
    adds to that claim's net amount whatever positive difference the recomputation
    produced".

    Design: Difficulty/transitive_cascade/validation_report_chain_changes_dispute_decision_outcome
    """
    book = setup_loan()
    claim = setup_approved_claim_for_loan(book)
    dispute = setup_dispute(book, grounds="VALUATION_ERROR", in_review=True)

    report = get_success_data(api_client.create_external_report(
        book["loan_id"], {
            "verified_loan_amount_cents": 34_000_000,
            "verified_property_value_cents": 39_000_000,
            "post_origination_value_cents": 0,
            "occupancy_reported": "OWNER_OCCUPIED",
            "independent_validation_completed_utc": "2026-09-01T00:00:00Z",
        }, UNDERWRITER))
    assert report["validated_ltv"] == 87.1795
    assert report["occupancy_materially_differs"] is False

    loan = refresh_loan(book)
    assert loan["verified_property_value_cents"] == 39_000_000
    assert loan["verified_loan_amount_cents"] == 34_000_000

    resolved = validate_success(api_client.decide_dispute(dispute["id"], {
        "decision": "UPHELD",
        "decision_reason": "Originated value unsupported by the validated figure",
    }, ADMIN))
    assert resolved["status"] == "RESOLVED"
    assert resolved["decision"] == "UPHELD"

    # A dispute can raise a claim's figure but can never lower it.
    decided_claim = get_success_data(api_client.get_claim(claim["id"], UNDERWRITER))
    assert decided_claim["net_claim_amount_cents"] >= claim["net_claim_amount_cents"]