"""Endpoint probes: the fixed success and error envelopes.

Every 2xx wraps its payload in meta + response_type + data, with a
req_-prefixed request id and an ISO 8601 UTC timestamp rendered to three
fractional digits; every 4xx answers response_type "error" with
data.error_id and data.message, and its meta holds exactly the two request
fields.
"""

import re

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_case,
    create_court,
    is_iso8601_timestamp,
    make_case_payload,
    validate_error,
    validate_success,
)

_THREE_FRACTIONAL_DIGITS = re.compile(r"\.\d{3}(Z|[+-]\d{2}:?\d{2})$")


def test_success_envelope_shape_on_case_create(api, admin_headers):
    """PRD §4: "Operations that create new resources return `201 Created`; operations that modify an existing resource or record an action against it — docketing, completing, deciding, ruling, marking, closing, recalendaring, setting coverage — return `200 OK`, as does the clock-setting capability."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    Design: Corner/endpoints/success_envelope_shape_on_case_create
    """
    court = create_court()
    resp = api.create_case(make_case_payload(court["id"]), headers=admin_headers)
    case = validate_success(resp, 201)
    assert_case(case)  # id, created_at, updated_at, version present and typed
    assert case["version"] == 1

    body = resp.json()
    assert body["response_type"] == "object", (
        "a single created resource is an object response"
    )
    assert body["data"]["id"] == case["id"]
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        "the request id carries the req_ prefix"
    )
    timestamp = meta["api_request_timestamp"]
    assert is_iso8601_timestamp(timestamp)
    assert _THREE_FRACTIONAL_DIGITS.search(timestamp), (
        "the request timestamp renders with three fractional digits"
    )


def test_error_envelope_shape_on_not_found(api, admin_headers):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format"
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
    PRD §2.6: "3. **Existence (HTTP 404).** Path identifiers and body foreign-key identifiers must resolve to existing resources, validated left-to-right: path parameters first, in the order they appear in the path, then body identifiers in the endpoint's declared input order."

    Design: Corner/endpoints/error_envelope_shape_on_not_found
    """
    resp = api.get_court(NON_EXISTENT_UUID, headers=admin_headers)
    validate_error(resp, ApiErrorId.ERR_COURT_NOT_FOUND)

    body = resp.json()
    assert resp.status_code == 404
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_COURT_NOT_FOUND"
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"].strip(), "the message is a non-empty explanation"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        "the error meta carries only the two request fields"
    )
