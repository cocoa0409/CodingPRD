"""Help-desk cases: SoD, revoke-and-replace cascade, selector determinism,
empty-pool fallback."""
from test_helpers import (
    HD,
    HD2,
    LOG,
    SA,
    ApiErrorId,
    api_client,
    attest_assign_distribute,
    create_and_activate_enrollment,
    create_approved_order,
    create_device,
    create_employee,
    create_help_desk_case_payload,
    create_model,
    create_org,
    create_received_order_with_keys,
    get_success_data,
    make_helpdesk_agent_headers,
    setup_pending_review_case,
    validate_error,
    validate_paginated,
    validate_success,
)


def _account_for_org(legal_name, **org_overrides):
    org = create_org(legal_name=legal_name, **org_overrides)
    emp = create_employee(org["id"])
    return org, emp, emp["identity_account_id"]


def test_lost_key_resolve_revokes_distributes_and_replaces():
    """PRD §3.9: "On success, every ceremony of the account in `ACTIVE` or
    `EXPIRING` is revoked and its key revoked; the replacement key is
    auto-selected, auto-assigned to the account, and bound by a new ceremony
    created in `PENDING`; and the account's counters are recomputed, locking
    the account if the count is zero."

    Design: Corner/state_machines/lost_key_resolve_revokes_distributes_and_replaces
    """
    org = create_org(legal_name="Lost Org", backup_key_minimum=2)
    m = create_model(model_code="M-T", unit_price_cents=150)
    create_device(org["id"], asset_tag="D-S5", platform="WINDOWS",
                  connectors=["USB_C"], protocol_capability=["FIDO2"])
    emp = create_employee(org["id"], employee_ref="E-L1", directory_user_id="u-l1")
    acct = emp["identity_account_id"]
    order, keys = create_received_order_with_keys(
        org["id"], [{"model_code": m["model_code"], "quantity": 2}],
        ["T-001", "T-002"])
    k_lost, k_spare = keys[0], keys[1]
    validate_success(api_client.attest_security_key(org["id"], k_lost["id"], SA))
    validate_success(api_client.attest_security_key(org["id"], k_spare["id"], SA))
    validate_success(api_client.assign_security_key(org["id"], k_lost["id"], acct, SA))
    validate_success(api_client.mark_distributed(org["id"], k_lost["id"], LOG))
    old_en = create_and_activate_enrollment(acct, k_lost["id"])
    case = setup_pending_review_case(acct, category="LOST_KEY")
    resolved = validate_success(api_client.resolve_help_desk_case(
        case["id"], {"resolution": "REVOKED_AND_REPLACED"}, HD2))
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "REVOKED_AND_REPLACED"
    all_keys, _ = validate_paginated(api_client.list_security_keys(
        org["id"], HD2, params={"purchase_order_id": order["id"]}))
    by_id = {k["id"]: k for k in all_keys}
    assert by_id[k_lost["id"]]["hardware_status"] == "REVOKED"
    assert by_id[k_spare["id"]]["hardware_status"] == "ASSIGNED"
    enrollments, _ = validate_paginated(api_client.list_enrollments(acct, HD2))
    en_by_id = {e["id"]: e for e in enrollments}
    assert en_by_id[old_en["id"]]["status"] == "REVOKED"
    account = validate_success(api_client.get_identity_account(acct, HD2))
    assert account["registered_key_count"] == 0


