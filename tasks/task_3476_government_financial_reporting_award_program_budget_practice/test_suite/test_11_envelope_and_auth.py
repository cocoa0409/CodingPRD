"""Fixed response envelope, authentication-first precedence, and
shape-before-role validation precedence (PRD §2.1, §2.2, §2.6).
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_member,
    government_payload,
    make_member_headers,
    set_logical_clock,
    setup_submitted_submission,
    make_government_contact_headers,
    validate_error,
)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers:
    `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring
    the capacity in which they act."
    PRD §2.1: "A request with either header missing or invalid, or whose role
    is not one of these six, is rejected with `ERR_UNAUTHENTICATED`."
    PRD §2.6: "1. **Authentication** — the headers of §2.1 are present and the
    role is declared, else `ERR_UNAUTHENTICATED`." (existence is rule 4, so
    the bogus id is never reached.)

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    set_logical_clock(api)

    resp = api.get_report_submission(NON_EXISTENT_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_forbidden_role_yields_to_shape_validation(api):
    """PRD §2.6: "A single request can fail several rules at once, so the
    system evaluates checks in a fixed order and reports the first failure
    encountered."
    PRD §2.6, rule 2: "the body parses, every required input field is present,
    enum fields hold declared values, and numeric ranges are respected:
    `page_count` must be positive, `requested_cents` must be positive,
    `pool_total_cents` and `per_applicant_cap_cents` must be positive,
    `closes_at` must lie after the current logical time, and a cycle's
    `submission_opens_at` must precede its `submission_deadline_at`, which
    must precede its `review_close_at`. Violations yield `ERR_VALIDATION`."
    PRD §2.6, rule 3: "the caller's role appears in the operation's authorized
    list, else `ERR_FORBIDDEN_ROLE`."

    Design: Corner/validations/forbidden_role_yields_to_shape_validation
    """
    set_logical_clock(api)
    member = create_member(api)
    headers = make_member_headers(member["id"])

    # Member is the wrong role for government registration AND the body is
    # missing required fields: shape is evaluated first.
    malformed = api.create_government(
        {"legal_name": "Broken Body Only"}, headers=headers
    )
    validate_error(malformed, ApiErrorId.ERR_VALIDATION, 400)

    # The same caller with a well-formed body reaches the role gate.
    forbidden = api.create_government(government_payload(), headers=headers)
    validate_error(forbidden, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_response_envelope_error_shape(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with `response_type` "error" and a `data` object
    carrying `error_id` and `message`.
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `message` provides a human-readable explanation of what
    went wrong."
    PRD §3.4: "The submission must be in `DRAFT`, else
    `ERR_SUBMISSION_STATE_INVALID`."

    Design: Corner/endpoints/response_envelope_error_shape
    """
    bundle = setup_submitted_submission(api)

    resp = api.submit_report_submission(
        bundle["submission"]["id"],
        headers=make_government_contact_headers(bundle["government"]["id"]),
    )
    error_data = validate_error(resp, ApiErrorId.ERR_SUBMISSION_STATE_INVALID)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(error_data["message"], str) and error_data["message"].strip()
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
