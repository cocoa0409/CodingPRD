"""Customer registration, fetch, listing, and the success-envelope contract."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_customer,
    create_customer,
    create_customer_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

CO = TEST_USERS["contracts_officer_headers"]


def test_customer_create_success_system_fields(api):
    """PRD §3.1: "A `ContractsOfficer` registers each customer with a
    `legal_name`, a `credit_tier`, and a `tax_credit_flag`."
    PRD §2.4: "Every persisted resource carries `id` (a server-minted UUID with
    no type prefix), `created_at` and `updated_at` (ISO 8601 UTC timestamps with
    three fractional digits), and `version` (an integer that increments by 1 on
    every mutation of the resource)."

    Design: Corner/entities/customer_create_success_system_fields
    """
    resp = api.create_customer(
        create_customer_payload(
            legal_name="Acme Solar Dev", credit_tier="TIER_A", tax_credit_flag=True
        ),
        CO,
    )
    data = validate_success(resp, 201)
    assert_customer(data)
    assert data["credit_tier"] == "TIER_A"
    assert data["tax_credit_flag"] is True
    assert data["legal_name"] == "Acme Solar Dev"
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])


def test_customer_missing_credit_tier_rejected(api):
    """PRD §3.1: "A `ContractsOfficer` registers each customer with a
    `legal_name`, a `credit_tier`, and a `tax_credit_flag`."
    PRD §2.5: "Only then do business rules run: traceability and schema checks,
    then the domain constraints described in §3."

    Design: Corner/entities/customer_missing_credit_tier_rejected
    """
    resp = api.create_customer(
        {"legal_name": "No Tier Co", "tax_credit_flag": False}, CO
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_customer_get_not_found(api):
    """PRD §2.5: "Only after those pass does the server resolve referenced
    resources: path parameters and body references are validated left to right —
    line, then series, then customer, then reservation, then delivery, then lot,
    then attestation, then claim — and any missing reference yields
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/customer_get_not_found
    """
    resp = api.get_customer(NON_EXISTENT_UUID, CO)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_customer_list_pagination_envelope(api):
    """PRD §2.3: "List endpoints accept `limit` and `offset` query parameters.
    `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset`
    defaults to 0. List responses order results by `created_at` ascending. The
    `meta` object of every list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/customer_list_pagination_envelope
    """
    create_customer(legal_name="Alpha Co", credit_tier="TIER_A")
    create_customer(legal_name="Beta Co", credit_tier="TIER_B")
    create_customer(legal_name="Gamma Co", credit_tier="TIER_C", tax_credit_flag=True)

    resp = api.list_customers(CO, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"limit=2 must return exactly 2 rows, got {len(data)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    for row in data:
        assert_customer(row)


def test_response_envelope_success_shape(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."

    Design: Corner/endpoints/response_envelope_success_shape
    """
    resp = api.create_customer(
        create_customer_payload(
            legal_name="Acme Solar Dev", credit_tier="TIER_A", tax_credit_flag=True
        ),
        CO,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["response_type"] == "object"
    assert body["data"]["legal_name"] == "Acme Solar Dev"
    assert is_valid_uuid(body["data"]["id"])
