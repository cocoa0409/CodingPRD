"""Attestation: supply-chain gates, firmware approval, auto-quarantine."""
from test_helpers import (
    LOG,
    PROC,
    SA,
    ApiErrorId,
    api_client,
    create_approved_order,
    create_model,
    create_org,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_high_assurance_ship_requires_supply_chain_cert():
    """PRD §3.5: "For a `HIGH_ASSURANCE` organization the request must carry
    `supply_chain_cert_id`; shipping without one is rejected with
    `ERR_PHISHABLE_PATH_FORBIDDEN`."

    Design: Corner/errors/high_assurance_attestation_requires_supply_chain_cert
    """
    org = create_org(legal_name="HA2 Org", assurance_tier="HIGH_ASSURANCE",
                     approved_firmware_versions=["5.4.3"])
    m = create_model(model_code="M-HA", unit_price_cents=100)
    po1 = create_approved_order(org["id"], [{"model_code": m["model_code"], "quantity": 1}])
    po2 = create_approved_order(org["id"], [{"model_code": m["model_code"], "quantity": 1}])
    resp = api_client.ship_purchase_order(org["id"], po1["id"], LOG)
    validate_error(resp, ApiErrorId.ERR_PHISHABLE_PATH_FORBIDDEN)
    shipped = validate_success(api_client.ship_purchase_order(
        org["id"], po2["id"], LOG, supply_chain_cert_id="SCC-2026-001"))
    assert shipped["status"] == "IN_TRANSIT"
    assert shipped["supply_chain_cert_id"] == "SCC-2026-001"


def test_high_assurance_attest_requires_order_supply_chain_cert():
    """PRD §3.6: "for a `HIGH_ASSURANCE` organization the key's order must
    carry a `supply_chain_cert_id` — attesting without one is
    `ERR_PHISHABLE_PATH_FORBIDDEN`".

    Design: Corner/errors/high_assurance_attestation_requires_supply_chain_cert
    """
    org = create_org(assurance_tier="HIGH_ASSURANCE",
                     approved_firmware_versions=["5.4.3"])
    m = create_model(model_code="M-HA2", unit_price_cents=100)
    po = create_approved_order(org["id"], [{"model_code": m["model_code"], "quantity": 1}])
    # PRD §3.6: keys are pre-registered against an APPROVED order.
    keys = validate_success(api_client.preregister_keys(
        org["id"], po["id"],
        {"keys": [{"serial_number": "HA-1", "firmware_version": "5.4.3"}]}, LOG,
    ), expected_status=201)
    # ship WITH cert so the order moves; then release path checks cert presence.
    get_success_data(api_client.ship_purchase_order(
        org["id"], po["id"], LOG, supply_chain_cert_id="SCC-OK"))
    get_success_data(api_client.receive_purchase_order(org["id"], po["id"], LOG))
    # with cert on the order and approved firmware, attestation succeeds
    attested = validate_success(
        api_client.attest_security_key(org["id"], keys[0]["id"], SA))
    assert attested["attestation_status"] == "VERIFIED"


def test_attestation_failure_auto_quarantines_high_assurance_order():
    """PRD §3.6: "When the firmware gate fails, the attestation still succeeds
    as a recorded act but the outcome is `FAILED`; if the organization is
    `HIGH_ASSURANCE` and the key's order is `RECEIVED`, the order is
    immediately quarantined with the full receipt-to-quarantine cascade of
    §3.5."

    Design: Corner/errors/attestation_failure_auto_quarantines_high_assurance_order
    """
    org2 = create_org(legal_name="QA Org", assurance_tier="HIGH_ASSURANCE",
                      approved_firmware_versions=["5.4.3"])
    m2 = create_model(model_code="M-QA2", unit_price_cents=100)
    po = create_approved_order(org2["id"], [{"model_code": m2["model_code"], "quantity": 2}])
    # PRD §3.6: keys are pre-registered against an APPROVED order.
    keys2 = validate_success(api_client.preregister_keys(
        org2["id"], po["id"],
        {"keys": [{"serial_number": "QA-11", "firmware_version": "5.4.3"},
                  {"serial_number": "QA-12", "firmware_version": "9.9.9"}]},
        LOG,
    ), expected_status=201)
    get_success_data(api_client.ship_purchase_order(
        org2["id"], po["id"], LOG, supply_chain_cert_id="SCC-OK"))
    get_success_data(api_client.receive_purchase_order(org2["id"], po["id"], LOG))
    bad_key = keys2[1]
    result = validate_success(api_client.attest_security_key(org2["id"], bad_key["id"], SA))
    assert result["attestation_status"] == "FAILED"
    pos, _ = validate_paginated(api_client.list_purchase_orders(org2["id"], SA))
    assert pos[0]["status"] == "QUARANTINED"
    all_keys, _ = validate_paginated(api_client.list_security_keys(
        org2["id"], SA, params={"purchase_order_id": po["id"]}))
    assert all(k["hardware_status"] == "REVOKED" for k in all_keys)


def test_high_assurance_empty_approved_list_fails_every_attestation():
    """PRD §3.1: "A `HIGH_ASSURANCE` organization with an empty approved list
    fails every attestation it attempts — the empty list means "nothing
    approved yet"."

    Design: Corner/errors/attestation_failure_auto_quarantines_high_assurance_order
    """
    org = create_org(assurance_tier="HIGH_ASSURANCE")
    assert org["approved_firmware_versions"] == []
    m = create_model(model_code="M-QA3", unit_price_cents=100)
    po = create_approved_order(org["id"], [{"model_code": m["model_code"], "quantity": 1}])
    # PRD §3.6: keys are pre-registered against an APPROVED order.
    keys = validate_success(api_client.preregister_keys(
        org["id"], po["id"],
        {"keys": [{"serial_number": "QA-21", "firmware_version": "5.4.3"}]}, LOG,
    ), expected_status=201)
    get_success_data(api_client.ship_purchase_order(
        org["id"], po["id"], LOG, supply_chain_cert_id="SCC-OK"))
    get_success_data(api_client.receive_purchase_order(org["id"], po["id"], LOG))
    result = validate_success(api_client.attest_security_key(org["id"], keys[0]["id"], SA))
    assert result["attestation_status"] == "FAILED"
    pos, _ = validate_paginated(api_client.list_purchase_orders(org["id"], SA))
    assert pos[0]["status"] == "QUARANTINED"


def test_ship_in_wrong_state_and_missing_cert_state_wins():
    """PRD §2.5: "After existence, state checks fire: if the target resource is
    not in a state from which the requested transition exists, the request is
    rejected with `ERR_INVALID_STATE`."
    PRD §2.5: "Then optimistic-concurrency checks: a stale
    `expected_identity_account_version` or `expected_purchase_order_version`
    yields `ERR_STALE_VERSION`. Business-safety policy checks come next —
    phishing-resistance and high-assurance violations surface as
    `ERR_PHISHABLE_PATH_FORBIDDEN`, and segregation-of-duties violations as
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/ship_in_wrong_state_and_missing_cert_state_wins
    """
    org = create_org(legal_name="HA Org", assurance_tier="HIGH_ASSURANCE",
                     authentication_policy="PHISHING_RESISTANT")
    m = create_model(model_code="M-J", unit_price_cents=150)
    po = validate_success(api_client.create_purchase_order(
        org["id"],
        {"lines": [{"model_code": m["model_code"], "quantity": 1}],
         "shipping_location": "HQ"},
        PROC,
    ), expected_status=201)
    # PENDING_APPROVAL + missing cert: the state failure must surface
    resp = api_client.ship_purchase_order(org["id"], po["id"], LOG)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_ship_pending_order_standard_org_also_state_error():
    """PRD §3.5: "Once approved, physical movement is a `LogisticsCoordinator`
    workflow. Shipping an `APPROVED` order moves it to `IN_TRANSIT`."

    Design: Difficulty/priority_pair_validation_conflict/ship_in_wrong_state_and_missing_cert_state_wins
    """
    org = create_org()
    m = create_model(model_code="M-J2", unit_price_cents=150)
    po = create_approved_order(org["id"], [{"model_code": m["model_code"], "quantity": 1}])
    # ship once (valid), then ship again from IN_TRANSIT: no such transition
    get_success_data(api_client.ship_purchase_order(org["id"], po["id"], LOG))
    resp = api_client.ship_purchase_order(org["id"], po["id"], LOG)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
