"""Immediate read-after-write consistency, required fields and not-found resolution."""
from test_helpers import (
    ANY,
    ApiErrorId,
    NON_EXISTENT_UUID,
    get_broker,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.fixtures import (
    NAMED_QC_ANALYST_ID,
    broker_version,
    open_qc_review,
    record_decision,
    setup_conditional_approval_loan,
    setup_full_scenario,
    setup_loan_in_state,
    underwrite_loan,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_broker_headers,
    make_compliance_officer_headers,
    make_underwriter_headers,
)


def test_funding_response_carries_every_derived_broker_field_immediately(api):
    """PRD §2.8: "`updated_at` is an ISO 8601 UTC timestamp with three fractional digits marking
    the last mutation, and it is refreshed on any change to the resource's properties."
    PRD §3.8: "Funding moves the loan to `FUNDED`, adds the loan's `loan_amount_cents` to the
    broker's `rolling_funded_volume_cents`, recomputes `active_loan_count`, and increments the
    broker's `version` by one."

    Design: Corner/consistency_model/funding_response_reflects_every_derived_broker_field_immediately
    """
    scenario = setup_loan_in_state("CLEAR_TO_CLOSE")
    loan_id = scenario["loan_id"]
    b = scenario["broker_id"]
    version_before = get_broker(b)["version"]

    funded = validate_success(api_client.fund_loan(loan_id, make_underwriter_headers()))
    assert funded["status"] == "FUNDED"
    assert funded["id"] == loan_id
    assert funded["broker_id"] == b

    broker_now = get_broker(b)
    assert broker_now["rolling_funded_volume_cents"] == 40_000_000
    assert broker_now["active_loan_count"] == 0, "FUNDED is not an active status"
    assert broker_now["total_active_compensation_commitment_cents"] == 0, (
        "a FUNDED loan leaves the in-flight commitment cohort"
    )
    assert broker_now["version"] > version_before


def test_loan_read_with_an_unknown_id_returns_loan_not_found(api):
    """PRD §2.11: "The catalogue of not-found identifiers is `ERR_BROKER_NOT_FOUND`,
    `ERR_RATE_SHEET_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_ELIGIBILITY_NOT_FOUND`,
    `ERR_PLAN_NOT_FOUND` and `ERR_ESCALATION_NOT_FOUND`."
    PRD §2.11: "it rejects the request with the `404 Not Found` error that corresponds to the
    first identifier in that order which does not resolve."

    Design: Corner/entities/loan_submission_get_with_unknown_id_returns_loan_not_found
    """
    response = api_client.get_loan_submission(NON_EXISTENT_UUID, TEST_USERS["any_headers"])
    validate_error(response, ApiErrorId.ERR_LOAN_NOT_FOUND, expected_status=404)
    body = response.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == ApiErrorId.ERR_LOAN_NOT_FOUND
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]


def test_loan_read_with_an_unknown_id_is_not_a_malformed_body(api):
    """PRD §2.11: "it rejects the request with the `404 Not Found` error that corresponds to the
    first identifier in that order which does not resolve."
    PRD §2.11: "A `resolution_note` shorter than ten characters, a defect review created with
    `remediation_status` `OPEN`, an unknown enum member and a missing required field all travel
    through `ERR_INVALID_REQUEST`."

    Design: Corner/entities/loan_submission_get_with_unknown_id_returns_loan_not_found
    """
    for resource, expected in (
        ("brokers", ApiErrorId.ERR_BROKER_NOT_FOUND),
        ("pricing-quotes", ApiErrorId.ERR_QUOTE_NOT_FOUND),
        ("rate-sheets", ApiErrorId.ERR_RATE_SHEET_NOT_FOUND),
    ):
        response = api.get(f"/wholesale-channel/{resource}/{NON_EXISTENT_UUID}",
                           headers=TEST_USERS["any_headers"])
        validate_error(response, expected, expected_status=404)


def test_loan_submission_missing_lock_expires_at_is_a_malformed_body(api):
    """PRD §3.6: "A `BrokerUser` creates a `LoanSubmission` against its own brokerage by
    supplying `broker_id`, `pricing_quote_id`, `borrower_name`, `property_state`,
    `loan_amount_cents`, `lock_expires_at`"
    PRD §2.11: "an unknown enum member and a missing required field all travel through
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/loan_submission_create_missing_lock_expires_at_returns_invalid_request
    """
    scenario = setup_full_scenario()
    b = scenario["broker_id"]

    response = api_client.create_loan_submission(
        {
            "broker_id": b,
            "pricing_quote_id": scenario["quote"]["id"],
            "borrower_name": "Omission Borrower",
            "property_state": "TX",
            "loan_amount_cents": 40_000_000,
            "compensation_election": "LENDER_PAID",
            "comp_plan_id": scenario["plan"]["id"],
        },
        make_broker_headers(b),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    rows, meta = validate_paginated(
        api_client.list_loan_submissions(TEST_USERS["any_headers"], {"broker_id": b})
    )
    assert meta["total_count"] == 1, "only the scenario's own loan exists"
    assert all(row["borrower_name"] != "Omission Borrower" for row in rows)


def test_loan_submission_omitting_the_optional_election_still_submits(api):
    """PRD §3.6: "optionally `competitor_channel_identifier`, `compensation_election` and
    `comp_plan_id`"
    PRD §3.6: "While the election is still `UNDECIDED`, both are 0."

    Design: Corner/entities/loan_submission_create_missing_lock_expires_at_returns_invalid_request
    """
    scenario = setup_full_scenario()
    b = scenario["broker_id"]

    submitted = validate_success(
        api_client.create_loan_submission(
            {
                "broker_id": b,
                "pricing_quote_id": scenario["quote"]["id"],
                "borrower_name": "Undecided Election Borrower",
                "property_state": "TX",
                "loan_amount_cents": 30_000_000,
                "lock_expires_at": "2027-01-01T00:00:00Z",
            },
            make_broker_headers(b),
        ),
        expected_status=201,
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["compensation_election"] == "UNDECIDED"
    assert submitted["lender_paid_comp_cents"] == 0
    assert submitted["borrower_paid_comp_cents"] == 0

    # The broker commitment is unchanged: an undecided loan contributes nothing.
    broker = get_broker(b)
    assert broker["total_active_compensation_commitment_cents"] == 250_000
    assert broker["active_loan_count"] == 2