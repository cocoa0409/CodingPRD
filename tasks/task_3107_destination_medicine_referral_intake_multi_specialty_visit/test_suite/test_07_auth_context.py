"""Authentication-context validation: missing user headers."""
from test_helpers import (
    ApiErrorId,
    create_specialty_service_payload,
    set_clock,
    validate_error,
)


def test_missing_user_context_headers_rejected(api):
    """PRD §2.1: "Every request to the API must carry two HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the
    capacity in which they act. A request in which either header is missing
    or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_rejected_before_role_check
    """
    set_clock()
    resp = api.create_specialty_service(
        create_specialty_service_payload(code="X", name="X"),
        {},  # no X-User-ID / X-User-Role headers at all
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_missing_role_header_rejected(api):
    """PRD §2.1: "A request in which either header is missing or empty is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_rejected_before_role_check
    """
    set_clock()
    resp = api.create_specialty_service(
        create_specialty_service_payload(code="X", name="X"),
        {"X-User-ID": "admin-pat", "Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
