"""Corner queue: error-catalog claims — the 401 header guards and the error
envelope shape.
"""
from test_helpers import (
    ABSENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    headers_without_role,
    headers_without_user_id,
    validate_error,
)

PM = TEST_USERS["portfolio_manager_headers"]


def test_request_missing_header_role_returns_401():
    """PRD §2.1: "A missing `X-User-Role` header, or a value outside these six,
    is rejected with `ERR_MISSING_ROLE` (HTTP 401)."

    Design: Corner/errors/request_missing_header_role_returns_401
    """
    resp = api_client.list_brands(headers_without_role())
    validate_error(resp, ApiErrorId.ERR_MISSING_ROLE)


def test_request_missing_header_user_id_returns_401():
    """PRD §2.1: "A missing or empty `X-User-ID` header is rejected with
    `ERR_MISSING_USER_ID` (HTTP 401)."

    Design: Corner/errors/request_missing_header_user_id_returns_401
    """
    resp = api_client.list_brands(headers_without_user_id("PortfolioManager"))
    validate_error(resp, ApiErrorId.ERR_MISSING_USER_ID)


def test_error_envelope_carries_error_id_and_message():
    """PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/error_envelope_carries_error_id_and_message
    """
    resp = api_client.get_item(ABSENT_UUID, PM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
        "error responses must carry a non-empty human-readable message"
    )
    assert "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]
