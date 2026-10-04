"""Enrollment ceremonies: activation preconditions, OCC, dual-variant
backup compliance, cyclic renewal, expiry window, refresh supersede."""
from test_helpers import (
    LOG,
    SA,
    ApiErrorId,
    api_client,
    account_version,
    create_and_activate_enrollment,
    create_device,
    create_employee,
    create_model,
    create_org,
    create_received_order_with_keys,
    create_subscription,
    run_periodic,
    set_clock,
    setup_account_with_active_enrollments,
    setup_active_enrollment,
    setup_received_key_for_account,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_backup_compliance_standard_vs_strict():
    """PRD §3.3: "`backup_compliant` compares that count against the effective
    backup minimum: the organization's configured `backup_key_minimum` when its
    `authentication_policy` is `STANDARD`, or that value plus one when the
    policy is `PHISHING_RESISTANT`."

    Design: Difficulty/dual_variant_calc/backup_compliance_standard_vs_strict
    """
    std = setup_account_with_active_enrollments(
        2, org_overrides={"legal_name": "Std Org", "backup_key_minimum": 2},
        serial_prefix="S")
    pr = setup_account_with_active_enrollments(
        2,
        org_overrides={"legal_name": "PR Org",
                       "authentication_policy": "PHISHING_RESISTANT",
                       "backup_key_minimum": 2},
        serial_prefix="P")
    acct_s = validate_success(api_client.get_identity_account(std["account_id"], SA))
    acct_p = validate_success(api_client.get_identity_account(pr["account_id"], SA))
    assert acct_s["registered_key_count"] == 2
    assert acct_p["registered_key_count"] == 2
    assert acct_s["backup_compliant"] is True
    assert acct_p["backup_compliant"] is False


def test_backup_compliant_flips_when_count_drops_below_minimum():
    """PRD §3.3: "The account is compliant when its count is at least the
    effective minimum."

    Design: Difficulty/dual_variant_calc/backup_compliance_standard_vs_strict
    """
    env = setup_account_with_active_enrollments(
        2, org_overrides={"backup_key_minimum": 2}, serial_prefix="B")
    acct = env["account_id"]
    before = validate_success(api_client.get_identity_account(acct, SA))
    assert before["backup_compliant"] is True
    # revoke one ACTIVE ceremony: count 1 < 2 -> not compliant
    validate_success(api_client.revoke_enrollment(
        acct, env["enrollments"][0]["id"], SA))
    after = validate_success(api_client.get_identity_account(acct, SA))
    assert after["registered_key_count"] == 1
    assert after["backup_compliant"] is False
    assert after["status"] == "ENROLLED"


def test_enrollment_expiring_active_cycle_once_per_period():
    """PRD §3.7: "Renewal lets a `SecurityAdmin` pull an `EXPIRING` ceremony
    back to `ACTIVE`, provided the single per-period renewal has not been
    consumed — `renewal_count` must still be 0 — and the key remains
    `DISTRIBUTED` and `VERIFIED`. Renewal recomputes `expires_at` to 365 days
    from the renewal moment and sets `renewal_count` to 1, consuming the
    period's renewal; a second renewal attempt before the next sweep-driven
    transition is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/enrollment_expiring_active_cycle_once_per_period
    """
    env = setup_active_enrollment(org_overrides={"legal_name": "Cycle Org",
                                                 "backup_key_minimum": 2},
                                  serial="C-001")
    acct, en = env["account_id"], env["enrollment"]
    # activated at 2026-09-01 -> expires 2027-09-01; inside the 30-day window
    set_clock("2027-08-10T00:00:00Z")
    counts = run_periodic()
    assert counts["enrollments_expiring"] == 1
    renewed = validate_success(api_client.renew_enrollment(acct, en["id"], SA))
    assert renewed["status"] == "ACTIVE"
    assert renewed["renewal_count"] == 1
    assert renewed["expires_at"].startswith("2028-08-09T00:00:00")
    resp = api_client.renew_enrollment(acct, en["id"], SA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_renewal_of_active_ceremony_rejected():
    """PRD §3.7: "Renewal lets a `SecurityAdmin` pull an `EXPIRING` ceremony
    back to `ACTIVE`, provided the single per-period renewal has not been
    consumed — `renewal_count` must still be 0 — and the key remains
    `DISTRIBUTED` and `VERIFIED`."

    Design: Difficulty/non_linear_state_machine/enrollment_expiring_active_cycle_once_per_period
    """
    env = setup_active_enrollment(serial="C-002")
    resp = api_client.renew_enrollment(env["account_id"], env["enrollment"]["id"], SA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_enrollment_activation_requires_key_distributed_and_verified():
    """PRD §3.7: "The ceremony must be `PENDING`; the key's `hardware_status`
    must be `DISTRIBUTED` and its `attestation_status` must be `VERIFIED`; the
    key's `assigned_identity_account_id` must equal the ceremony's account".

    Design: Difficulty/cross_entity_state_dependency/enrollment_activation_requires_key_distributed_and_verified
    """
    env = setup_received_key_for_account(org_overrides={"legal_name": "Act Org"},
                                         serial="N-001")
    org_id, key_id, acct = env["org"]["id"], env["key"]["id"], env["account_id"]
    validate_success(api_client.attest_security_key(org_id, key_id, SA))
    validate_success(api_client.assign_security_key(org_id, key_id, acct, SA))
    ceremony = validate_success(api_client.create_enrollment(acct, key_id, SA),
                                expected_status=201)
    version = account_version(acct)
    resp = api_client.activate_enrollment(acct, ceremony["id"], version, SA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    validate_success(api_client.mark_distributed(org_id, key_id, LOG))
    activated = validate_success(
        api_client.activate_enrollment(acct, ceremony["id"], version, SA))
    assert activated["status"] == "ACTIVE"


def test_activation_requires_verified_attestation():
    """PRD §3.7: "The ceremony must be `PENDING`; the key's `hardware_status`
    must be `DISTRIBUTED` and its `attestation_status` must be `VERIFIED`; the
    key's `assigned_identity_account_id` must equal the ceremony's account".

    Design: Difficulty/cross_entity_state_dependency/enrollment_activation_requires_key_distributed_and_verified
    """
    env = setup_received_key_for_account(serial="N-002")
    org_id, key_id, acct = env["org"]["id"], env["key"]["id"], env["account_id"]
    # distribute WITHOUT attesting: attestation gate must block activation
    validate_success(api_client.assign_security_key(org_id, key_id, acct, SA))
    validate_success(api_client.mark_distributed(org_id, key_id, LOG))
    ceremony = validate_success(api_client.create_enrollment(acct, key_id, SA),
                                expected_status=201)
    resp = api_client.activate_enrollment(
        acct, ceremony["id"], account_version(acct), SA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_enrollment_validity_window_adjacent_cycle_no_overlap():
    """PRD §3.7: "The boundary is strict: at the exact instant equal to
    `expires_at` the enrollment is still valid — lapse requires now to be
    strictly later than `expires_at`."

    Design: Difficulty/resource_temporal_overlap/enrollment_validity_window_adjacent_cycle_no_overlap
    """
    env = setup_active_enrollment(org_overrides={"legal_name": "Window Org",
                                                 "backup_key_minimum": 1},
                                  serial="O-001")
    acct, en = env["account_id"], env["enrollment"]
    # activated at 2026-09-01 -> expires_at 2027-09-01
    set_clock("2027-09-01T00:00:00Z")
    counts = run_periodic()
    assert counts["enrollments_expiring"] == 1
    assert counts["enrollments_expired"] == 0
    enrollments, _ = validate_paginated(api_client.list_enrollments(acct, SA))
    assert enrollments[0]["status"] == "EXPIRING"


def test_expiry_sweep_revokes_after_expires_at():
    """PRD §3.7: "When the current time passes `expires_at`, a ceremony in
    `ACTIVE` or `EXPIRING` is revoked by the sweep with `revoked_at` set, the
    account's count falls by one, `backup_compliant` is recomputed, and the
    account locks if it was `ENROLLED` and the count hit zero."

    Design: Difficulty/resource_temporal_overlap/enrollment_validity_window_adjacent_cycle_no_overlap
    """
    env = setup_active_enrollment(org_overrides={"backup_key_minimum": 1},
                                  serial="O-002")
    acct, en = env["account_id"], env["enrollment"]
    set_clock("2027-09-02T00:00:00Z")
    counts = run_periodic()
    assert counts["enrollments_expired"] == 1
    enrollments, _ = validate_paginated(api_client.list_enrollments(acct, SA))
    assert enrollments[0]["status"] == "REVOKED"
    assert enrollments[0]["revoked_at"] is not None
    account = validate_success(api_client.get_identity_account(acct, SA))
    assert account["registered_key_count"] == 0
    assert account["status"] == "LOCKED"


def test_refresh_supersede_conserves_registered_key_count():
    """PRD §3.8: "The account's old ceremony in `ACTIVE` or `EXPIRING` becomes
    `SUPERSEDED` and the old key is revoked; because the replacement activation
    offsets the supersede in the same run, the account's
    `registered_key_count` is unchanged by the exchange."

    Design: Difficulty/compensating_invariant/refresh_supersede_conserves_registered_key_count
    """
    org = create_org(legal_name="Refresh Org", backup_key_minimum=1)
    m = create_model(model_code="M-P", unit_price_cents=150)
    create_device(org["id"], asset_tag="D-16", platform="WINDOWS",
                  connectors=["USB_C"], protocol_capability=["FIDO2"])
    emp = create_employee(org["id"], employee_ref="E-R1", directory_user_id="u-r1")
    acct = emp["identity_account_id"]
    order, keys = create_received_order_with_keys(
        org["id"], [{"model_code": m["model_code"], "quantity": 2}],
        ["P-101", "P-102"])
    # k_a enrolled ACTIVE; k_b spare (attested but PRE_REGISTERED)
    validate_success(api_client.attest_security_key(org["id"], keys[0]["id"], SA))
    validate_success(api_client.attest_security_key(org["id"], keys[1]["id"], SA))
    validate_success(api_client.assign_security_key(org["id"], keys[0]["id"], acct, SA))
    validate_success(api_client.mark_distributed(org["id"], keys[0]["id"], LOG))
    old_en = create_and_activate_enrollment(acct, keys[0]["id"])
    create_subscription(org["id"], tier="ENTERPRISE", refresh_interval_days=30,
                        replacement_credits_total=10)
    before = validate_success(api_client.get_identity_account(acct, SA))
    assert before["registered_key_count"] == 1
    # subscription created at 2026-09-01 -> period end 2026-10-01
    set_clock("2026-10-02T00:00:00Z")
    counts = run_periodic(organization_id=org["id"])
    assert counts["refreshed_accounts"] == 1
    after = validate_success(api_client.get_identity_account(acct, SA))
    assert after["registered_key_count"] == 1
    superseded, _ = validate_paginated(api_client.list_enrollments(
        acct, SA, params={"status": "SUPERSEDED"}))
    assert any(e["id"] == old_en["id"] for e in superseded)


def test_refresh_run_consumes_one_credit_per_account():
    """PRD §3.8: "The subscription's `credits_used` rises by one and
    `credits_remaining` falls by one; if that empties the pool, the
    subscription becomes `EXHAUSTED`."

    Design: Difficulty/compensating_invariant/refresh_supersede_conserves_registered_key_count
    """
    org = create_org(backup_key_minimum=1)
    m = create_model(model_code="M-P2", unit_price_cents=150)
    create_device(org["id"], asset_tag="D-26", platform="WINDOWS",
                  connectors=["USB_C"], protocol_capability=["FIDO2"])
    emp = create_employee(org["id"], employee_ref="E-R2", directory_user_id="u-r2x")
    acct = emp["identity_account_id"]
    order, keys = create_received_order_with_keys(
        org["id"], [{"model_code": m["model_code"], "quantity": 2}],
        ["P-201", "P-202"])
    validate_success(api_client.attest_security_key(org["id"], keys[0]["id"], SA))
    validate_success(api_client.attest_security_key(org["id"], keys[1]["id"], SA))
    validate_success(api_client.assign_security_key(org["id"], keys[0]["id"], acct, SA))
    validate_success(api_client.mark_distributed(org["id"], keys[0]["id"], LOG))
    create_and_activate_enrollment(acct, keys[0]["id"])
    create_subscription(org["id"], tier="ENTERPRISE", refresh_interval_days=30,
                        replacement_credits_total=1)
    set_clock("2026-10-02T00:00:00Z")
    counts = run_periodic(organization_id=org["id"])
    assert counts["refreshed_accounts"] == 1
    subs = validate_success(api_client.list_subscriptions(org["id"], SA))
    assert subs[0]["credits_used"] == 1
    assert subs[0]["credits_remaining"] == 0
    assert subs[0]["status"] == "EXHAUSTED"
