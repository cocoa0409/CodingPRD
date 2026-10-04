"""Corner queue — endpoint-level claims: pagination defaults and the response
envelope shape for success and error."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_contract_payload,
    setup_study_with_sites,
    validate_error,
    validate_paginated,
    validate_success,
)

AO = TEST_USERS["agency_officer_headers"]
SD = TEST_USERS["study_director_headers"]


def test_site_list_pagination_limit_offset(api):
    """PRD §2.3: "If not provided, it defaults to 10, with a minimum of 1 and
    maximum of 100. The `offset` parameter specifies the number of items to
    skip and defaults to 0."
    PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/site_list_pagination_limit_offset
    """
    ctx = setup_study_with_sites(site_specs=((10, "PROSPECTED"),) * 11)
    study_id = ctx["study"]["id"]

    data, meta = validate_paginated(api.list_sites(study_id, SD))
    assert len(data) == 10, "default page size is 10"
    assert meta["total_count"] == 11
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is True

    data, meta = validate_paginated(
        api.list_sites(study_id, SD, params={"limit": 10, "offset": 10})
    )
    assert len(data) == 1, "the 11th site is alone on the second page"
    assert meta["total_count"] == 11
    assert meta["has_more"] is False


def test_response_envelope_shape_success_and_error(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`." ... "The `response_type` is
    either \"object\" for a single resource or \"array\" for a list of
    resources."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error. The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/endpoints/response_envelope_shape_success_and_error
    """
    contract = validate_success(
        api.create_contract(
            create_contract_payload(
                agency_code="ACF-OPRE", title="T", award_amount_cents=90000000
            ),
            AO,
        ),
        201,
    )

    resp = api.get_contract(contract["id"], AO)
    data = validate_success(resp, 200)
    body = resp.json()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["response_type"] == "object"
    assert data["id"] == contract["id"]

    resp = api.get_contract(NON_EXISTENT_UUID, AO)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert err["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err["message"], str) and err["message"].strip()
