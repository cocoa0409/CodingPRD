"""Claim review cycle and settlement-admissibility refusals."""
import pytest

from prd_bench_local_runner.testing import validate_success, validate_error, get_success_data

from test_helpers import (
    ApiErrorId, api_client, setup_loan_with_filed_claim,
    setup_loan_with_approved_claim, setup_loan_with_claim_in_review,
    setup_settled_claim, file_claim, begin_claim_review, refresh_loan,
    settle_claim, UNDERWRITER,
)


def test_reconsideration_returns_a_denied_claim_to_the_filed_queue():
    """PRD §3.7: "The same reconsideration operation is available from `DENIED`,
    where it re-opens the denial and returns the claim to `FILED` — which is to
    say that a denial is not the end of a claim's life".

    Design: Difficulty/non_linear_state_machine/claim_reconsideration_cycle_reopens_denied_claims
    """
    book = setup_loan_with_claim_in_review()
    claim_id = book["claim_id"]
    get_success_data(api_client.deny_claim(claim_id, {"denial_reason": "Title chain incomplete"},
                                           UNDERWRITER))

    response = api_client.reconsider_claim(
        claim_id, {"reason": "Lender supplied the missing title chain"},
        book["lender_headers"])
    data = validate_success(response)
    assert data["status"] == "FILED"

    # The cycle can then be traversed a second time.
    again = api_client.begin_claim_review(claim_id, UNDERWRITER)
    assert validate_success(again)["status"] == "UNDER_REVIEW"


def test_second_reconsideration_from_the_filed_re_entry_state_is_refused():
    """PRD §3.7: "From `UNDER_REVIEW` the lender may seek reconsideration, which
    returns the claim to `FILED` and re-enters it in the review queue".
    PRD §2.10: "Only `SETTLED` and `RESCINDED` are terminal, and even those are
    reachable more than once: a denied claim can be re-opened, so denial is not
    terminal."

    Design: Difficulty/non_linear_state_machine/claim_reconsideration_cycle_reopens_denied_claims
    """
    book = setup_loan_with_claim_in_review()
    claim_id = book["claim_id"]
    get_success_data(api_client.deny_claim(claim_id, {"denial_reason": "Title chain incomplete"},
                                           UNDERWRITER))
    get_success_data(api_client.reconsider_claim(
        claim_id, {"reason": "Lender supplied the missing title chain"},
        book["lender_headers"]))

    # FILED declares no reconsideration transition, so re-entry is refused.
    response = api_client.reconsider_claim(
        claim_id, {"reason": "Second attempt"}, book["lender_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    assert get_success_data(api_client.get_claim(claim_id, UNDERWRITER))["status"] == "FILED"


def test_settling_an_already_settled_claim_is_refused():
    """PRD §3.11: "Settlement is admissible from `APPROVED` and from nowhere
    else."
    PRD §2.10: "A claim begins at `FILED` and moves through `UNDER_REVIEW`,
    `APPROVED`, `DENIED`, `SETTLED` and `RESCINDED`."

    Design: Corner/state_machines/settling_an_already_settled_claim_is_rejected
    """
    book = setup_settled_claim(option="CASH")
    claim_id = book["claim_id"]
    settled = get_success_data(api_client.get_claim(claim_id, UNDERWRITER))
    loan = refresh_loan(book)
    assert settled["status"] == "SETTLED"

    response = api_client.settle_claim(claim_id, {
        "settlement_option_kind": "CASH",
        "expected_claim_version": settled["version"],
        "expected_loan_version": loan["version"],
    }, book["lender_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    still = get_success_data(api_client.get_claim(claim_id, UNDERWRITER))
    assert still["status"] == "SETTLED"
    assert still["version"] == settled["version"]

    cessions = get_success_data(api_client.list_cessions(
        UNDERWRITER, params={"claim_id": claim_id}))
    assert len(cessions) == 1, "no second cession may be written by a refused settlement"


def test_settlement_option_outside_the_four_priced_kinds_is_refused():
    """PRD §3.9: "The option named by `settlement_option_kind` must be one of the
    four rows priced on the claim; anything else is refused with
    `ERR_SETTLEMENT_OPTION_UNKNOWN`."

    Design: Difficulty/non_linear_state_machine/claim_reconsideration_cycle_reopens_denied_claims
    """
    book = setup_loan_with_approved_claim()
    claim_id = book["claim_id"]
    claim = get_success_data(api_client.get_claim(claim_id, UNDERWRITER))
    loan = refresh_loan(book)

    response = api_client.settle_claim(claim_id, {
        "settlement_option_kind": "WIRE_TRANSFER",
        "expected_claim_version": claim["version"],
        "expected_loan_version": loan["version"],
    }, book["lender_headers"])
    validate_error(response, ApiErrorId.ERR_SETTLEMENT_OPTION_UNKNOWN)

    assert get_success_data(api_client.get_claim(claim_id, UNDERWRITER))["status"] == "APPROVED"


def test_claim_can_be_approved_after_the_reopened_review_completes():
    """PRD §3.7: "a lender that has been refused may put the claim back into the
    queue with an explanation".
    PRD §3.8: "Only when those gates pass does the arithmetic run, the rates
    freeze, the four option rows are created, and the claim advance to
    `APPROVED`".

    Design: Difficulty/non_linear_state_machine/claim_reconsideration_cycle_reopens_denied_claims
    """
    book = setup_loan_with_claim_in_review()
    claim_id = book["claim_id"]
    get_success_data(api_client.deny_claim(claim_id, {"denial_reason": "Title chain incomplete"},
                                           UNDERWRITER))
    get_success_data(api_client.reconsider_claim(
        claim_id, {"reason": "Lender supplied the missing title chain"},
        book["lender_headers"]))
    get_success_data(api_client.begin_claim_review(claim_id, UNDERWRITER))

    response = api_client.approve_claim(claim_id, UNDERWRITER)
    data = validate_success(response)
    assert data["status"] == "APPROVED"
    assert data["net_claim_amount_cents"] == 6_098_400