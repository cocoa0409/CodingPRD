"""Corner: error envelope, idempotency conflict, OTP mismatch trio, OCC 412s."""
from test_helpers import (
    OPERATOR,
    ApiErrorId,
    BAD_CODE,
    GOOD_CODE_1,
    GOOD_CODE_2,
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
    validate_success,
)


def test_error_envelope_shape_is_fixed(api):
    """PRD section 2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with response_type "error" and data carrying
    "error_id" and "message"; the PRD states "The meta object for error
    responses contains only api_request_id and api_request_timestamp."

    Design: Corner/errors/error_envelope_shape_is_fixed
    """
    reset_clock(api)
    resp = api.create_cardholder({"legal_name": "No Email"}, None)
    assert resp.status_code == 400
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_VALIDATION"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]


def test_idempotency_conflict_on_reused_key_with_different_payload(api):
    """PRD section 3.4: "the same idempotency_key on the same device replays
    the original session unchanged, while the same key with a different payload
    is ERR_IDEMPOTENCY_CONFLICT."

    Design: Corner/errors/idempotency_conflict_on_reused_key_with_different_payload
    """
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, _agr = setup_issuer_active(api)
    device = setup_device(api, ch)
    account, artifact = setup_account_and_artifact(api, ch, issuer)
    artifact3 = get_success_data(api.create_card_artifact(
        {"card_account_id": account["id"], "pan_last4": "6666",
         "expiry": "0931", "embossing_name": "ADA BYERS"}, OPERATOR))
    session = open_session(api, device, artifact, ch, idem_key="prov-a")
    ch_h = make_cardholder_headers(ch["id"])
    resp = api.create_provisioning_session(
        device["id"],
        {"card_artifact_id": artifact3["id"], "idempotency_key": "prov-a"}, ch_h)
    validate_error(resp, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT)
    current = get_success_data(api.get_provisioning_session(session["id"]))
    assert current["status"] == "VERIFICATION_REQUIRED"


def test_third_otp_mismatch_fails_session(api):
    """PRD section 3.4: "A wrong code is rejected with ERR_OTP_MISMATCH (HTTP
    409), and the third consecutive mismatch on a session fails it outright:
    the session transitions to terminal FAILED even as the error is returned."

    Design: Corner/errors/third_otp_mismatch_fails_session
    """
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, _agr = setup_issuer_active(api)
    device = setup_device(api, ch)
    account, artifact = setup_account_and_artifact(api, ch, issuer)
    session = open_session(api, device, artifact, ch)
    ch_h = make_cardholder_headers(ch["id"])
    for _ in range(3):
        resp = api.verify_session(device["id"], session["id"],
                                  {"method": "OTP_TEXT", "code": BAD_CODE}, ch_h)
        validate_error(resp, ApiErrorId.ERR_OTP_MISMATCH)
    current = get_success_data(api.get_provisioning_session(session["id"]))
    assert current["status"] == "FAILED"
    resp = api.verify_session(device["id"], session["id"],
                              {"method": "OTP_TEXT", "code": GOOD_CODE_1}, ch_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_occ_stale_session_version_rejected_412(api):
    """PRD section 2.5: "Tokenizing a provisioning session requires the field
    expected_session_version in the request body, carrying the
    ProvisioningSession's version as last read by the caller. If the session's
    version has advanced — for example because an earlier verify or tokenize
    already moved it — the tokenize is rejected with ERR_VERSION_CONFLICT
    (HTTP 412)."

    Design: Corner/errors/occ_stale_session_version_rejected_412
    """
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, _agr = setup_issuer_active(api)
    device = setup_device(api, ch)
    account, artifact = setup_account_and_artifact(api, ch, issuer)
    session = open_session(api, device, artifact, ch)
    ch_h = make_cardholder_headers(ch["id"])
    get_success_data(api.verify_session(
        device["id"], session["id"],
        {"method": "OTP_TEXT", "code": GOOD_CODE_1}, ch_h))
    stale = get_success_data(api.get_provisioning_session(session["id"]))
    get_success_data(api.verify_session(
        device["id"], session["id"],
        {"method": "ISSUER_APP", "code": GOOD_CODE_2}, ch_h))
    resp = api.tokenize_session(
        device["id"], session["id"],
        {"expected_session_version": stale["version"]}, ch_h)
    validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT)
    fresh = get_success_data(api.get_provisioning_session(session["id"]))
    resp = api.tokenize_session(
        device["id"], session["id"],
        {"expected_session_version": fresh["version"]}, ch_h)
    token = validate_success(resp, expected_status=201)
    assert token["status"] == "ACTIVE"


def test_occ_stale_device_version_on_default_card_rejected_412(api):
    """PRD section 2.5: "Setting the device default card requires the field
    expected_device_version, carrying the Device's version as last read.
    Because an intervening token deactivation also mutates default_card_id and
    bumps the device version, a mismatch means the caller's choice set may be
    invalidated, and the write is rejected with ERR_VERSION_CONFLICT (HTTP
    412)." An intervening set-security equally bumps the version.

    Design: Corner/errors/occ_stale_device_version_on_default_card_rejected_412
    """
    ns = setup_provisioned_token(api)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    d = ns["device"]["id"]
    dev = get_success_data(api.get_device(d))
    get_success_data(api.set_device_security(
        d, {"passcode_enabled": True, "biometric_enabled": False}, ch))
    resp = api.set_default_card(
        d, {"token_id": ns["token"]["id"],
            "expected_device_version": dev["version"]}, ch)
    validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT)


def test_missing_required_field_returns_validation(api):
    """PRD section 2.10 priority 3: "Payload schema — required fields present,
    enum members valid, integers non-negative where required. Failure:
    ERR_VALIDATION." and section 3.8: "A PlatformAdmin registers a
    TransitOperator with a unique operator_code, a display name, a
    flat_fare_cents charged per tap, an express_cap_cents ceiling". Omitting
    operator_code is a 400 ERR_VALIDATION.

    Design: Corner/errors/every_catalogued_error_is_triggerable
    """
    from test_helpers import ADMIN
    reset_clock(api)
    resp = api.create_transit_operator(
        {"name": "x", "flat_fare_cents": 250, "express_cap_cents": 1000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
