"""Platform and validation pipeline: missing auth headers, role authorization,
path-existence precedence over state checks, and the logical clock."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, api_client,
    make_consumer_headers, validate_error, validate_success,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["platform_admin_headers"]
MM = TEST_USERS["marketing_manager_headers"]


def test_request_missing_auth_headers_returns_400():
    """PRD §2.1: "All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, presenting an empty value, or naming an undeclared role is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/request_missing_auth_headers_returns_400
    """
    resp = api_client.create_brand(
        {"name": "No Headers", "legal_entity_name": "No Headers Co"}, {})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_consumer_cannot_create_distributor_returns_forbidden():
    """PRD §2.1: "When the headers are valid but the caller's role is not among the roles authorized for the target endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §2.1: "`ChannelManager` — owns the distributor lifecycle (create, approve, suspend, reinstate, terminate), coverage assignments (propose, activate, suspend, resume, withdraw), records promotion redemptions, and may read the rebate preview."

    Design: Corner/validations/consumer_cannot_create_distributor_returns_forbidden
    """
    market = fx.create_market()
    resp = api_client.create_distributor(
        {"legal_name": "Consumer Corp", "home_market_id": market["id"],
         "channels_served": ["MASS"], "credit_limit_cents": 1000},
        make_consumer_headers("consumer-1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_existence_check_precedes_state_check():
    """PRD §2.10: "For every such request the server validates path identifiers strictly left to right and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve, before any body-level, state-level or business-level check is attempted."
    PRD §2.6: "Every request is evaluated against an ordered validation pipeline, and the first failing check determines the error returned — later checks are never reached once an earlier one fails."

    Design: Corner/validations/existence_check_precedes_state_check
    """
    resp = api_client.approve_promotion(NON_EXISTENT_UUID, MM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_clock_regression_rejected_then_forward_accepted():
    """PRD §2.4: "Before any operator intervention the logical time is exactly `2026-09-01T00:00:00Z`; the server must not fall back to the host clock under any circumstance. A `PlatformAdmin` may advance the clock through an admin-only test-driving capability — mounted outside the `/brand-ops` namespace — that accepts a target instant in the `to_iso8601` field (ISO 8601 UTC) and echoes the resulting time back as `current_utc`."
    PRD §2.4: "The target must be strictly after the current logical time; any attempt to hold or regress the clock is rejected with `ERR_CLOCK_REGRESSION` (HTTP 400)."

    Design: Corner/validations/clock_regression_rejected_then_forward_accepted
    """
    backward = api_client.set_clock("2026-08-01T00:00:00Z", ADMIN)
    validate_error(backward, ApiErrorId.ERR_CLOCK_REGRESSION)

    forward = api_client.set_clock("2026-09-02T00:00:00Z", ADMIN)
    data = validate_success(forward)
    assert data["current_utc"].startswith("2026-09-02T00:00:00"), \
        "the endpoint echoes the new logical time"
