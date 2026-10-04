"""Service contracts: cryopreservation viability forking and retry loop,
custom-generation strain minting, and the conditional IP-terms validation.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    VIABILITY_FLOOR_PCT,
    api_client,
    assert_contract,
    assert_strain,
    create_active_customer,
    create_catalog_strain,
    create_contract_payload,
    create_draft_contract,
    create_new_strain_spec,
    execute_contract,
    read_strain,
    transition_contract,
    validate_error,
)

_ADMIN = TEST_USERS["admin_headers"]


def test_contract_cryo_viability_failure_retry_loop():
    """PRD Section 3.10: "the outcome hinges on the viability floor of 70: a
    `viability_pct` of at least 70 completes the contract and stores the
    figure, while a value below 70 routes the contract to `VALIDATION_FAILED`
    instead, still storing the figure. A failed validation is not the end:
    the contract may be moved from `VALIDATION_FAILED` back to `IN_PROGRESS`
    to retry."

    Design: Corner/state_machines/contract_cryo_viability_failure_retry_loop
    """
    customer = create_active_customer()
    strain = create_catalog_strain()
    contract = create_draft_contract(
        customer, strain["id"],
        contract_type="CRYOPRESERVATION",
        ip_ownership="VENDOR_RETAINED",
        royalty_rate_pct=10,
        straw_count=100,
    )
    execute_contract(contract["id"], customer["id"])
    transition_contract(contract["id"], "IN_PROGRESS", _ADMIN)
    transition_contract(contract["id"], "VALIDATION", _ADMIN)

    # 65 < VIABILITY_FLOOR_PCT: routed to VALIDATION_FAILED, figure stored.
    failed = transition_contract(contract["id"], "COMPLETED", _ADMIN, viability_pct=65)
    assert failed["milestone_status"] == "VALIDATION_FAILED"
    assert failed["viability_pct"] == 65

    # The retry loop closes with a passing viability.
    transition_contract(contract["id"], "IN_PROGRESS", _ADMIN)
    transition_contract(contract["id"], "VALIDATION", _ADMIN)
    completed = transition_contract(contract["id"], "COMPLETED", _ADMIN, viability_pct=85)
    assert completed["milestone_status"] == "COMPLETED"
    assert completed["viability_pct"] == 85
    assert 85 >= VIABILITY_FLOOR_PCT
    assert_contract(completed)


def test_contract_custom_generation_mints_strain():
    """PRD Section 3.10: "For `CUSTOM_GENERATION`, completion requires the
    contract's `new_strain_spec` to be present; completing mints a new
    `ModelStrain` from that spec — whose `strain_code` must not collide with
    any existing strain, else `ERR_DUPLICATE_KEY` (HTTP 409) — and stores the
    new strain's identifier in `generated_strain_id`, which had been null
    until then."

    Design: Corner/state_machines/contract_custom_generation_mints_strain
    """
    customer = create_active_customer(is_commercial=True)
    strain = create_catalog_strain()
    spec = create_new_strain_spec(immune_class="IMMUNOCOMPROMISED")
    contract = create_draft_contract(
        customer, strain["id"],
        contract_type="CUSTOM_GENERATION",
        new_strain_spec=spec,
        ip_ownership="CUSTOMER_EXCLUSIVE",
        exclusivity_fee_cents=500000,
        royalty_rate_pct=0,
    )
    assert contract["generated_strain_id"] is None

    execute_contract(contract["id"], customer["id"])
    transition_contract(contract["id"], "IN_PROGRESS", _ADMIN)
    transition_contract(contract["id"], "VALIDATION", _ADMIN)
    completed = transition_contract(contract["id"], "COMPLETED", _ADMIN)

    assert completed["milestone_status"] == "COMPLETED"
    assert completed["generated_strain_id"] is not None

    minted = read_strain(completed["generated_strain_id"])
    assert minted["strain_code"] == spec["strain_code"]
    assert minted["immune_class"] == "IMMUNOCOMPROMISED"
    assert_strain(minted)


def test_contract_ip_terms_conditional_validation():
    """PRD Section 3.10: "`CUSTOMER_EXCLUSIVE` terms are reserved for
    commercial accounts — the customer's `is_commercial` flag must be true —
    and require a one-time `exclusivity_fee_cents` of at least 1, while
    `royalty_rate_pct` must be absent or 0, since exclusivity replaces
    royalties. `SHARED` or `VENDOR_RETAINED` terms instead require a
    `royalty_rate_pct` strictly greater than 0 and at most 100 — the
    downstream-sales royalty percentage. Any combination that breaks these
    rules — exclusive terms without a commercial customer or without the fee,
    a royalty attached to exclusive terms, or a missing or out-of-range
    royalty on shared or vendor-retained terms — is `ERR_IP_TERMS_INVALID`
    (HTTP 422)."

    Design: Corner/validations/contract_ip_terms_conditional_validation
    """
    customer = create_active_customer()  # non-commercial by default
    strain = create_catalog_strain()

    # Exclusive terms with neither a commercial customer nor the fee.
    payload1 = create_contract_payload(
        customer["id"], strain["id"],
        contract_type="CUSTOM_GENERATION",
        new_strain_spec=create_new_strain_spec(),
        ip_ownership="CUSTOMER_EXCLUSIVE",
    )
    payload1.pop("royalty_rate_pct", None)
    resp = api_client.create_contract(payload1, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_IP_TERMS_INVALID)

    # SHARED terms with no royalty_rate_pct.
    payload2 = create_contract_payload(
        customer["id"], strain["id"],
        contract_type="CRYOPRESERVATION",
        ip_ownership="SHARED",
        straw_count=50,
    )
    payload2.pop("royalty_rate_pct", None)
    resp = api_client.create_contract(payload2, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_IP_TERMS_INVALID)
