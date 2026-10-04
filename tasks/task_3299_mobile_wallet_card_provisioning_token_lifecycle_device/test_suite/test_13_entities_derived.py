"""Corner: computed posture, system-minted token fields, body FK existence,
allowlist immutability."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    NON_EXISTENT_UUID,
    OPERATOR,
    assert_transit_allowlist_entry,
    create_transit_allowlist_payload,
    create_transit_operator_payload,
    get_success_data,
    make_cardholder_headers,
    reset_clock,
    setup_account_and_artifact,
    setup_cardholder,
    setup_device,
    setup_issuer_active,
    setup_provisioned_token,
    validate_error,
    validate_paginated,
)

UUID_A = "00000000-0000-4000-8000-000000000001"
UUID_B = "00000000-0000-4000-8000-000000000002"


def test_device_security_posture_is_computed_never_stored(api):
    """PRD section 2.11: "if the device's is_lost flag is set, posture is LOST;
    otherwise, if passcode_enabled is false, posture is DEGRADED; otherwise —
    passcode enabled and not lost — posture is HEALTHY. A freshly registered
    device, which has no passcode configured, therefore reports DEGRADED until
    the cardholder enables a passcode."

    Design: Corner/entities/device_security_posture_is_computed_never_stored
    """
    reset_clock(api)
    ch = setup_cardholder(api)
    headers = make_cardholder_headers(ch["id"])
    device = setup_device(api, ch, serial="SN-9", secure=False)
    assert device["security_posture"] == "DEGRADED"
    device = get_success_data(api.set_device_security(
        device["id"], {"passcode_enabled": True, "biometric_enabled": False}, headers))
    assert device["security_posture"] == "HEALTHY"
    device = get_success_data(api.report_device_lost(device["id"], headers))
    assert device["security_posture"] == "LOST"
    device = get_success_data(api.report_device_found(device["id"], headers))
    assert device["security_posture"] == "HEALTHY"


def test_token_created_active_with_zeroed_counters(api):
    """PRD section 3.4: "a PaymentToken is created directly in ACTIVE status —
    bound to this device (device_id), this funding account (card_account_id),
    this artifact (card_artifact_id), and, denormalized for issuer scoping, the
    issuer_id — carrying the minted device_account_number, the requested
    express_transit_enabled flag, and a full set of zeroed counters:
    auth_attempt_count, approved_auth_count, decline_count,
    consecutive_decline_count, and suspension_count, plus null
    last_decline_reason and deactivated_reason."

    Design: Corner/entities/token_create_client_supplied_status_and_counters_are_ignored
    """
    ns = setup_provisioned_token(api)
    token = ns["token"]
    assert token["status"] == "ACTIVE"
    for counter in ("auth_attempt_count", "approved_auth_count", "decline_count",
                    "consecutive_decline_count", "suspension_count"):
        assert token[counter] == 0, f"{counter} expected 0, got {token[counter]}"
    assert token["last_decline_reason"] is None
    assert token["deactivated_reason"] is None
    assert token["device_account_number"]
    assert token["device_account_number"] != ns["artifact"]["pan_last4"]


def test_body_foreign_keys_resolved_after_path_and_missing_program_404(api):
    """PRD section 2.6: "Foreign keys supplied in the request body — such as a
    card_artifact_id on session creation or a merchant_program_id on enrollment
    — are resolved only after all path identifiers have resolved. Existence
    failures surface as 404" with entity-specific codes
    (ERR_PROGRAM_NOT_FOUND, ERR_CARD_ACCOUNT_NOT_FOUND).

    Design: Corner/entities/body_foreign_keys_checked_in_declared_input_order
    """
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, _agr = setup_issuer_active(api)
    account, _art = setup_account_and_artifact(api, ch, issuer,
                                               card_product="CREDIT")
    # unknown program + existing account -> program-specific 404
    resp = api.enroll_merchant_card_program(
        {"merchant_program_id": UUID_A, "card_account_id": account["id"]}, OPERATOR
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND)
    # existing program id is required for the account-specific 404: with an
    # unknown account AND unknown program the failure is still a 404.
    resp = api.enroll_merchant_card_program(
        {"merchant_program_id": UUID_A, "card_account_id": UUID_B}, OPERATOR
    )
    assert resp.status_code == 404
    rows, _meta = validate_paginated(
        api.list_merchant_card_programs(params={"card_account_id": account["id"]})
    )
    assert rows == []


def test_allowlist_entry_carries_only_id_and_created_at(api):
    """PRD section 2.4: "The two exceptions are TransitAllowlist entries and
    TokenEvent records: both carry only id and created_at — updated_at and
    version are absent from both". PRD section 3.8: allowlist rows are "born
    ACTIVE with REMOVED as the exit status."

    Design: Corner/entities/allowlist_is_immutable_common_fields_false
    """
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, _agr = setup_issuer_active(api)
    account, _art = setup_account_and_artifact(api, ch, issuer)
    operator = get_success_data(api.create_transit_operator(
        create_transit_operator_payload(), ADMIN))
    resp = api.add_transit_allowlist(
        create_transit_allowlist_payload(operator["id"], account["id"]), OPERATOR
    )
    from test_helpers import validate_success
    entry = validate_success(resp, expected_status=201)
    assert_transit_allowlist_entry(entry)
    assert entry["status"] == "ACTIVE"
