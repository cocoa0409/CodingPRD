"""Corner: validations — auth headers, role/ownership, dispute and close gates,
tokenize priority pairs, express eligibility at tokenize."""
from test_helpers import (
    ADMIN,
    OPERATOR,
    ApiErrorId,
    approved_authorization,
    create_dispute_payload,
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
    validate_paginated,
    verify_session_twice,
)


def test_authorize_missing_role_header_returns_auth_error(api):
    """PRD section 2.1: "Every other endpoint requires both headers to be
    present and well-formed; a missing or malformed header is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (HTTP 400)." Authorization is
    role-gated to IssuerOperator, so a header-less POST fails at priority 1.

    Design: Corner/validations/authorize_missing_role_header_returns_auth_error
    """
    ns = setup_provisioned_token(api)
    resp = api.authorize(ns["token"]["id"], {
        "cryptogram": "c1", "amount_cents": 100, "currency": "USD",
        "merchant_id": "m-1", "merchant_category": "GENERAL",
    }, None)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_tokenize_wrong_role_is_forbidden_even_with_expired_session(api):
    """PRD section 2.10: "Authorization is checked only after the header check"
    and the role/ownership slot (priority 2) precedes lazy expiry (priority 5):
    an IssuerOperator calling tokenize gets ERR_FORBIDDEN even when the session
    is expired — the caller never learns the expiry state.

    Design: Corner/validations/tokenize_wrong_role_is_forbidden_even_with_valid_state
    """
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, _agr = setup_issuer_active(api)
    device = setup_device(api, ch)
    account, artifact = setup_account_and_artifact(api, ch, issuer)
    session = open_session(api, device, artifact, ch)
    session = verify_session_twice(api, device, session, ch)
    api.set_clock("2026-09-03T00:00:00Z", None)
    fresh = get_success_data(api.get_provisioning_session(session["id"]))
    resp = api.tokenize_session(
        device["id"], session["id"],
        {"expected_session_version": fresh["version"]}, OPERATOR)
    err = validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert err["error_id"] != ApiErrorId.ERR_PROVISIONING_SESSION_EXPIRED.value


def test_cardholder_cannot_act_on_another_cardholders_device(api):
    """PRD section 2.1: "A Cardholder may act only on devices they own on
    ownership-scoped endpoints; a mismatch is ERR_FORBIDDEN." Cardholder B
    calling set-security on A's device is rejected and the flags do not change.

    Design: Corner/validations/cardholder_cannot_act_on_another_cardholders_device
    """
    reset_clock(api)
    ch_a = setup_cardholder(api)
    ch_b = setup_cardholder(api, email="bea@example.com", name="Bea Coy",
                            phone="+15550001002")
    device = setup_device(api, ch_a, secure=False)
    resp = api.set_device_security(
        device["id"], {"passcode_enabled": True, "biometric_enabled": False},
        make_cardholder_headers(ch_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    device = get_success_data(api.get_device(device["id"]))
    assert device["passcode_enabled"] is False


def test_disputed_amount_mismatch_rejected(api):
    """PRD section 3.7: "the disputed amount must equal the authorization's
    amount_cents exactly — otherwise ERR_DISPUTE_AMOUNT_MISMATCH"."

    Design: Corner/validations/disputed_amount_mismatch_rejected
    """
    ns = setup_provisioned_token(api)
    auth = approved_authorization(api, ns["token"], amount_cents=10000,
                                  cryptogram="cgm-d")
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    resp = api.open_dispute(
        auth["id"], create_dispute_payload(9999, reason="DUPLICATE"), ch)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_AMOUNT_MISMATCH)
    rows, _meta = validate_paginated(api.list_token_disputes(ns["token"]["id"]))
    assert rows == []


def test_close_account_with_open_dispute_rejected(api):
    """PRD section 3.3: "closing an OPEN account is blocked while any OPEN
    dispute exists on tokens of the account, surfacing
    ERR_CARD_HAS_OPEN_DISPUTES."

    Design: Corner/validations/close_account_with_open_dispute_rejected
    """
    ns = setup_provisioned_token(api)
    auth = approved_authorization(api, ns["token"], amount_cents=8000,
                                  cryptogram="cgm-e")
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    get_success_data(api.open_dispute(
        auth["id"], create_dispute_payload(8000, reason="GOODS_NOT_RECEIVED"), ch))
    resp = api.close_card_account(ns["account"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_CARD_HAS_OPEN_DISPUTES)
    account = get_success_data(api.get_card_account(ns["account"]["id"]))
    assert account["status"] == "OPEN"


def test_tokenize_with_closed_account_fails_account_restricted(api):
    """PRD section 3.4: tokenize runs its gates including "the funding account
    must be OPEN and the issuer ACTIVE with an ACTIVE agreement
    (ERR_CARD_ACCOUNT_RESTRICTED, ERR_ISSUER_NOT_ACTIVE)". A VERIFIED session
    whose funding account was closed fails with ERR_CARD_ACCOUNT_RESTRICTED,
    not a state error — the session state gate already passed.

    Design: Corner/validations/provisioning_session_state_beats_card_account_restricted
    """
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, _agr = setup_issuer_active(api)
    device = setup_device(api, ch)
    account, artifact = setup_account_and_artifact(api, ch, issuer)
    session = open_session(api, device, artifact, ch)
    session = verify_session_twice(api, device, session, ch)
    get_success_data(api.close_card_account(account["id"], OPERATOR))
    fresh = get_success_data(api.get_provisioning_session(session["id"]))
    resp = api.tokenize_session(
        device["id"], session["id"],
        {"expected_session_version": fresh["version"]},
        make_cardholder_headers(ch["id"]))
    err = validate_error(resp, ApiErrorId.ERR_CARD_ACCOUNT_RESTRICTED)
    assert err["error_id"] != ApiErrorId.ERR_INVALID_STATE.value


def test_express_tokenize_requires_agreement_support(api):
    """PRD section 3.4: "requesting express_transit_enabled true requires the
    account's card_product to be TRANSIT and the agreement's
    express_transit_supported to be true, else
    ERR_EXPRESS_TRANSIT_NOT_SUPPORTED"."

    Design: Corner/validations/express_requires_agreement_support_even_when_token_flag_settable
    """
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, _agr = setup_issuer_active(api, express_supported=False)
    device = setup_device(api, ch)
    account, artifact = setup_account_and_artifact(
        api, ch, issuer, card_product="TRANSIT", pan_last4="7777")
    session = open_session(api, device, artifact, ch)
    session = verify_session_twice(api, device, session, ch)
    fresh = get_success_data(api.get_provisioning_session(session["id"]))
    resp = api.tokenize_session(
        device["id"], session["id"],
        {"express_transit_enabled": True,
         "expected_session_version": fresh["version"]},
        make_cardholder_headers(ch["id"]))
    validate_error(resp, ApiErrorId.ERR_EXPRESS_TRANSIT_NOT_SUPPORTED)
