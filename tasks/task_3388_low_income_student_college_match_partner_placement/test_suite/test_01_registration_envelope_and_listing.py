"""Registration defaults, enum validation, not-found handling, the error
envelope shape, and college directory pagination."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    UNKNOWN_UUID,
    assert_partner_college,
    assert_student,
    create_college,
    create_college_payload,
    create_student,
    expect_created,
    expect_error,
    validate_paginated,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_ANON = TEST_USERS["anonymous_headers"]


def test_student_create_returns_defaults_and_system_fields(api):
    """PRD §3.1: "Every new student begins at `student_stage` `PROSPECT`, and
    the stage ladder — `PROSPECT` → `APPLICANT` → `FINALIST` → `MATCHED` →
    `ENROLLED` — is advanced only by the workflow cascades narrated later in
    this section, never set directly."
    PRD §2.5: "`id` is a server-minted UUID with no type prefix. `created_at`
    records creation time as an ISO 8601 UTC timestamp with three fractional
    digits; `updated_at` follows the same format and refreshes on every
    mutation of the resource."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
    timestamp with three fractional digits."

    Design: Corner/entities/student_create_returns_defaults_and_system_fields
    """
    payload = {
        "email": "stage-prospect@example.com",
        "full_name": "Stu One",
        "state_code": "TX",
        "source": "SELF",
    }
    resp = api.create_student(payload, _ANON)
    data = expect_created(resp, payload)
    assert_student(data)
    assert data["student_stage"] == "PROSPECT", (
        f"new student must begin at PROSPECT, got {data['student_stage']!r}"
    )
    assert data["id"] and data["created_at"] and data["updated_at"]
    assert isinstance(data["version"], int) and data["version"] >= 1
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"], "meta.api_request_id must be present"
    assert body["meta"]["api_request_timestamp"], (
        "meta.api_request_timestamp must be present"
    )


def test_register_duplicate_email_returns_email_taken(api):
    """PRD §3.1: "The `email` must be unique across students; a duplicate is
    rejected with `ERR_EMAIL_TAKEN`."

    Design: Corner/validations/register_duplicate_email_returns_email_taken
    """
    create_student(email="dupe@example.com")
    payload = {
        "email": "dupe@example.com",
        "full_name": "Copy Cat",
        "state_code": "CA",
        "source": "SELF",
    }
    resp = api.create_student(payload, _ANON)
    expect_error(resp, ApiErrorId.ERR_EMAIL_TAKEN, payload)


def test_college_create_with_invalid_aid_policy_returns_invalid_request(api):
    """PRD §3.1: "A college is registered with a `name`, an `aid_policy` of
    either `NO_LOAN` or `MINIMAL_LOAN`, a `min_academic_index` floor that an
    applicant's academic index must reach before the college can take them in
    the match, a `match_slots` quota of zero or more binding-match slots per
    cycle, and `coa_cents`, the annual cost of attendance in cents."
    PRD §2.10: "1. Request well-formedness — required fields present, correct
    types, enum fields carrying a declared member — `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/college_create_with_invalid_aid_policy_returns_invalid_request
    """
    payload = create_college_payload(name="Bad Policy U", aid_policy="FREE_RIDE")
    resp = api.create_college(payload, _ADMIN)
    expect_error(resp, ApiErrorId.ERR_INVALID_REQUEST, payload)


def test_application_get_nonexistent_returns_not_found(api):
    """PRD §2.10: "4. Existence of every path parameter, resolved left to
    right — `ERR_NOT_FOUND` (HTTP 404) at the first unresolved identifier."

    Design: Corner/entities/application_get_nonexistent_returns_not_found
    """
    resp = api.get_application(UNKNOWN_UUID, _ADMIN)
    expect_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_error_envelope_shape_for_not_found(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what
    went wrong."

    Design: Corner/errors/error_envelope_shape_for_not_found
    """
    resp = api.get_college(UNKNOWN_UUID, _ADMIN)
    err = expect_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert err["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err["message"], str) and err["message"], (
        "error data.message must be a non-empty string"
    )
    body = resp.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {
        "api_request_id",
        "api_request_timestamp",
    }, f"error meta must carry exactly the two request fields, got {body['meta']!r}"


def test_colleges_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "`limit` caps the number of items returned; when omitted it
    defaults to 10, and it accepts a minimum of 1 and a maximum of 100.
    `offset` skips a number of items from the start of the result set and
    defaults to 0."
    PRD §2.3: "List responses carry four pagination fields in the envelope's
    `meta` object: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/colleges_list_paginates_with_total_count_and_has_more
    """
    create_college(name="Page U 1")
    create_college(name="Page U 2")
    create_college(name="Page U 3")
    page1, meta1 = validate_paginated(
        api.list_colleges(_ADMIN, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2, f"page 1 must hold 2 rows, got {len(page1)}"
    assert_partner_college(page1[0])
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0
    page2, meta2 = validate_paginated(
        api.list_colleges(_ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1, f"page 2 must hold exactly 1 row, got {len(page2)}"
    assert meta2["total_count"] == 3, (
        "total_count spans the whole set, not the page"
    )
    assert meta2["has_more"] is False
