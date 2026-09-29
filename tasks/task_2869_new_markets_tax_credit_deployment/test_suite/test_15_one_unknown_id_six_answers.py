"""One unknown identifier, offered to six collections, gets six different codes.

The not-found code is chosen from the collection addressed by the path, never
from a global search for the identifier.
"""
from test_helpers import (
    ApiErrorId,
    SETUP_CLOCK,
    make_agency_headers,
    setup_deployed_investment,
    validate_error,
)

UNKNOWN_ID = "00000000-0000-4000-8000-0000000000c1"


def test_the_same_unknown_id_answers_with_each_collections_own_code(api):
    """Nothing in the database is empty, and nothing owns this identifier.

    PRD: "The first identifier that resolves to nothing decides the response, and
    each resource has its own not-found code: `ERR_CDE_NOT_FOUND`,
    `ERR_ALLOCATION_AWARD_NOT_FOUND`, `ERR_CENSUS_TRACT_NOT_FOUND`,
    `ERR_QALICB_NOT_FOUND`, `ERR_INVESTMENT_FUND_NOT_FOUND`, `ERR_QEI_NOT_FOUND`,
    `ERR_QLICI_NOT_FOUND`, `ERR_REINVESTMENT_OBLIGATION_NOT_FOUND`,
    `ERR_CBA_NOT_FOUND` and `ERR_UNWIND_NOT_FOUND`, all HTTP 404."

    PRD: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    PRD: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/every_path_entity_has_its_own_distinct_not_found_code
    """
    scenario = setup_deployed_investment(
        api, clock=SETUP_CLOCK, certification_suffix=127
    )
    assert scenario.qlici["status"] == "DEPLOYED", "the database is populated"
    headers = make_agency_headers()

    cases = (
        (
            "cdes",
            api.get_cde(UNKNOWN_ID, headers),
            ApiErrorId.ERR_CDE_NOT_FOUND.value,
        ),
        (
            "investment-funds",
            api.get_investment_fund(UNKNOWN_ID, headers),
            ApiErrorId.ERR_INVESTMENT_FUND_NOT_FOUND.value,
        ),
        (
            "qlicis",
            api.get_qlici(UNKNOWN_ID, headers),
            ApiErrorId.ERR_QLICI_NOT_FOUND.value,
        ),
        (
            "reinvestment-obligations",
            api.get_reinvestment_obligation(UNKNOWN_ID, headers),
            ApiErrorId.ERR_REINVESTMENT_OBLIGATION_NOT_FOUND.value,
        ),
        (
            "community-benefits-agreements",
            api.get_community_benefits_agreement(UNKNOWN_ID, headers),
            ApiErrorId.ERR_CBA_NOT_FOUND.value,
        ),
        (
            "unwind-transactions",
            api.get_unwind_transaction(UNKNOWN_ID, headers),
            ApiErrorId.ERR_UNWIND_NOT_FOUND.value,
        ),
    )

    for collection, response, expected_error_id in cases:
        validate_error(response, expected_error_id, 404)
        body = response.json()
        assert body["response_type"] == "error", collection
        assert body["data"]["message"], f"{collection} must explain the failure"

    answered = {response.json()["data"]["error_id"] for _, response, _ in cases}
    assert len(answered) == 6, "the same identifier drew six different codes"
