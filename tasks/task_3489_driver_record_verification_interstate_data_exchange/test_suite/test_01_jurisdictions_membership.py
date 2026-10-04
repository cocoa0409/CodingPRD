"""Jurisdiction registration, membership lifecycle, auth rungs, and the
response envelope."""

import re

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    AUDIT_AUTHORITY_HEADERS,
    DEFAULT_CLOCK_ISO,
    EMPTY_HEADERS,
    NON_EXISTENT_UUID,
    TIMELINESS_SCORE_FULL_BP,
    ApiErrorId,
    assert_created,
    assert_error,
    assert_jurisdiction,
    assert_ok,
    assert_same_instant,
    create_jurisdiction,
    enroll_participation,
    is_iso8601_timestamp,
    jurisdiction_payload,
    make_jurisdiction_registrar_headers,
    membership_transition_payload,
    read_jurisdiction,
    setup_certified_jurisdiction,
    withdraw_jurisdiction,
)


def test_create_jurisdiction_applies_defaults(api):
    """PRD §3.1: "A freshly registered jurisdiction starts with `membership_status`
    `APPLIED`, a `certified_systems_count` of zero, and a `timeliness_score_bp` of
    10,000 — the empty-set value for a member with no commercial convictions yet."
    PRD §2.4: "The platform runs on a logical clock, not wall-clock time. At startup,
    before any explicit adjustment, the clock reads exactly `2026-09-01T00:00:00Z`,
    and it must never silently fall back to the host's wall clock."

    Design: Corner/entities/create_jurisdiction_applies_defaults
    """
    resp = api.create_jurisdiction(
        jurisdiction_payload(code="AA", name="State A", fee_tier="TIER_1"),
        ASSOCIATION_ADMIN_HEADERS,
    )
    data = assert_created(resp)
    assert_jurisdiction(data)
    assert data["membership_status"] == "APPLIED", "a fresh jurisdiction starts APPLIED"
    assert data["certified_systems_count"] == 0
    assert data["timeliness_score_bp"] == TIMELINESS_SCORE_FULL_BP
    assert_same_instant(data["created_at"], DEFAULT_CLOCK_ISO, label="created_at")


