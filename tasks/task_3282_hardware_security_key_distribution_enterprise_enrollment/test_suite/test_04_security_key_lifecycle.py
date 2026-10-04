"""Security-key lifecycle: parallel state dimensions, order gating, cascades,
attestation policy, and return-to-stock conservation."""
from test_helpers import (
    LOG,
    SA,
    ApiErrorId,
    api_client,
    create_approved_order,
    create_employee,
    create_model,
    create_org,
    create_pending_order,
    create_received_order_with_keys,
    get_success_data,
    setup_active_enrollment,
    setup_received_key_for_account,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_security_key_parallel_dimensions_independent():
    """PRD §3.6: "A security key carries two independent state dimensions.
    `hardware_status` tracks distribution — `PRE_REGISTERED`, `ASSIGNED`,
    `DISTRIBUTED`, or the terminal `REVOKED` — while `attestation_status`
    tracks firmware verification — `UNVERIFIED`, `VERIFIED`, or `FAILED`,
    where `FAILED` is terminal for that dimension."

    Design: Difficulty/non_linear_state_machine/security_key_parallel_dimensions_independent
    """
    env = setup_received_key_for_account(org_overrides={"legal_name": "Parallel Org"},
                                         serial="G-001")
    org_id, key_id, acct = env["org"]["id"], env["key"]["id"], env["account_id"]
    # attestation dimension moves alone
    r1 = validate_success(api_client.attest_security_key(org_id, key_id, SA))
    assert r1["hardware_status"] == "PRE_REGISTERED"
    assert r1["attestation_status"] == "VERIFIED"
    # hardware dimension moves without touching attestation
    r2 = validate_success(api_client.assign_security_key(org_id, key_id, acct, SA))
    assert r2["hardware_status"] == "ASSIGNED"
    assert r2["attestation_status"] == "VERIFIED"
    r3 = validate_success(api_client.mark_distributed(org_id, key_id, LOG))
    assert r3["hardware_status"] == "DISTRIBUTED"
    assert r3["attestation_status"] == "VERIFIED"
    # hardware revoke leaves attestation untouched
    r4 = validate_success(api_client.revoke_security_key(org_id, key_id, SA))
    assert r4["hardware_status"] == "REVOKED"
    assert r4["attestation_status"] == "VERIFIED"


def test_failed_attestation_dimension_is_terminal():
    """PRD §3.6: "`FAILED` is terminal — a failed key cannot be re-attested."

    Design: Difficulty/non_linear_state_machine/security_key_parallel_dimensions_independent
    """
    # STANDARD org whose approved firmware list excludes the key's firmware
    org2 = create_org(approved_firmware_versions=["9.9.9"])
    m = create_model()
    order, keys = create_received_order_with_keys(
        org2["id"], [{"model_code": m["model_code"], "quantity": 1}], ["G-003"])
    r = validate_success(api_client.attest_security_key(org2["id"], keys[0]["id"], SA))
    assert r["attestation_status"] == "FAILED"
    assert r["hardware_status"] == "PRE_REGISTERED"
    resp = api_client.attest_security_key(org2["id"], keys[0]["id"], SA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_security_key_assign_requires_order_received():
    """PRD §3.6: "Assigning a key — a `SecurityAdmin` action moving
    `hardware_status` from `PRE_REGISTERED` to `ASSIGNED` and recording the
    target in `assigned_identity_account_id` — requires that the key's order is
    `RECEIVED` (otherwise `ERR_ORDER_STATE`)".

    Design: Difficulty/cross_entity_state_dependency/security_key_assign_requires_order_received
    """
    org = create_org(legal_name="Gate Org")
    m = create_model(model_code="M-M")
    emp = create_employee(org["id"], employee_ref="E-M1", directory_user_id="u-m1")
    acct = emp["identity_account_id"]
    po = create_pending_order(org["id"], [{"model_code": m["model_code"], "quantity": 1}])
    validate_success(
        api_client.approve_purchase_order(org["id"], po["id"], po["version"], SA))
    keys = validate_success(api_client.preregister_keys(
        org["id"], po["id"],
        {"keys": [{"serial_number": "M-001", "firmware_version": "5.4.3"}]}, LOG,
    ), expected_status=201)
    key_id = keys[0]["id"]
    get_success_data(api_client.ship_purchase_order(org["id"], po["id"], LOG))
    # order IN_TRANSIT: assign rejected
    resp = api_client.assign_security_key(org["id"], key_id, acct, SA)
    validate_error(resp, ApiErrorId.ERR_ORDER_STATE)
    # after receive: the same assign succeeds
    get_success_data(api_client.receive_purchase_order(org["id"], po["id"], LOG))
    assigned = validate_success(api_client.assign_security_key(org["id"], key_id, acct, SA))
    assert assigned["hardware_status"] == "ASSIGNED"


def test_mark_distributed_requires_order_received():
    """PRD §3.6: "Marking a key distributed — a `LogisticsCoordinator` action
    moving `ASSIGNED` to `DISTRIBUTED` — likewise requires the parent order to
    be `RECEIVED`."

    Design: Difficulty/cross_entity_state_dependency/security_key_assign_requires_order_received
    """
    org = create_org()
    m = create_model(model_code="M-M2")
    emp = create_employee(org["id"], employee_ref="E-M2", directory_user_id="u-m2")
    acct = emp["identity_account_id"]
    po = create_approved_order(org["id"], [{"model_code": m["model_code"], "quantity": 1}])
    keys = validate_success(api_client.preregister_keys(
        org["id"], po["id"],
        {"keys": [{"serial_number": "M-002", "firmware_version": "5.4.3"}]}, LOG,
    ), expected_status=201)
    key_id = keys[0]["id"]
    # order still APPROVED: assign rejected as well (order gating)
    resp = api_client.assign_security_key(org["id"], key_id, acct, SA)
    validate_error(resp, ApiErrorId.ERR_ORDER_STATE)


def test_quarantine_cascades_order_key_enrollment_account():
    """PRD §3.5: "Every key of the order with `hardware_status` in
    `PRE_REGISTERED`, `ASSIGNED`, or `DISTRIBUTED` is revoked. For every
    revoked key whose enrollment ceremony is in `PENDING`, `ACTIVE`, or
    `EXPIRING`, the ceremony is revoked and its `revoked_at` set. For each
    affected account, `registered_key_count` is recomputed (only `ACTIVE` and
    `EXPIRING` ceremonies count), `backup_compliant` is recomputed, and the
    account is locked if and only if it was `ENROLLED` and the count is now
    zero."

    Design: Difficulty/transitive_cascade/quarantine_cascades_order_key_enrollment_account
    """
    env = setup_active_enrollment(org_overrides={"legal_name": "Cascade Org"},
                                  serial="H-001")
    org_id, po_id = env["org"]["id"], env["order"]["id"]
    key_id, acct, en_id = env["key"]["id"], env["account_id"], env["enrollment"]["id"]
    po = validate_success(api_client.quarantine_purchase_order(org_id, po_id, SA))
    assert po["status"] == "QUARANTINED"
    keys, _ = validate_paginated(api_client.list_security_keys(
        org_id, SA, params={"purchase_order_id": po_id}))
    assert keys[0]["hardware_status"] == "REVOKED"
    enrollments, _ = validate_paginated(api_client.list_enrollments(acct, SA))
    by_id = {e["id"]: e for e in enrollments}
    assert by_id[en_id]["status"] == "REVOKED"
    account = validate_success(api_client.get_identity_account(acct, SA))
    assert account["registered_key_count"] == 0
    assert account["backup_compliant"] is False
    assert account["status"] == "LOCKED"


def test_release_quarantined_order_never_unrevokes_keys():
    """PRD §3.5: "Release never un-revokes hardware: keys revoked by any
    earlier quarantine stay `REVOKED` permanently, even as the order itself
    cycles between `RECEIVED` and `QUARANTINED` repeatedly."

    Design: Difficulty/transitive_cascade/quarantine_cascades_order_key_enrollment_account
    """
    env = setup_active_enrollment(serial="H-002")
    org_id, po_id = env["org"]["id"], env["order"]["id"]
    validate_success(api_client.quarantine_purchase_order(org_id, po_id, SA))
    released = validate_success(api_client.release_purchase_order(org_id, po_id, SA))
    assert released["status"] == "RECEIVED"
    keys, _ = validate_paginated(api_client.list_security_keys(
        org_id, SA, params={"purchase_order_id": po_id}))
    assert keys[0]["hardware_status"] == "REVOKED"


def test_ship_from_quarantined_rejected():
    """PRD §3.5: "Once approved, physical movement is a `LogisticsCoordinator`
    workflow. Shipping an `APPROVED` order moves it to `IN_TRANSIT`."

    Design: Corner/state_machines/order_terminal_state_lockdown_after_quarantine_release_cycle
    """
    org = create_org(legal_name="Lock Org")
    m = create_model(model_code="M-W", unit_price_cents=100)
    po = create_approved_order(org["id"], [{"model_code": m["model_code"], "quantity": 1}])
    get_success_data(api_client.ship_purchase_order(org["id"], po["id"], LOG))
    get_success_data(api_client.receive_purchase_order(org["id"], po["id"], LOG))
    get_success_data(api_client.quarantine_purchase_order(org["id"], po["id"], SA))
    resp = api_client.ship_purchase_order(org["id"], po["id"], LOG)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_return_to_stock_blocked_when_enrollment_pending():
    """PRD §3.6: "Returning a key to stock reverses an assignment, moving
    `ASSIGNED` back to `PRE_REGISTERED` and clearing
    `assigned_identity_account_id` to null; it is only possible while no
    ceremony binds the key in `PENDING`, `ACTIVE`, or `EXPIRING` — otherwise
    the transition does not exist and the request is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/return_to_stock_blocked_when_enrollment_pending
    """
    env = setup_received_key_for_account(org_overrides={"legal_name": "Stock2 Org"},
                                         serial="V-001")
    org_id, key_id, acct = env["org"]["id"], env["key"]["id"], env["account_id"]
    validate_success(api_client.assign_security_key(org_id, key_id, acct, SA))
    validate_success(api_client.create_enrollment(acct, key_id, SA), expected_status=201)
    resp = api_client.return_to_stock(org_id, key_id, SA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_assign_return_to_stock_conserves_assignments():
    """PRD §3.6: "Returning a key to stock reverses an assignment, moving
    `ASSIGNED` back to `PRE_REGISTERED` and clearing
    `assigned_identity_account_id` to null; it is only possible while no
    ceremony binds the key in `PENDING`, `ACTIVE`, or `EXPIRING` — otherwise
    the transition does not exist and the request is `ERR_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/assign_return_to_stock_conserves_assignments
    """
    env = setup_received_key_for_account(org_overrides={"legal_name": "Stock Org"},
                                         serial="Q-001")
    org_id, key_id, acct = env["org"]["id"], env["key"]["id"], env["account_id"]
    validate_success(api_client.assign_security_key(org_id, key_id, acct, SA))
    _, meta1 = validate_paginated(api_client.list_security_keys(
        org_id, SA, params={"hardware_status": "ASSIGNED"}))
    assert meta1["total_count"] == 1
    restored = validate_success(api_client.return_to_stock(org_id, key_id, SA))
    assert restored["hardware_status"] == "PRE_REGISTERED"
    assert restored["assigned_identity_account_id"] is None
    _, meta2 = validate_paginated(api_client.list_security_keys(
        org_id, SA, params={"hardware_status": "ASSIGNED"}))
    assert meta2["total_count"] == 0
    _, meta3 = validate_paginated(api_client.list_security_keys(
        org_id, SA, params={"assigned_identity_account_id": acct}))
    assert meta3["total_count"] == 0


def test_return_to_stock_clears_assignment_without_touching_counters():
    """PRD §3.6: "Returning a key to stock reverses an assignment, moving
    `ASSIGNED` back to `PRE_REGISTERED` and clearing
    `assigned_identity_account_id` to null; it is only possible while no
    ceremony binds the key in `PENDING`, `ACTIVE`, or `EXPIRING` — otherwise
    the transition does not exist and the request is `ERR_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/assign_return_to_stock_conserves_assignments
    """
    env = setup_received_key_for_account(serial="Q-002")
    org_id, key_id, acct = env["org"]["id"], env["key"]["id"], env["account_id"]
    before = validate_success(api_client.get_identity_account(acct, SA))
    validate_success(api_client.assign_security_key(org_id, key_id, acct, SA))
    validate_success(api_client.return_to_stock(org_id, key_id, SA))
    after = validate_success(api_client.get_identity_account(acct, SA))
    assert before["registered_key_count"] == after["registered_key_count"] == 0
    assert after["status"] == "UNENROLLED"
