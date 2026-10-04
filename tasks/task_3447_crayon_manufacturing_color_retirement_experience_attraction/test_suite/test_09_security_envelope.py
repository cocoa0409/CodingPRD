"""Authentication, authorization, existence precedence, and envelopes."""
import test_helpers.fixtures as fx
from test_helpers import (
    api_client, ApiErrorId, validate_error, assert_error_envelope,
    NON_EXISTENT_UUID,
)

ADMIN = fx.ADMIN
CONSUMER = fx.CONSUMER
BOXOFFICE = fx.BOXOFFICE
SAFETY = fx.SAFETY


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD section 2.1: "A request missing either header, or presenting a role
    value the system does not declare, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)." — priority 1, before any role, shape, or existence check.

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    fx.reset_clock()
    resp = api_client.create_color({"name": "No Header Blue", "hex_code": "#000000"}, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401


def test_unknown_path_id_returns_not_found_before_state_checks(api):
    """PRD section 2.8: "The stages are evaluated in the order below, the first
    failure wins" — existence (stage 4, `ERR_NOT_FOUND`, HTTP 404) precedes
    state gates (stage 6), so a transition on a never-created formula id never
    reaches the formula-state check.

    Design: Corner/validations/unknown_path_id_returns_not_found_before_state_checks
    """
    fx.reset_clock()
    resp = api_client.formula_transition(NON_EXISTENT_UUID, {"action": "APPROVE"}, SAFETY)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404
    assert resp.json()["data"]["error_id"] != "ERR_INVALID_FORMULA_STATE"


def test_error_response_envelope_shape_is_fixed(api):
    """PRD section 2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" — `response_type` "error", `data.error_id`,
    `data.message`, and `meta.api_request_id`/`api_request_timestamp`.

    Design: Corner/endpoints/error_response_envelope_shape_is_fixed
    """
    fx.reset_clock()
    resp = api_client.get_color(NON_EXISTENT_UUID, ADMIN)
    data = assert_error_envelope(resp, 404)
    assert data["error_id"] == "ERR_NOT_FOUND"


def test_consumer_cannot_create_colors(api):
    """PRD section 2.1: "`Consumer` — the public voter; may only cast ballots."
    and "A request whose role is declared but not permitted on the target
    endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)". Color creation is
    PlatformAdmin-only per section 4.

    Design: Corner/rbac/consumer_cannot_create_colors
    """
    fx.reset_clock()
    resp = api_client.create_color({"name": "Ballot Blue", "hex_code": "#3366CC"}, CONSUMER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert resp.status_code == 403


def test_boxoffice_cannot_run_epoch(api):
    """PRD section 3.8: "The run-epoch checkpoint of §2.4 is the platform's
    batch heart-beat, callable only by `PlatformAdmin`."

    Design: Corner/rbac/boxoffice_cannot_run_epoch
    """
    fx.reset_clock()
    resp = api_client.run_epoch(BOXOFFICE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert resp.status_code == 403
