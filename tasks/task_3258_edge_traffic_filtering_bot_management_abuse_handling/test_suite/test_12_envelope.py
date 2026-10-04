"""Response envelopes: the error shape on rejection."""
from test_helpers import (
    validate_error, ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_error_envelope_shape_on_rejection(api):
    """PRD section 2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" and "The meta object for error responses contains
    only api_request_id and api_request_timestamp."

    Design: Corner/endpoints/error_envelope_shape_on_rejection
    """
    resp = api.get_zone(NON_EXISTENT_UUID, ADMIN)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert err["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err["message"], str) and len(err["message"]) > 0
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_")
    assert isinstance(meta.get("api_request_timestamp"), str)
