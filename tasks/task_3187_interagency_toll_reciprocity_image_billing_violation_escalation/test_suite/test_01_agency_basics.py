"""Agency basics: creation defaults, listing pagination, error checks."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_agency,
    create_agency_payload,
    create_away_agency_payload,
    create_home_agency,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

SO = TEST_USERS["settlement_officer_headers"]
AO = TEST_USERS["agency_ops_headers"]


def test_agency_create_returns_defaults_and_system_fields():
    """PRD §3.1: "The `settlement_currency` may be supplied and defaults to USD.
    A newly registered agency starts in `ACTIVE` status."
    PRD §2.4: "Every primary resource carries a system-minted `id` formatted
    as a UUID with no type prefix, a `created_at` timestamp, an `updated_at`
    timestamp, and an integer `version`."

    Design: Corner/entities/agency_create_returns_defaults_and_system_fields
    """
    resp = api_client.create_agency(
        create_agency_payload(
            agency_code="MTA", name="Metro Toll Alliance", reciprocity_fee_bps=125
        ),
        SO,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]
    agency = body["data"]
    assert_agency(agency)
    assert agency["settlement_currency"] == "USD"
    assert agency["status"] == "ACTIVE"
    assert agency["version"] == 1


def test_agencies_list_paginates_with_total_count_and_has_more():
    """PRD §2.3: "The `meta` object of every list response carries `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/agencies_list_paginates_with_total_count_and_has_more
    """
    create_home_agency(agency_code="A1", name="Agency One")
    create_home_agency(agency_code="A2", name="Agency Two")
    create_home_agency(agency_code="A3", name="Agency Three", home_state="PA")

    resp1 = api_client.list_agencies(AO, params={"limit": 2, "offset": 0})
    assert resp1.status_code == 200
    assert resp1.json()["response_type"] == "array"
    page1, meta1 = validate_paginated(resp1)
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    resp2 = api_client.list_agencies(AO, params={"limit": 2, "offset": 2})
    page2, meta2 = validate_paginated(resp2)
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_missing_auth_header_returns_400():
    """PRD §2.1: "A request with either header missing or malformed is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    agency = create_home_agency()
    resp = api_client.get_agency(agency["id"], headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
