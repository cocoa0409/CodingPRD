"""Corner: cross-cutting complexity layers — OCC freshness, fee variant
convergence, express feature flag, active_token_count reconciliation,
transit allowlist gating."""
from test_helpers import (
    ADMIN,
    OPERATOR,
    ApiErrorId,
    authorize,
    create_transit_allowlist_payload,
    create_transit_operator_payload,
    get_success_data,
    make_cardholder_headers,
    provision_second_token,
    setup_provisioned_token,
    validate_error,
    validate_success,
)


def test_occ_fresh_version_succeeds_after_stale_rejection(api):
    """PRD section 2.4: "version, an integer that starts at its initial value
    on creation and increments by one on every mutation of that row" and
    section 3.5: "A successful set bumps the device's version by one." A
    default-card retry with the pre-set version fails 412 while the fresh
    version succeeds.

    Design: Corner/cross-cutting complexity layers/occ_fresh_version_succeeds_after_stale_rejection
    """
    ns = setup_provisioned_token(api)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    d, t = ns["device"]["id"], ns["token"]["id"]
    dev = get_success_data(api.get_device(d))
    v0 = dev["version"]
    dev = get_success_data(api.set_default_card(
        d, {"token_id": t, "expected_device_version": v0}, ch))
    v1 = dev["version"]
    assert v1 == v0 + 1
    resp = api.set_default_card(
        d, {"token_id": t, "expected_device_version": v0}, ch)
    validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT)
    dev = get_success_data(api.set_default_card(
        d, {"token_id": t, "expected_device_version": v1}, ch))
    assert dev["version"] == v1 + 1


def test_fee_variants_converge_when_no_pending_authorizations(api):
    """PRD section 3.6: "The two variants must therefore diverge whenever at
    least one PENDING authorization exists for the issuer, and agree when none
    does." With only an APPROVED authorization of 20000 at 150 bps (fee 300),
    projected_fee_cents and approved_fee_cents agree at 300.

    Design: Corner/cross-cutting complexity layers/dual_variant_fee_switch_reconciles_on_pending_resolution
    """
    ns = setup_provisioned_token(api, card_product="CREDIT")
    from test_helpers import approved_authorization
    approved_authorization(api, ns["token"], amount_cents=20000, cryptogram="cgm-v1")
    proj = get_success_data(api.get_fee_projection(ns["issuer"]["id"], OPERATOR))
    assert proj["approved_fee_cents"] == 300
    assert proj["projected_fee_cents"] == 300


def test_express_feature_flag_gates_express_authorization(api):
    """PRD section 3.6: "Express eligibility (16) requires the whole chain —
    token express_transit_enabled, account card_product TRANSIT, agreement
    express_transit_supported, and an ACTIVE transit operator whose
    express_cap_cents is at least the requested amount — else
    ERR_EXPRESS_TRANSIT_NOT_SUPPORTED."

    Design: Corner/cross-cutting complexity layers/express_feature_flag_gates_express_authorization
    """
    ns = setup_provisioned_token(api, express_token=True)
    token_no = provision_second_token(api, ns)  # express flag not set
    operator = get_success_data(api.create_transit_operator(
        create_transit_operator_payload(), ADMIN))
    resp = authorize(api, ns["token"], amount_cents=250, cryptogram="cgm-t1",
                     merchant_id="BART", merchant_category="TRANSIT",
                     express_mode=True, transit_operator_id=operator["id"])
    auth = validate_success(resp, expected_status=201)
    assert auth["status"] == "APPROVED"
    resp = authorize(api, token_no, amount_cents=250, cryptogram="cgm-t2",
                     merchant_id="BART", merchant_category="TRANSIT",
                     express_mode=True, transit_operator_id=operator["id"])
    validate_error(resp, ApiErrorId.ERR_EXPRESS_TRANSIT_NOT_SUPPORTED)


def test_active_token_count_reconciles_across_provision_and_deactivate(api):
    """PRD section 3.2: the device tracks "an active_token_count of tokens
    currently ACTIVE on it (starting at 0)" and section 3.5: on deactivation
    "the device's active_token_count is recomputed". Two tokens then two
    deactivations step the count 2 -> 1 -> 0.

    Design: Corner/cross-cutting complexity layers/active_token_count_reconciles_across_provision_and_deactivate
    """
    ns = setup_provisioned_token(api)
    token2 = provision_second_token(api, ns, pan_last4="6666", idem_key="prov-d")
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    d = ns["device"]["id"]
    assert get_success_data(api.get_device(d))["active_token_count"] == 2
    get_success_data(api.deactivate_token(d, token2["id"], ch))
    assert get_success_data(api.get_device(d))["active_token_count"] == 1
    get_success_data(api.deactivate_token(d, ns["token"]["id"], ch))
    assert get_success_data(api.get_device(d))["active_token_count"] == 0


def test_transit_allowlist_blocks_unlisted_card_but_admits_after_enrollment(api):
    """PRD section 3.6: "when the operator's allowlist_active flag is set, the
    funding account must appear on that operator's allowlist in ACTIVE
    standing, else ERR_TRANSIT_NOT_ALLOWED" and section 3.8: "IssuerOperator
    and PlatformAdmin add accounts to an operator's allowlist by creating
    TransitAllowlist rows".

    Design: Corner/cross-cutting complexity layers/transit_allowlist_blocks_unlisted_card_but_admits_after_enrollment
    """
    ns = setup_provisioned_token(api, express_token=True)
    operator = get_success_data(api.create_transit_operator(
        create_transit_operator_payload(operator_code="MTA", name="Metro",
                                        flat_fare_cents=300,
                                        express_cap_cents=1000,
                                        allowlist_active=True), ADMIN))
    resp = authorize(api, ns["token"], amount_cents=300, cryptogram="cgm-a1",
                     merchant_id="MTA", merchant_category="TRANSIT",
                     express_mode=True, transit_operator_id=operator["id"])
    validate_error(resp, ApiErrorId.ERR_TRANSIT_NOT_ALLOWED)
    get_success_data(api.add_transit_allowlist(
        create_transit_allowlist_payload(operator["id"], ns["account"]["id"]),
        OPERATOR))
    resp = authorize(api, ns["token"], amount_cents=300, cryptogram="cgm-a2",
                     merchant_id="MTA", merchant_category="TRANSIT",
                     express_mode=True, transit_operator_id=operator["id"])
    auth = validate_success(resp, expected_status=201)
    assert auth["status"] == "APPROVED"
