"""Priority-pair validations (queue A): earlier priority masks later error."""
from test_helpers import (
    ApiErrorId,
    authorize,
    get_success_data,
    make_cardholder_headers,
    open_session,
    reset_clock,
    setup_account_and_artifact,
    setup_cardholder,
    setup_device,
    setup_issuer_active,
    validate_error,
    validate_paginated,
    verify_session_twice,
)


def _expired_session_on_unsecured_device(api):
    """Verified session whose expiry has passed; device has NO passcode."""
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, _agr = setup_issuer_active(api)
    device = setup_device(api, ch, secure=False)
    account, artifact = setup_account_and_artifact(api, ch, issuer)
    session = open_session(api, device, artifact, ch)
    session = verify_session_twice(api, device, session, ch)
    api.set_clock("2026-09-02T01:00:00Z", None)
    fresh = get_success_data(api.get_provisioning_session(session["id"]))
    return ch, device, session, fresh


def test_expired_session_error_beats_device_unsecured_on_tokenize(api):
    """PRD section 2.10: "Provisioning session lazy expiry — on verify and
    tokenize, if the logical clock has reached the session's expires_at, the
    session is transitioned to EXPIRED before any other check runs, and the
    request fails with ERR_PROVISIONING_SESSION_EXPIRED." Even with the device
    DEGRADED (priority 9), the priority-5 expiry error surfaces first.

    Design: Difficulty/priority_pair_validation_conflict/tokenize_expired_session_state_beats_device_unsecured_safety
    """
    ch, device, session, fresh = _expired_session_on_unsecured_device(api)
    resp = api.tokenize_session(
        device["id"], session["id"],
        {"expected_session_version": fresh["version"]},
        make_cardholder_headers(ch["id"]),
    )
    err = validate_error(resp, ApiErrorId.ERR_PROVISIONING_SESSION_EXPIRED)
    assert err["error_id"] != ApiErrorId.ERR_DEVICE_UNSECURED.value


def test_expired_session_is_marked_expired_after_failed_tokenize(api):
    """PRD section 2.10: "Provisioning session lazy expiry — on verify and
    tokenize, if the logical clock has reached the session's expires_at, the
    session is transitioned to EXPIRED before any other check runs, and the
    request fails with ERR_PROVISIONING_SESSION_EXPIRED." The lazy flip is
    observable: after the failed tokenize the session reads back EXPIRED.

    Design: Difficulty/priority_pair_validation_conflict/tokenize_expired_session_state_beats_device_unsecured_safety
    """
    ch, device, session, fresh = _expired_session_on_unsecured_device(api)
    api.tokenize_session(
        device["id"], session["id"],
        {"expected_session_version": fresh["version"]},
        make_cardholder_headers(ch["id"]),
    )
    current = get_success_data(api.get_provisioning_session(session["id"]))
    assert current["status"] == "EXPIRED"


def test_suspended_token_error_beats_amount_cap_on_authorize(api):
    """PRD section 2.10: "Because lower numbers run first, a request that would
    fail both the token-active check and the amount cap always surfaces
    ERR_TOKEN_NOT_ACTIVE". A suspended token charged 250000 (> the 100000
    per-authorization cap) fails with ERR_TOKEN_NOT_ACTIVE (priority 8), not
    ERR_AUTH_AMOUNT_EXCEEDS_CAP (priority 14).

    Design: Difficulty/priority_pair_validation_conflict/authorize_inactive_token_state_beats_amount_cap_fiscal
    """
    from test_helpers import setup_provisioned_token

    ns = setup_provisioned_token(api)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    get_success_data(api.suspend_token(ns["device"]["id"], ns["token"]["id"], ch))
    resp = authorize(api, ns["token"], amount_cents=250000, cryptogram="cgm-x")
    err = validate_error(resp, ApiErrorId.ERR_TOKEN_NOT_ACTIVE)
    assert err["error_id"] != ApiErrorId.ERR_AUTH_AMOUNT_EXCEEDS_CAP.value


def test_gate_failure_persists_no_authorization_row(api):
    """PRD section 3.6: "A failure at any gate rejects the request with that
    gate's 4xx error and no Authorization row is persisted at all; none of the
    token's decline counters move." A suspended token charged an over-cap
    amount leaves the token's authorization list empty.

    Design: Difficulty/priority_pair_validation_conflict/authorize_inactive_token_state_beats_amount_cap_fiscal
    """
    from test_helpers import setup_provisioned_token

    ns = setup_provisioned_token(api)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    get_success_data(api.suspend_token(ns["device"]["id"], ns["token"]["id"], ch))
    authorize(api, ns["token"], amount_cents=250000, cryptogram="cgm-x")
    resp = api.list_token_authorizations(ns["token"]["id"])
    rows, meta = validate_paginated(resp)
    assert rows == [] and meta["total_count"] == 0
