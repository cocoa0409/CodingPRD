"""Contractor entity creation and retrieval corner tests."""
from test_helpers import (
    ApiErrorId,
    create_contractor_payload,
    get_success_data,
    validate_error,
    validate_success,
)


def test_contractor_creation_applies_system_defaults(api, program_admin_headers):
    """PRD §3.1: "A fresh contractor record begins with `status` of `ACTIVE`, a
    `workmanship_score` of 100, a `complaint_score_24mo` of 0, a
    `lifetime_substantiated_count` of 0, and an `outstanding_liability_cents` of 0."
    PRD §2.4: "`version` (integer): starts at 1 on creation and increments on every
    mutation, including cascaded state changes triggered by the system rather than
    by a direct client write."

    Design: Corner/entities/contractor_creation_applies_system_defaults
    """
    resp = api.create_contractor(create_contractor_payload(legal_name="New Co", license_number="LIC-N"), program_admin_headers)
    data = validate_success(resp, expected_status=201)
    cid = data["id"]

    fetched = validate_success(api.get_contractor(cid, program_admin_headers))
    assert fetched["status"] == "ACTIVE"
    assert fetched["workmanship_score"] == 100
    assert fetched["complaint_score_24mo"] == 0
    assert fetched["lifetime_substantiated_count"] == 0
    assert fetched["outstanding_liability_cents"] == 0
    assert fetched["version"] == 1


def test_get_contractor_nonexistent_returns_not_found(api, program_admin_headers):
    """PRD §2.10: "The first reference that does not resolve to an existing resource
    terminates the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404), and the error
    message names the type of the missing resource."

    Design: Corner/entities/get_contractor_nonexistent_returns_not_found
    """
    resp = api.get_contractor("11111111-2222-3333-4444-555555555555", program_admin_headers)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


def test_contractor_create_missing_required_field_returns_invalid_request(api, program_admin_headers):
    """PRD §2.8: "Request-shape validation follows (`ERR_INVALID_REQUEST`), then
    existence of every referenced resource, validated left to right along path and
    body references (`ERR_RESOURCE_NOT_FOUND`)."

    Design: Corner/entities/contractor_create_missing_required_field_returns_invalid_request
    """
    payload = {
        "legal_name": "Bad Co",
        "license_number": "LIC-X",
        "license_expiry": "2030-01-01",
        "territory_codes": ["T1"],
    }
    resp = api.create_contractor(payload, program_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_contractor_create_client_supplied_version_input_ignored(api, program_admin_headers):
    """PRD §3.1: "A fresh contractor record begins with `status` of `ACTIVE`, a
    `workmanship_score` of 100, a `complaint_score_24mo` of 0, a
    `lifetime_substantiated_count` of 0, and an `outstanding_liability_cents` of 0."
    PRD §2.4: "`version` (integer): starts at 1 on creation and increments on every
    mutation, including cascaded state changes triggered by the system rather than
    by a direct client write."

    Design: Corner/entities/contractor_create_client_supplied_version_input_ignored
    """
    payload = create_contractor_payload(legal_name="Sneaky Co", license_number="LIC-SN")
    payload["version"] = 99
    payload["workmanship_score"] = 5
    resp = api.create_contractor(payload, program_admin_headers)
    data = validate_success(resp, expected_status=201)
    assert data["version"] == 1
    assert data["workmanship_score"] == 100


def test_error_response_envelope_shape(api, program_admin_headers):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`." PRD §2.2: "The `error_id` is a unique, machine-readable
    string that identifies the specific error. The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/endpoints/error_response_envelope_shape
    """
    resp = api.get_contractor("11111111-2222-3333-4444-555555555555", program_admin_headers)
    body = resp.json()
    assert body["response_type"] == "error"
    assert "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]
    assert body["data"]["error_id"] == "ERR_RESOURCE_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and len(body["data"]["message"]) > 0
