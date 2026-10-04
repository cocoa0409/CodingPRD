"""Auth, scoping, RBAC, optimistic concurrency, initial states."""
from test_helpers import (
    HD,
    LOG,
    NON_EXISTENT_UUID,
    PA,
    PROC,
    SA,
    ApiErrorId,
    api_client,
    account_version,
    attest_assign_distribute,
    create_approved_order,
    create_employee,
    create_model,
    create_org,
    create_pending_order,
    create_received_order_with_keys,
    get_success_data,
    make_procurement_admin_headers,
    make_security_admin_headers,
    setup_received_key_for_account,
    validate_error,
    validate_success,
)


def test_missing_auth_headers_returns_unauthenticated():
    """PRD §2.1: "A request missing either header, or carrying a role string
    outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    resp = api_client.create_organization(
        {"legal_name": "No Auth", "assurance_tier": "STANDARD",
         "authentication_policy": "STANDARD", "idp_protocols": ["FIDO2"]},
        {},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_unknown_organization_id_returns_not_found():
    """PRD §2.5: "Only then does existence checking occur: every path
    identifier and every foreign-key reference in the body must resolve,
    validated left-to-right along the path, and every referenced entity must
    belong to the organization scope carried in the path — a resource that
    exists but sits outside the caller's organization scope is reported as not
    found, never as forbidden. Both of those failures surface as
    `ERR_NOT_FOUND`."

    Design: Corner/validations/unknown_organization_id_returns_not_found
    """
    resp = api_client.list_devices(NON_EXISTENT_UUID, SA)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_cross_org_reference_returns_not_found_not_forbidden():
    """PRD §2.10: "A device, employee, purchase order, security key, or
    subscription referenced under the wrong organization is `ERR_NOT_FOUND`,
    even when it exists elsewhere."

    Design: Corner/validations/cross_org_reference_returns_not_found_not_forbidden
    """
    org_a = create_org(legal_name="Org V1")
    org_b = create_org(legal_name="Org V2")
    m = create_model(model_code="M-VV", unit_price_cents=100)
    po = create_approved_order(org_a["id"], [{"model_code": m["model_code"], "quantity": 1}])
    keys = validate_success(api_client.preregister_keys(
        org_a["id"], po["id"],
        {"keys": [{"serial_number": "VV-1", "firmware_version": "5.4.3"}]}, LOG,
    ), expected_status=201)
    resp = api_client.attest_security_key(org_b["id"], keys[0]["id"], SA)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_segregation_of_duties_on_purchase_approval():
    """PRD §2.9: "A purchase order records the `X-User-ID` of its creator in
    `created_by`; the approval must come from a different user — an approver
    whose `X-User-ID` equals `created_by` is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

    Design: Corner/validations/segregation_of_duties_on_purchase_approval
    """
    org = create_org(legal_name="SoD Org")
    m = create_model(model_code="M-V3", unit_price_cents=100)
    po = create_pending_order(
        org["id"], [{"model_code": m["model_code"], "quantity": 1}],
        creator_headers=make_procurement_admin_headers("shared-user"))
    assert po["created_by"] == "shared-user"
    resp = api_client.approve_purchase_order(
        org["id"], po["id"], po["version"],
        make_security_admin_headers("shared-user"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    approved = validate_success(api_client.approve_purchase_order(
        org["id"], po["id"], po["version"], SA))
    assert approved["status"] == "APPROVED"


def test_logistics_cannot_approve_purchase_order():
    """PRD §2.1: "A request whose role is not permitted for the endpoint is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/logistics_cannot_approve_purchase_order
    """
    org = create_org(legal_name="RBAC Org")
    m = create_model(model_code="M-B1", unit_price_cents=100)
    po = create_pending_order(org["id"], [{"model_code": m["model_code"], "quantity": 1}])
    resp = api_client.approve_purchase_order(org["id"], po["id"], po["version"], LOG)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_occ_stale_version_on_enrollment_activation():
    """PRD §2.6: "Activating an enrollment ceremony requires
    `expected_identity_account_version`, holding the account's `version` as
    last observed; if another writer has since advanced the account's version
    — for instance by activating a different ceremony for the same account,
    legitimately raising `registered_key_count` — the activation is rejected
    with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on
    a view of the account it has not observed."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_enrollment_activation
    """
    org = create_org(legal_name="OCC Org")
    m = create_model(model_code="M-O1", unit_price_cents=100)
    emp = create_employee(org["id"], employee_ref="E-O1", directory_user_id="u-o1")
    acct = emp["identity_account_id"]
    order, keys = create_received_order_with_keys(
        org["id"], [{"model_code": m["model_code"], "quantity": 2}],
        ["O-101", "O-102"])
    ka, kb = keys[0], keys[1]
    attest_assign_distribute(org["id"], ka["id"], acct)
    attest_assign_distribute(org["id"], kb["id"], acct)
    en_a = validate_success(api_client.create_enrollment(acct, ka["id"], SA),
                            expected_status=201)
    en_b = validate_success(api_client.create_enrollment(acct, kb["id"], SA),
                            expected_status=201)
    captured_version = account_version(acct)
    activated = validate_success(api_client.activate_enrollment(
        acct, en_a["id"], captured_version, SA))
    assert activated["status"] == "ACTIVE"
    resp = api_client.activate_enrollment(acct, en_b["id"], captured_version, SA)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_occ_stale_version_on_purchase_order_approval():
    """PRD §2.6: "Approving a purchase order requires the request body to
    carry `expected_purchase_order_version`, holding the order's `version` as
    the client last observed it; if the order's current `version` has advanced
    — because a prior approval attempt or shipment-state change legitimately
    moved it forward — the approval is rejected with `ERR_STALE_VERSION` (HTTP
    412), since the approver's quoted figures are stale."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_enrollment_activation
    """
    org = create_org()
    m = create_model(model_code="M-O2b", unit_price_cents=100)
    po = create_pending_order(org["id"], [{"model_code": m["model_code"], "quantity": 1}])
    # first approval advances the order version
    validate_success(api_client.approve_purchase_order(org["id"], po["id"], po["version"], SA))
    # second approval with the stale captured version is rejected
    resp = api_client.approve_purchase_order(org["id"], po["id"], po["version"], SA)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_initial_state_of_each_entity():
    """PRD §3.4: "The order is created in `PENDING_APPROVAL`, its `created_by`
    is set from the caller's `X-User-ID`, and two derived figures are frozen at
    creation: `line_count`, the total unit count across all lines, and
    `quoted_total_cents`, computed by the provisional variant of the order-total
    calculation."
    PRD §3.6: "A key begins `PRE_REGISTERED` and `UNVERIFIED`."
    PRD §3.9: "The grant is created `ACTIVE`, its `starts_at` set to the
    creation instant on the logical clock, and its `expires_at` computed as
    `starts_at` plus `duration_hours` hours."
    PRD §3.9: "the opener's `X-User-ID` is recorded in `opened_by_agent_id`,
    and the case starts `OPEN` with `resolution` null."

    Design: Corner/state_machines/initial_state_of_each_entity
    """
    org = create_org(legal_name="Init Org")
    m = create_model(model_code="M-U", unit_price_cents=100)
    emp = create_employee(org["id"], employee_ref="E-I1", directory_user_id="u-i1")
    acct = emp["identity_account_id"]
    po = create_pending_order(org["id"], [{"model_code": m["model_code"], "quantity": 1}])
    assert po["status"] == "PENDING_APPROVAL"
    validate_success(api_client.approve_purchase_order(org["id"], po["id"], po["version"], SA))
    keys = validate_success(api_client.preregister_keys(
        org["id"], po["id"],
        {"keys": [{"serial_number": "U-001", "firmware_version": "5.4.3"}]}, LOG,
    ), expected_status=201)
    assert keys[0]["hardware_status"] == "PRE_REGISTERED"
    assert keys[0]["attestation_status"] == "UNVERIFIED"
    grant = validate_success(api_client.create_temporary_access(
        acct, {"method": "SMART_CARD", "duration_hours": 4}, HD), expected_status=201)
    assert grant["status"] == "ACTIVE"
    case = validate_success(api_client.create_help_desk_case(
        {"identity_account_id": acct, "category": "OTHER", "description": "check"},
        HD), expected_status=201)
    assert case["status"] == "OPEN"
    assert case["resolution"] is None


def test_error_invalid_request_for_missing_required_field():
    """PRD §2.5: "Well-formedness comes first: required fields present, enum
    values valid, no unknown fields, and bulk elements structurally valid — a
    malformed body is rejected with `ERR_INVALID_REQUEST` before anything else
    is examined."

    Design: Corner/errors/error_invalid_request_for_missing_required_field
    """
    resp = api_client.create_key_model(
        {"model_code": "M-BAD", "connectors": ["USB_C"], "protocols": ["FIDO2"],
         "form_factor": "KEYCHAIN"},
        PA,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_activate_with_stale_version_and_bad_protocol_state_occ_wins():
    """PRD §2.5: "After existence, state checks fire: if the target resource is
    not in a state from which the requested transition exists, the request is
    rejected with `ERR_INVALID_STATE`. Then optimistic-concurrency checks: a
    stale `expected_identity_account_version` or
    `expected_purchase_order_version` yields `ERR_STALE_VERSION`."

    Design: Difficulty/priority_pair_validation_conflict/activate_with_stale_version_and_bad_protocol_state_occ_wins
    """
    org = create_org(legal_name="PIV Org", idp_protocols=["PIV"])
    m = create_model(model_code="M-K", connectors=["USB_C"], protocols=["PIV"],
                     unit_price_cents=150)
    emp = create_employee(org["id"], employee_ref="E-K1", directory_user_id="u-k1")
    acct = emp["identity_account_id"]
    captured_version = account_version(acct)
    order, keys = create_received_order_with_keys(
        org["id"], [{"model_code": m["model_code"], "quantity": 1}], ["K-001"])
    key_id = keys[0]["id"]
    validate_success(api_client.attest_security_key(org["id"], key_id, SA))
    ceremony = validate_success(api_client.create_enrollment(acct, key_id, SA),
                                expected_status=201)
    # a lock advances the account version past the captured one
    locked = validate_success(api_client.lock_identity_account(acct, SA))
    assert locked["version"] > captured_version
    resp = api_client.activate_enrollment(acct, ceremony["id"], captured_version, SA)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_activate_with_current_version_succeeds_from_locked():
    """PRD §3.7: "the account must be `UNENROLLED`, `ENROLLED`, or `LOCKED` —
    the `LOCKED` path being the sanctioned re-enrollment route back into
    service".

    Design: Difficulty/priority_pair_validation_conflict/activate_with_stale_version_and_bad_protocol_state_occ_wins
    """
    org = create_org(idp_protocols=["PIV"])
    m = create_model(model_code="M-K2", connectors=["USB_C"], protocols=["PIV"],
                     unit_price_cents=150)
    emp = create_employee(org["id"], employee_ref="E-K2", directory_user_id="u-k2")
    acct = emp["identity_account_id"]
    order, keys = create_received_order_with_keys(
        org["id"], [{"model_code": m["model_code"], "quantity": 1}], ["K-002"])
    key_id = keys[0]["id"]
    validate_success(api_client.attest_security_key(org["id"], key_id, SA))
    validate_success(api_client.assign_security_key(org["id"], key_id, acct, SA))
    validate_success(api_client.mark_distributed(org["id"], key_id, LOG))
    ceremony = validate_success(api_client.create_enrollment(acct, key_id, SA),
                                expected_status=201)
    validate_success(api_client.lock_identity_account(acct, SA))
    # fresh observation of the version after the lock
    activated = validate_success(api_client.activate_enrollment(
        acct, ceremony["id"], account_version(acct), SA))
    assert activated["status"] == "ACTIVE"
    account = validate_success(api_client.get_identity_account(acct, SA))
    assert account["status"] == "ENROLLED"
