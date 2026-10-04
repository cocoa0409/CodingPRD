"""Candidate registration, listing, envelope shape, and authentication."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    create_candidate_payload, setup_candidate, submit_application,
    make_candidate_headers, set_clock, assert_candidate,
)

ADMIN = TEST_USERS["system_admin_headers"]
FC = TEST_USERS["field_consultant_headers"]


def test_candidate_create_returns_system_fields_and_registered_status(api):
    """PRD §3.1: "A freshly registered candidate's `candidate_status` reads
    `REGISTERED`, and its `active_application_id` is null because no application
    exists yet."
    PRD §2.5: "Every primary resource — candidates, applications, interview
    rounds, ... — carries a standard set of system-managed fields"

    Design: Corner/entities/candidate_create_returns_system_fields_and_registered_status
    """
    set_clock()
    resp = api.create_candidate(create_candidate_payload(
        legal_name="Pat Applicant", email="pat@example.com",
        home_market_code="GA", relocation_willing=True, liquid_capital_cents=500000,
    ), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_candidate(data)
    assert data["candidate_status"] == "REGISTERED"
    assert data["version"] == 1
    assert data["active_application_id"] is None
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"].get("api_request_id")
    assert body["meta"].get("api_request_timestamp")


def test_candidate_create_missing_email_returns_invalid_request(api):
    """PRD §2.1: "Independently of role, a request body that is missing a
    required field or carries a malformed value is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/candidate_create_missing_email_returns_invalid_request
    """
    set_clock()
    payload = create_candidate_payload(legal_name="Pat Applicant")
    payload.pop("email")
    resp = api.create_candidate(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_candidate_get_unknown_id_returns_not_found(api):
    """PRD §2.6: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
    first path segment whose identifier does not correspond to an existing
    resource, before any later segment or any business rule is evaluated."

    Design: Corner/entities/candidate_get_unknown_id_returns_not_found
    """
    set_clock()
    resp = api.get_candidate(NON_EXISTENT_UUID, FC)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"].get("message"), str) and body["data"]["message"]


def test_candidates_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The `meta` object of a list response always carries `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/candidates_list_paginates_with_total_count_and_has_more
    """
    set_clock()
    setup_candidate(legal_name="A One", email="a1@example.com", home_market_code="GA")
    setup_candidate(legal_name="A Two", email="a2@example.com", home_market_code="GA")
    setup_candidate(legal_name="A Three", email="a3@example.com", home_market_code="FL",
                    relocation_willing=False)

    data, meta = validate_paginated(api.list_candidates(FC, params={"limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    data, meta = validate_paginated(api.list_candidates(FC, params={"limit": 2, "offset": 2}))
    assert len(data) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    data, meta = validate_paginated(api.list_candidates(FC, params={"home_market_code": "FL"}))
    assert len(data) == 1
    assert data[0]["home_market_code"] == "FL"


def test_unauthenticated_request_missing_role_header_rejected(api):
    """PRD §2.1: "A request missing either header, or presenting a role outside
    the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/endpoints/unauthenticated_request_missing_role_header_rejected
    """
    set_clock()
    resp = api.list_candidates({}, params=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_error_envelope_shape_on_business_error(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" and "The `meta` object for error responses
    contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/error_envelope_shape_on_business_error
    """
    set_clock()
    resp = api.get_restaurant(NON_EXISTENT_UUID, FC)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"].get("message"), str) and body["data"]["message"]
    assert body["meta"].get("api_request_id")
    assert body["meta"].get("api_request_timestamp")


def test_duplicate_application_for_candidate_rejected(api):
    """PRD §3.1: "Submission is permitted only while the candidate is
    `REGISTERED` and has no non-terminal application; a candidate who already
    has a live application is refused with `ERR_DUPLICATE_APPLICATION`."

    Design: Corner/validations/duplicate_application_for_candidate_rejected
    """
    set_clock()
    candidate = setup_candidate(legal_name="Vic Applicant", email="vic@example.com")
    submit_application(candidate, target_market_code="GA")
    resp = api.create_application(
        candidate["id"], {"target_market_code": "FL"}, make_candidate_headers(candidate["id"])
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION)


def test_application_withdraw_returns_candidate_to_registered(api):
    """PRD §3.5: "Every withdrawal bubbles the candidate from `IN_SELECTION`
    back to `REGISTERED` and clears `active_application_id`"

    Design: Difficulty/compensating_invariant/application_withdraw_restores_candidate_to_registered
    """
    set_clock()
    candidate = setup_candidate(legal_name="Omar Applicant", email="omar@example.com")
    application = submit_application(candidate, target_market_code="GA")
    resp = api.withdraw_application(application["id"], make_candidate_headers(candidate["id"]))
    validate_success(resp)
    after = get_success_data(api.get_candidate(candidate["id"], ADMIN))
    assert after["candidate_status"] == "REGISTERED"
    assert after["active_application_id"] is None


def test_candidate_can_apply_again_after_withdrawal(api):
    """PRD §3.1: "Submission is permitted only while the candidate is
    `REGISTERED` and has no non-terminal application; a candidate who already
    has a live application is refused with `ERR_DUPLICATE_APPLICATION`."
    PRD §3.5: "Every withdrawal bubbles the candidate from `IN_SELECTION` back
    to `REGISTERED` and clears `active_application_id`"

    Design: Difficulty/compensating_invariant/application_withdraw_restores_candidate_to_registered
    """
    set_clock()
    candidate = setup_candidate(legal_name="Omar Applicant", email="omar@example.com")
    first = submit_application(candidate, target_market_code="GA")
    validate_success(api.withdraw_application(first["id"], make_candidate_headers(candidate["id"])))
    resp = api.create_application(
        candidate["id"], {"target_market_code": "GA"}, make_candidate_headers(candidate["id"])
    )
    second = validate_success(resp, expected_status=201)
    assert second["stage"] == "SUBMITTED"
