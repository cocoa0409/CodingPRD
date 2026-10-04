"""Breadth test for the error envelope shape."""

import test_helpers as th


def test_error_envelope_shape(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format: ... `"response_type": "error"`, `"data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING", "message": "A human-readable
    explanation of the error." }"
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/error_envelope_shape
    """
    resp = api.create_member({"external_ref": "env1"}, th.TEST_USERS["program_ops"])
    assert resp.status_code == 400
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_INVALID_REQUEST"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert body["meta"]["api_request_id"].startswith("req_")
    assert th.is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