def test_create_jurisdiction_missing_required_field_returns_invalid_request(api):
    """PRD §2.6: "Independent of the ladder, field-shape failures — a missing required
    field, an unknown enum member, a malformed date or datetime, or a value outside its
    declared shape such as demerit `points` beyond the one-to-six range or a quarterly
    volume array of the wrong length — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)
    wherever they occur."
    PRD §3.1: "A jurisdiction enters the exchange when an `AssociationAdmin` registers
    it with a two-letter `code`, an official `name`, and the association-assigned dues
    weighting tier `fee_tier` — one of `TIER_1`, `TIER_2`, or `TIER_3`."

    Design: Corner/entities/create_jurisdiction_missing_required_field_returns_invalid_request
    """
    resp = api.create_jurisdiction(
        {"code": "AA", "name": "State A"},  # fee_tier omitted
        ASSOCIATION_ADMIN_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_jurisdiction_invalid_enum_returns_invalid_request(api):
    """PRD §3.1: "the association-assigned dues weighting tier `fee_tier` — one of
    `TIER_1`, `TIER_2`, or `TIER_3`."
    PRD §2.6: "field-shape failures — a missing required field, an unknown enum member,
    a malformed date or datetime, or a value outside its declared shape such as demerit
    `points` beyond the one-to-six range or a quarterly volume array of the wrong length
    — are rejected with `ERR_INVALID_REQUEST` (HTTP 400) wherever they occur."

    Design: Corner/entities/create_jurisdiction_invalid_enum_returns_invalid_request
    """
    resp = api.create_jurisdiction(
        jurisdiction_payload(code="AA", name="State A", fee_tier="TIER_9"),
        ASSOCIATION_ADMIN_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_jurisdiction_not_found_returns_404(api):
    """PRD §2.6: "Path identifiers and body foreign keys must reference existing
    resources, validated left to right; the first missing reference yields the
    corresponding not-found error — `ERR_JURISDICTION_NOT_FOUND`" (HTTP 404).

    Design: Corner/entities/get_jurisdiction_not_found_returns_404
    """
    resp = api.get_jurisdiction(NON_EXISTENT_UUID, ASSOCIATION_ADMIN_HEADERS)
    assert_error(resp, ApiErrorId.ERR_JURISDICTION_NOT_FOUND)


def test_duplicate_jurisdiction_code_rejected(api):
    """PRD §3.1: "The code must be unique across all jurisdictions; a collision is
    rejected with `ERR_JURISDICTION_CODE_TAKEN`."

    Design: Corner/entities/duplicate_jurisdiction_code_rejected
    """
    create_jurisdiction(api, code="AA", name="State A")
    resp = api.create_jurisdiction(
        jurisdiction_payload(code="AA", name="Another A", fee_tier="TIER_2"),
        ASSOCIATION_ADMIN_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_JURISDICTION_CODE_TAKEN)


def test_create_jurisdiction_computed_field_input_ignored(api):
    """PRD §3.1: "A freshly registered jurisdiction starts with `membership_status`
    `APPLIED`, a `certified_systems_count` of zero, and a `timeliness_score_bp` of
    10,000 — the empty-set value for a member with no commercial convictions yet."
    The computed score is pinned by the server at registration; a client-supplied
    `timeliness_score_bp` in the payload does not change it.

    Design: Corner/entities/create_jurisdiction_computed_field_input_ignored
    """
    resp = api.create_jurisdiction(
        jurisdiction_payload(code="AA", name="State A", fee_tier="TIER_1", timeliness_score_bp=1),
        ASSOCIATION_ADMIN_HEADERS,
    )
    data = assert_created(resp)
    assert data["timeliness_score_bp"] == TIMELINESS_SCORE_FULL_BP, (
        "the server-computed empty-set score wins over client-supplied input"
    )


def test_create_response_envelope_shape(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp
    with three fractional digits."
    PRD §2.2 (error format): "The `message` provides a human-readable explanation of
    what went wrong."
    PRD §4: "Operations that create a new resource return `201 Created`".

    Design: Corner/endpoints/create_response_envelope_shape
    """
    resp = api.create_jurisdiction(
        jurisdiction_payload(code="CC", name="Envelope State", fee_tier="TIER_3"),
        ASSOCIATION_ADMIN_HEADERS,
    )
    data = assert_created(resp)
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["data"]["code"] == "CC"
    request_id = body["meta"]["api_request_id"]
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        "api_request_id is a server-generated identifier starting with req_"
    )
    timestamp = body["meta"]["api_request_timestamp"]
    assert is_iso8601_timestamp(timestamp)
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", timestamp), (
        "api_request_timestamp is an ISO 8601 UTC timestamp with three fractional digits"
    )
    assert data["code"] == "CC"

    err_resp = api.get_jurisdiction(NON_EXISTENT_UUID, ASSOCIATION_ADMIN_HEADERS)
    err_data = assert_error(err_resp, ApiErrorId.ERR_JURISDICTION_NOT_FOUND)
    err_body = err_resp.json()
    assert err_body["response_type"] == "error"
    assert err_data["error_id"] == "ERR_JURISDICTION_NOT_FOUND"
    assert isinstance(err_data["message"], str) and err_data["message"], (
        "error responses carry a human-readable message"
    )
    assert err_body["meta"]["api_request_id"]


def test_jurisdiction_activation_requires_certified_pointer(api):
    """PRD §3.1: "An administrator moves a jurisdiction from `APPLIED` to `ACTIVE` by
    patching its `status`, and the transition is gated: at least one of the
    jurisdiction's system participations must already hold `CERTIFIED` status in the
    `POINTER_NETWORK`, otherwise the attempt fails with `ERR_PARTICIPATION_NOT_CERTIFIED`."

    Design: Corner/state_machines/jurisdiction_activation_requires_certified_pointer
    """
    jurisdiction = create_jurisdiction(api, code="AA", name="State A")
    enroll_participation(api, jurisdiction["id"], "POINTER_NETWORK")
    resp = api.update_jurisdiction(
        jurisdiction["id"],
        membership_transition_payload("ACTIVE"),
        ASSOCIATION_ADMIN_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_PARTICIPATION_NOT_CERTIFIED)
    assert read_jurisdiction(api, jurisdiction["id"])["membership_status"] == "APPLIED"


def test_withdrawn_jurisdiction_is_terminal(api):
    """PRD §3.1: "Withdrawal, reachable from either `ACTIVE` or `SUSPENDED`, moves the
    jurisdiction to the terminal `WITHDRAWN`; a withdrawn jurisdiction's resources
    remain readable for the historical record."
    PRD §2.6: "The target resource must be in a state from which the requested
    transition is declared." (else `ERR_INVALID_STATE`, HTTP 409).

    Design: Corner/state_machines/withdrawn_jurisdiction_is_terminal
    """
    ctx = setup_certified_jurisdiction(api, code="AA", systems=("POINTER_NETWORK",))
    withdraw_jurisdiction(api, ctx["jurisdiction_id"])
    resp = api.update_jurisdiction(
        ctx["jurisdiction_id"],
        membership_transition_payload("ACTIVE"),
        ASSOCIATION_ADMIN_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_create_jurisdiction_as_auditor_forbidden(api):
    """PRD §2.1: "Once the headers are accepted, the declared role is checked against
    the endpoint's authorized role set; a role outside that set is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4: the registration endpoint POST /driver-exchange/jurisdictions is authorized
    for AssociationAdmin only ("Register a member jurisdiction | AssociationAdmin").

    Design: Corner/rbac/create_jurisdiction_as_auditor_forbidden
    """
    resp = api.create_jurisdiction(
        jurisdiction_payload(code="AA", name="State A", fee_tier="TIER_1"),
        AUDIT_AUTHORITY_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_missing_auth_headers_returns_400(api):
    """PRD §2.6: "**Header presence.** `X-User-ID` and `X-User-Role` must be present and
    well-formed, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/missing_auth_headers_returns_400
    """
    resp = api.create_jurisdiction(
        jurisdiction_payload(code="AA", name="State A", fee_tier="TIER_1"),
        EMPTY_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
