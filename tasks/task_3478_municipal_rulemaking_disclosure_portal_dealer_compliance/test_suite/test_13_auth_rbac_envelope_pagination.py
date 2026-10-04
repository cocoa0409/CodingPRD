"""Platform-wide contract: authentication, role exclusivity, the response
envelope, pagination meta, clock access/monotonicity, and path not-found
identity (PRD sections 2.1, 2.2, 2.3, 2.4, 2.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_envelope_meta,
    create_pending_approval_proposal,
    create_rule_proposal,
    headers_without_credentials,
    set_clock,
    set_clock_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["rulemaking_officer_headers"]
OFFICER_ALT = TEST_USERS["rulemaking_officer_alt_headers"]
REGULATOR = TEST_USERS["regulator_headers"]
SYSTEM_ADMIN = TEST_USERS["system_admin_headers"]
PORTAL_OPERATOR = TEST_USERS["portal_operator_headers"]

UNKNOWN_ID = "11111111-2222-3333-4444-555555555555"


def test_request_without_credential_headers_is_unauthenticated(api):
    """PRD section 2.1: "A request in which either header is missing or
    blank is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_rule_proposals(headers_without_credentials())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401


def test_regulator_cannot_create_rule_proposal(api):
    """PRD section 2.1: "an attempt to perform an action outside the
    caller's designated role is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)". PRD section 3.1: "A rule change begins when a
    `RulemakingOfficer` registers a **rule proposal**".

    Design: Corner/rbac/regulator_cannot_create_proposal
    """
    resp = api.create_rule_proposal(
        {"rule_code": "G-500", "title": "Regulator attempt", "body": "r", "category": "DISCLOSURE"},
        REGULATOR,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_rulemaking_officer_cannot_decide_proposal(api):
    """PRD section 3.1: "The decision belongs to a `Regulator`"; section
    2.1: "an attempt to perform an action outside the caller's designated
    role is rejected with `ERR_UNAUTHORIZED` (HTTP 403)". The role gate is
    distinct from the segregation-of-duties comparison: this caller is a
    different officer than the submitter, yet still lacks the role.

    Design: Corner/rbac/rulemaking_officer_cannot_decide_proposal
    """
    proposal = create_pending_approval_proposal(
        api, rule_code="G-502", title="Decide rbac", body="d", category="DEALER_CONDUCT"
    )
    resp = api.decide_proposal(proposal["id"], {"decision": "APPROVE"}, OFFICER_ALT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_non_systemadmin_cannot_set_the_logical_clock(api):
    """PRD section 2.4: the clock-setting capability "is deliberately
    mounted outside that prefix, is restricted to `SystemAdmin`", and
    section 2.1 rejects role violations with `ERR_UNAUTHORIZED`
    (HTTP 403).

    Design: Corner/rbac/non_systemadmin_cannot_set_clock
    """
    resp = api.set_clock(set_clock_payload("2026-09-02T00:00:00Z"), OFFICER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_clock_regression_is_rejected(api):
    """PRD section 2.4: "The clock is monotonic: `to_iso8601` must be at
    least the current logical time, and a request to move it strictly
    backwards is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422)."

    Design: Corner/validations/clock_regression_rejected
    """
    set_clock(api, "2026-09-10T00:00:00Z")
    resp = api.set_clock(set_clock_payload("2026-09-09T23:59:59Z"), SYSTEM_ADMIN)
    validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)


def test_response_envelope_shape_on_success_and_error(api):
    """PRD section 2.2 fixes `response_type` as either "object" for a
    single resource or "array" for a list of resources; "The
    `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`." On errors: "The `meta` object for
    error responses contains only `api_request_id` and
    `api_request_timestamp`.", "The `error_id` is a unique,
    machine-readable string that identifies the specific error.", and
    "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/endpoints/response_envelope_shape_on_success_and_error
    """
    created = api.create_organization(
        {"org_code": "BD-4001", "name": "Dealer Envelope", "org_type": "BROKER_DEALER"},
        PORTAL_OPERATOR,
    )
    validate_success(created, 201)
    body = created.json()
    assert_envelope_meta(body)
    assert body["response_type"] == "object"
    assert isinstance(body["data"], dict) and body["data"]["id"]

    missing = api.get_organization("99999999-8888-7777-6666-555555555555", PORTAL_OPERATOR)
    validate_error(missing, ApiErrorId.ERR_ORG_NOT_FOUND)
    error_body = missing.json()
    assert_envelope_meta(error_body)
    assert error_body["response_type"] == "error"
    assert error_body["data"]["error_id"] == "ERR_ORG_NOT_FOUND"
    assert isinstance(error_body["data"]["message"], str) and error_body["data"]["message"]


def test_rule_proposal_list_pagination_limit_offset_has_more(api):
    """PRD section 2.3: "The `limit` parameter caps the number of items
    returned; it defaults to 10, with a minimum of 1 and a maximum of 100."
    and "The `offset` parameter skips a number of items from the front of
    the result set and defaults to 0." and "The `meta` object of a list
    response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/proposal_list_pagination_limit_offset_has_more
    """
    for code, title in (("G-401", "P1"), ("G-402", "P2"), ("G-403", "P3")):
        create_rule_proposal(api, rule_code=code, title=title, body=title, category="DISCLOSURE")

    page1, meta1 = validate_paginated(
        api.list_rule_proposals(OFFICER, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_rule_proposals(OFFICER, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_get_unknown_proposal_returns_proposal_not_found(api):
    """PRD section 2.7: "Each resource family carries its own not-found
    error identifier:" — for rule proposals that identifier is
    `ERR_PROPOSAL_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/proposal_get_unknown_id_returns_proposal_not_found
    """
    resp = api.get_rule_proposal(UNKNOWN_ID, OFFICER)
    validate_error(resp, ApiErrorId.ERR_PROPOSAL_NOT_FOUND)
