"""Boundary precision (queue A): 24h TTL inclusive boundary; 3-decline streak."""
from test_helpers import (
    ApiErrorId,
    CRYPTOGRAM_DECLINE,
    authorize,
    get_success_data,
    make_cardholder_headers,
    open_session,
    reset_clock,
    setup_account_and_artifact,
    setup_cardholder,
    setup_device,
    setup_issuer_active,
    setup_provisioned_token,
    validate_error,
    verify_session_twice,
)


def test_tokenize_one_second_before_expiry_succeeds(api):
    """PRD section 3.4: "Its expires_at is computed at creation as exactly 24
    hours after created_at, measured on the logical clock ... the boundary is
    inclusive, so a clock reading exactly expires_at already means expired."
    One second before expires_at the window is still open and tokenize succeeds.

    Design: Difficulty/boundary_precision_check/session_expires_at_exactly_ttl_boundary_inclusive
    """
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, _ = setup_issuer_active(api)
    device = setup_device(api, ch)
    account, artifact = setup_account_and_artifact(api, ch, issuer)
    session = open_session(api, device, artifact, ch)
    session = verify_session_twice(api, device, session, ch)
    api.set_clock("2026-09-01T23:59:59Z", None)
    fresh = get_success_data(api.get_provisioning_session(session["id"]))
    resp = api.tokenize_session(
        device["id"], session["id"],
        {"expected_session_version": fresh["version"]},
        make_cardholder_headers(ch["id"]),
    )
    token = get_success_data(resp)
    assert token["status"] == "ACTIVE"


def test_tokenize_exactly_at_expiry_fails(api):
    """PRD section 3.4: "Expiry is lazy: a session whose expiry has passed is
    flipped to EXPIRED the next time it is accessed — on verify, on tokenize,
    or on read — and the boundary is inclusive, so a clock reading exactly
    expires_at already means expired." A session created at 2026-09-01T00:00:00Z
    expires at 2026-09-02T00:00:00Z; tokenize at exactly that instant fails with
    ERR_PROVISIONING_SESSION_EXPIRED.

    Design: Difficulty/boundary_precision_check/session_expires_at_exactly_ttl_boundary_inclusive
    """
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, _ = setup_issuer_active(api)
    device = setup_device(api, ch)
    account, artifact = setup_account_and_artifact(api, ch, issuer)
    session = open_session(api, device, artifact, ch)
    session = verify_session_twice(api, device, session, ch)
    # read at the last valid second, then advance to exactly expires_at
    api.set_clock("2026-09-01T23:59:59Z", None)
    fresh = get_success_data(api.get_provisioning_session(session["id"]))
    api.set_clock("2026-09-02T00:00:00Z", None)
    resp = api.tokenize_session(
        device["id"], session["id"],
        {"expected_session_version": fresh["version"]},
        make_cardholder_headers(ch["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROVISIONING_SESSION_EXPIRED)


def test_two_consecutive_declines_leave_token_active(api):
    """PRD section 3.5: "When a token's consecutive_decline_count reaches 3 —
    the system's decline-streak threshold — the token auto-suspends". Below the
    threshold nothing happens: after two declines the token is still ACTIVE
    with consecutive_decline_count 2.

    Design: Difficulty/boundary_precision_check/third_consecutive_decline_auto_suspends_exactly_at_threshold
    """
    ns = setup_provisioned_token(api)
    get_success_data(authorize(api, ns["token"], amount_cents=100,
                               cryptogram=CRYPTOGRAM_DECLINE))
    get_success_data(authorize(api, ns["token"], amount_cents=100,
                               cryptogram=CRYPTOGRAM_DECLINE, merchant_id="m-2"))
    token = get_success_data(api.get_payment_token(ns["token"]["id"]))
    assert token["consecutive_decline_count"] == 2
    assert token["status"] == "ACTIVE"


def test_third_consecutive_decline_auto_suspends_and_blocks_auth(api):
    """PRD section 3.5: "When a token's consecutive_decline_count reaches 3 —
    the system's decline-streak threshold — the token auto-suspends: it moves
    ACTIVE -> SUSPENDED, suspension_count increments, a SUSPENSION event is
    appended, and if the token was the device default, default_card_id is
    cleared." Exactly at 3 the auto-suspend fires; a 4th authorization fails
    with ERR_TOKEN_NOT_ACTIVE.

    Design: Difficulty/boundary_precision_check/third_consecutive_decline_auto_suspends_exactly_at_threshold
    """
    ns = setup_provisioned_token(api)
    for i in range(3):
        get_success_data(authorize(api, ns["token"], amount_cents=100,
                                   cryptogram=CRYPTOGRAM_DECLINE,
                                   merchant_id=f"m-{i}"))
    token = get_success_data(api.get_payment_token(ns["token"]["id"]))
    assert token["consecutive_decline_count"] == 3
    assert token["status"] == "SUSPENDED"
    assert token["suspension_count"] == 1
    resp = authorize(api, ns["token"], amount_cents=100, cryptogram="cgm-4th",
                     merchant_id="m-4")
    validate_error(resp, ApiErrorId.ERR_TOKEN_NOT_ACTIVE)
