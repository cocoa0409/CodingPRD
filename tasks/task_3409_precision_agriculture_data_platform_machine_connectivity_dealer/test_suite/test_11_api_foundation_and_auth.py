"""API foundation: success/error envelopes, the startup logical clock, and
the authentication/authorization headers."""

from test_helpers import (
    ADMIN,
    AGRONOMIST,
    ApiErrorId,
    UNKNOWN_ROLE_HEADERS,
    create_organization_payload,
    same_instant,
    validate_error,
    validate_success,
)


def test_organization_create_applies_defaults_and_envelope(api):
    """PRD section 3.1: "`right_to_repair_enabled`, defaulting to `false` ...
    `independent_session_max_minutes`, defaulting to 60 ... A new organization
    starts `ACTIVE`." PRD section 2.4: "It maintains a logical clock that
    starts fixed at `2026-09-01T00:00:00Z` when the server boots and never
    falls back to real time." PRD section 2.2: "The `response_type` is either
    "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/organization_create_applies_defaults_and_envelope
    """
    response = api.create_organization(
        create_organization_payload(), headers=ADMIN
    )
    org = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]

    assert org["right_to_repair_enabled"] is False
    assert org["independent_session_max_minutes"] == 60
    assert org["status"] == "ACTIVE"
    assert org["version"] == 1
    assert same_instant(org["created_at"], "2026-09-01T00:00:00Z")


def test_unknown_role_header_rejected(api):
    """PRD section 2.1: "A request missing either header, carrying a malformed
    header, or naming an undeclared role is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/unknown_role_header_rejected
    """
    response = api.create_organization(
        create_organization_payload(name="Ghost Org"),
        headers=UNKNOWN_ROLE_HEADERS,
    )
    validate_error(
        response, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    )


def test_role_not_on_endpoint_forbidden(api):
    """PRD section 2.1: "Every endpoint declares the roles permitted to invoke
    it (§4); a caller whose role is not in that endpoint's list is rejected
    with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." Organization creation is
    `PlatformAdmin`-only (PRD section 4).

    Design: Corner/validations/role_not_on_endpoint_forbidden
    """
    response = api.create_organization(
        create_organization_payload(name="Ghost Org"),
        headers=AGRONOMIST,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
