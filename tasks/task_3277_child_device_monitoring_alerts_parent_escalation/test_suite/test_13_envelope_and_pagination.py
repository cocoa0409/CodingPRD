"""Response envelope and pagination contracts."""
import pytest

from test_helpers import (
    MISSING_UUID,
    TEST_USERS,
    create_child,
    create_family,
    is_iso8601_timestamp,
    make_parent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_success_envelope_shape(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body: { "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456", "api_request_timestamp":
    "2025-05-24T10:30:00.123Z", "limit": 10, "offset": 0, "total_count": 100,
    "has_more": true }, "response_type": "object" | "array", "data": { } }"
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/success_envelope_shape
    """
    fam, _parent = create_family(
        family_name="Fam EV", primary_contact_email="ev@x.com",
        primary_parent_name="Pat EV",
    )
    resp = api.get_family(fam["id"], ADMIN)
    body = resp.json()
    assert resp.status_code == 200
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
    assert body["response_type"] == "object"
    assert isinstance(body["data"], dict)
    assert body["data"]["id"] == fam["id"]


def test_error_envelope_shape(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format: { "meta": { "api_request_id":
    "req_RANDOMALPHANUM123456", "api_request_timestamp":
    "2025-05-24T10:30:00.123Z" }, "response_type": "error", "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING", "message": "A human-readable
    explanation of the error." } }"
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/error_envelope_shape
    """
    resp = api.get_family(MISSING_UUID, ADMIN)
    body = resp.json()
    assert resp.status_code == 404
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert isinstance(body["meta"]["api_request_id"], str)
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def test_list_pagination_defaults_and_bounds(api):
    """PRD §2.3: "All list endpoints accept two optional query parameters:
    `limit` and `offset`. The `limit` parameter defaults to 10, must be at least
    1, and must not exceed 100. The `offset` parameter defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`, where `total_count` is the total number of
    matching records and `has_more` indicates whether further records exist
    beyond the returned window."

    Design: Corner/endpoints/list_pagination_defaults_and_bounds
    """
    fam, parent = create_family(
        family_name="Fam PG", primary_contact_email="pg@x.com",
        primary_parent_name="Pat PG",
    )
    headers = make_parent_headers(parent["id"])
    for i in range(11):
        create_child(fam["id"], parent["id"], display_name=f"K{i + 1:02d}")

    page1, meta1 = validate_paginated(api.list_children(fam["id"], headers))
    assert len(page1) == 10
    assert meta1["total_count"] == 11
    assert meta1["has_more"] is True
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_children(fam["id"], headers, params={"offset": 10})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 11
    assert meta2["has_more"] is False