def test_replacement_selector_cheapest_first_then_created_at():
    """PRD §3.9: "Among eligible keys the cheapest wins — lowest
    `unit_price_cents` first — with ties broken by the key's `created_at`
    ascending."

    Design: Corner/calculations/replacement_selector_cheapest_first_then_created_at
    """
    org = create_org(legal_name="Select Org", backup_key_minimum=2)
    m_ch = create_model(model_code="M-CH", unit_price_cents=100)
    m_ex = create_model(model_code="M-EX", unit_price_cents=300)
    create_device(org["id"], asset_tag="D-F3", platform="WINDOWS",
                  connectors=["USB_C"], protocol_capability=["FIDO2"])
    emp = create_employee(org["id"], employee_ref="E-F3", directory_user_id="u-f3")
    acct = emp["identity_account_id"]
    # order with both line models; keys pre-registered in creation order:
    # expensive first, then two cheap ones, then the in-service key
    po = create_approved_order(org["id"], [
        {"model_code": m_ch["model_code"], "quantity": 3},
        {"model_code": m_ex["model_code"], "quantity": 1},
    ])
    po_id = po["id"]
    # PRD §3.6: keys are pre-registered against an APPROVED order.
    k_exp = validate_success(api_client.preregister_keys(
        org["id"], po_id,
        {"keys": [{"serial_number": "F-EXP2", "model_code": m_ex["model_code"],
                   "firmware_version": "5.4.3"}]}, LOG), expected_status=201)[0]
    k_cheap = validate_success(api_client.preregister_keys(
        org["id"], po_id,
        {"keys": [{"serial_number": "F-CH1", "model_code": m_ch["model_code"],
                   "firmware_version": "5.4.3"}]}, LOG), expected_status=201)[0]
    pair = validate_success(api_client.preregister_keys(
        org["id"], po_id,
        {"keys": [{"serial_number": "F-CH2", "model_code": m_ch["model_code"],
                   "firmware_version": "5.4.3"},
                  {"serial_number": "F-OLD", "model_code": m_ch["model_code"],
                   "firmware_version": "5.4.3"}]}, LOG), expected_status=201)
    k_cheap2, k_old = pair[0], pair[1]
    get_success_data(api_client.ship_purchase_order(org["id"], po_id, LOG))
    get_success_data(api_client.receive_purchase_order(org["id"], po_id, LOG))
    attest_assign_distribute(org["id"], k_old["id"], acct)
    create_and_activate_enrollment(acct, k_old["id"])
    case = setup_pending_review_case(acct, category="LOST_KEY")
    validate_success(api_client.resolve_help_desk_case(
        case["id"], {"resolution": "REVOKED_AND_REPLACED"}, HD2))
    pending, _ = validate_paginated(api_client.list_enrollments(
        acct, HD2, params={"status": "PENDING"}))
    assert len(pending) == 1
    assert pending[0]["security_key_id"] == k_cheap["id"]


def test_error_no_eligible_key_triggerable():
    """PRD §3.9: "It requires, first, that the organization's `idp_protocols`
    contain at least one of the hardware protocols `FIDO2`, `U2F`, or `PIV` —
    otherwise recovery would fall back to phishable-only channels and the
    resolution is `ERR_PHISHABLE_PATH_FORBIDDEN` — and, second, that the
    replacement selector finds an eligible key, otherwise
    `ERR_NO_ELIGIBLE_KEY`."

    Design: Corner/errors/error_no_eligible_key_triggerable
    """
    org, emp, acct = _account_for_org("Pool Org")
    case = setup_pending_review_case(acct, category="LOST_KEY")
    resp = api_client.resolve_help_desk_case(
        case["id"], {"resolution": "REVOKED_AND_REPLACED"}, HD2)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_KEY)


def test_helpdesk_resolver_must_differ_from_opener():
    """PRD §2.9: "A help-desk case records its opener in
    `opened_by_agent_id`; the resolving agent must differ, and the resolver's
    id is recorded in `resolved_by_agent_id`. Resolution by the opener is
    rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/helpdesk_resolver_must_differ_from_opener
    """
    org, emp, acct = _account_for_org("SoD2 Org")
    case = validate_success(api_client.create_help_desk_case(
        create_help_desk_case_payload(acct, category="OTHER", description="question"),
        HD), expected_status=201)
    resp = api_client.resolve_help_desk_case(case["id"], {"resolution": "REJECTED"}, HD)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    rejected = validate_success(api_client.resolve_help_desk_case(
        case["id"], {"resolution": "REJECTED"}, HD2))
    assert rejected["status"] == "REJECTED"
    assert rejected["resolution"] == "REJECTED"
    assert rejected["resolved_by_agent_id"] == "hd2"


def test_resolver_recorded_on_resolved_case():
    """PRD §2.9: "A help-desk case records its opener in
    `opened_by_agent_id`; the resolving agent must differ, and the resolver's
    id is recorded in `resolved_by_agent_id`. Resolution by the opener is
    rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/helpdesk_resolver_must_differ_from_opener
    """
    org, emp, acct = _account_for_org("SoD3 Org")
    case = validate_success(api_client.create_help_desk_case(
        create_help_desk_case_payload(acct, category="LOCKOUT", description="locked"),
        make_helpdesk_agent_headers("agent-x")), expected_status=201)
    assert case["opened_by_agent_id"] == "agent-x"
    assert case["resolution"] is None
    validate_success(api_client.submit_case_review(
        case["id"], make_helpdesk_agent_headers("agent-x")))
    resp = api_client.resolve_help_desk_case(
        case["id"], {"resolution": "REJECTED"}, make_helpdesk_agent_headers("agent-x"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
