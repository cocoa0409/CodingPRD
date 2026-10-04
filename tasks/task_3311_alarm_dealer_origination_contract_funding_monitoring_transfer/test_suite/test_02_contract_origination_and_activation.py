"""Contract origination, activation gates and the optimistic-concurrency guard."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    get_success_data,
    set_logical_clock,
    setup_funded_direct_contract,
    setup_package_with_contract,
    submit_and_approve_package,
    find_monitoring_account,
    provision_monitoring_account,
    complete_contract_installation,
    project_version,
    package_version,
    register_customer,
    originate_direct_contract,
    create_contract_payload,
    create_customer_payload,
    create_dealer_payload,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
)

_CHANNEL = TEST_USERS["channel_manager_headers"]
_ANALYST = TEST_USERS["funding_analyst_headers"]
_MONITORING = TEST_USERS["monitoring_operator_headers"]
_SERVICE = TEST_USERS["service_coordinator_headers"]


# ─── Corner: entities / contract_get_round_trips_stored_origination_fields ───

def test_direct_contract_round_trips_origination_fields_and_null_linkage(api, channel_manager_headers):
    """PRD §3.4: "The contract is created in `PENDING_VALIDATION` with `source_channel` set to `DIRECT`, a null `dealer_id` and a null `dealer_package_id` because neither is supplied on the direct route"
    PRD §3.4: "the `customer_id`, `equipment_config_code`, `credit_score`, `contract_term_months`, `monthly_monitoring_cents` and optional `financed_charge_at_apr_cents`"

    Design: Corner/entities/contract_get_round_trips_stored_origination_fields
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    customer = register_customer(full_name="Fay Roundtrip",
                                 email="fay.roundtrip@example.com")
    contract = originate_direct_contract(
        customer["id"],
        equipment_config_code="ELITE",
        credit_score=688,
        contract_term_months=48,
        monthly_monitoring_cents=5999,
        financed_charge_at_apr_cents=19900,
    )

    fetched = validate_success(
        api_client.get_contract(contract["id"], channel_manager_headers), 200)

    assert fetched["source_channel"] == "DIRECT"
    assert fetched["dealer_id"] is None
    assert fetched["dealer_package_id"] is None
    assert fetched["equipment_config_code"] == "ELITE"
    assert fetched["credit_score"] == 688
    assert fetched["contract_term_months"] == 48
    assert fetched["monthly_monitoring_cents"] == 5999
    assert fetched["financed_charge_at_apr_cents"] == 19900
    assert fetched["contract_status"] == "PENDING_VALIDATION"


# ─── Corner: entities / contracts_list_paginates_with_total_count_and_has_more ───

def test_contract_list_paginates_with_total_count_and_has_more(api, channel_manager_headers):
    """PRD §2.3: "`limit` sets the maximum number of rows returned and defaults to 10, with a minimum of 1 and a maximum of 100; `offset` sets the number of leading rows skipped and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the size of the full filtered collection and `has_more` indicates whether further rows remain beyond the returned page."

    Design: Corner/entities/contracts_list_paginates_with_total_count_and_has_more
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    customer = register_customer(full_name="Gale Pager", email="gale.pager@example.com")
    for cfg, term in (("BASE", 36), ("PREMIUM", 48), ("ELITE", 60)):
        originate_direct_contract(
            customer["id"], equipment_config_code=cfg,
            credit_score=700, contract_term_months=term,
            premises_address_line=f"31{len(cfg)} Juniper St",
        )

    page, meta = validate_paginated(api_client.list_contracts(
        channel_manager_headers, params={"limit": 2, "offset": 0}))
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    tail, meta_tail = validate_paginated(api_client.list_contracts(
        channel_manager_headers, params={"limit": 2, "offset": 2}))
    assert len(tail) == 1
    assert meta_tail["has_more"] is False


# ─── Corner: errors / create_contract_with_unknown_customer_returns_fk_error ───

def test_contract_create_with_unknown_customer_returns_fk_integrity_violation(api, channel_manager_headers):
    """PRD §2.5: "A body-supplied foreign key that does not resolve fails separately, reported as `ERR_FK_INTEGRITY_VIOLATION` with HTTP 400."

    Design: Corner/errors/create_contract_with_unknown_customer_returns_fk_error
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    res = api_client.create_contract(
        create_contract_payload(
            "11111111-2222-3333-4444-555555555555",
            equipment_config_code="BASE",
            credit_score=700,
            contract_term_months=36,
            monthly_monitoring_cents=3999,
            premises_address_line="1 Ghost St",
        ),
        channel_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_FK_INTEGRITY_VIOLATION, expected_status=400)


# ─── Corner: errors / create_customer_duplicate_email_returns_409 ───

def test_customer_create_duplicate_email_returns_natural_key_duplicate(api, channel_manager_headers):
    """PRD §3.4: "a new subscriber begins in the status `PENDING_ACTIVATION` — the value its `status` field takes — and its `email` must be unique across all customers, a clash being refused with `ERR_NATURAL_KEY_DUPLICATE`."

    Design: Corner/errors/create_customer_duplicate_email_returns_409
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    first = validate_success(api_client.create_customer(
        create_customer_payload(
            full_name="Hal First", email="dup@example.com", phone="+15550001032"),
        channel_manager_headers,
    ), 201)

    res = api_client.create_customer(
        create_customer_payload(
            full_name="Ivy Second", email="dup@example.com", phone="+15550001033"),
        channel_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_NATURAL_KEY_DUPLICATE, expected_status=409)

    unchanged = validate_success(
        api_client.get_customer(first["id"], channel_manager_headers), 200)
    assert unchanged["email"] == "dup@example.com"
    assert unchanged["full_name"] == "Hal First"


# ─── Corner: consistency_model / immediate_visibility_of_funding_side_effects ───

def test_direct_fund_response_already_reports_active_and_split_fields(api):
    """PRD §3.4: "runs the equipment-financing split against its frozen credit band, which fixes its `equipment_financed_cents` and `equipment_payment_cents` and sets `equipment_financing_disclosed` to false; runs the funding fee, which fixes its `capex_cents`, its `holdback_cents`, its `holdback_remaining_cents` at the same amount, and its `funding_amount_cents`; sets its `funding_points` from the dealer's `quality_tier`; moves its `contract_status` to `ACTIVE` and stamps `activated_at` from the logical clock"
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    Design: Corner/consistency_model/immediate_visibility_of_funding_side_effects
    """
    customer, contract = setup_funded_direct_contract(
        equipment_config_code="PREMIUM", contract_term_months=60,
        customer_email="nia.immediate@example.com", fund=False)

    res = api_client.fund_contract(
        contract["id"],
        {"expected_contract_version": project_version(contract["id"])},
        _ANALYST,
    )
    funded = validate_success(res, 200)

    # The funding call's own response already carries every computed side effect.
    assert funded["contract_status"] == "ACTIVE"
    assert funded["holdback_cents"] == 0          # DIRECT channel: no dealer holdback
    assert funded["equipment_financed_cents"] == 302
    assert funded["equipment_payment_cents"] == 5
    assert funded["equipment_financing_disclosed"] is False


# ─── Corner: validations / rescission_self_approval_returns_segregation_error ───

def test_rescission_approval_by_requesting_operator_returns_segregation_error(api):
    """PRD §2.1: "The operator that approves a rescission must differ from the operator recorded as the requestor; when the approving `X-User-ID` equals the request's `operator_id`, the approval is refused with `ERR_SEGREGATION_OF_DUTIES_REQUIRED` and HTTP 403."

    Design: Corner/validations/rescission_self_approval_returns_segregation_error
    """
    from test_helpers import (
        setup_rescission_ready, make_operator_headers,
    )
    customer, contract, request = setup_rescission_ready(
        equipment_config_code="PREMIUM", contract_term_months=60,
        operator_id="ops-same-1", customer_email="kip.sod@example.com")
    assert contract["contract_status"] == "ACTIVE"

    res = api_client.decide_rescission_request(
        request["id"], {"outcome": "APPROVED"},
        make_operator_headers("ops-same-1", "ComplianceOfficer"),
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_REQUIRED, expected_status=403)

    still_requested = validate_success(
        api_client.get_rescission_request(request["id"], _ANALYST), 200)
    assert still_requested["request_status"] == "REQUESTED"
    still_active = validate_success(api_client.get_contract(contract["id"], _ANALYST), 200)
    assert still_active["contract_status"] == "ACTIVE"


# ─── Difficulty: combinatorial_formula / equipment_financing_split_... ───

def test_equipment_split_financed_amount_is_two_percent_of_monitoring_share(api):
    """PRD §3.5: "The monitoring share of the contract is sixty percent of `capex_cents`, rounded half-up, plus a dealer onboarding fee of 149 cents. The financed equipment amount `equipment_financed_cents` is two percent of that monitoring share, rounded half-up."
    PRD §3.4: "The contract's capitalised equipment amount `capex_cents` is looked up from its `equipment_config_code`: the `BASE` configuration carries 14900 cents, `PREMIUM` carries 24900 cents and `ELITE` carries 34900 cents."

    Design: Difficulty/combinatorial_formula/equipment_financing_split_incremental_residual_reconciliation
    """
    customer, contract = setup_funded_direct_contract(
        equipment_config_code="BASE", credit_score=700, contract_term_months=36,
        monthly_monitoring_cents=3999, customer_email="kirby.base@example.com")

    fetched = validate_success(api_client.get_contract(contract["id"], _ANALYST), 200)
    assert fetched["capex_cents"] == 14900
    # monitoring_share = round(14900 * 0.60) + 149 = 9089; 2% of 9089 -> 182
    assert fetched["equipment_financed_cents"] == 182


def test_equipment_split_payment_is_per_installment_rounded(api):
    """PRD §2.7: "Where a formula states that rounding happens at a named intermediate step, that step's rounding is performed before the value feeds the next step; the equipment-financing split is the clearest case, because its per-installment amount is rounded to cents first and only then multiplied by the number of term months."
    PRD §3.5: "the monthly `equipment_payment_cents` is `equipment_financed_cents` divided by `contract_term_months`, rounded half-up to whole cents"

    Design: Difficulty/combinatorial_formula/equipment_financing_split_incremental_residual_reconciliation
    """
    customer, contract = setup_funded_direct_contract(
        equipment_config_code="BASE", credit_score=700, contract_term_months=36,
        monthly_monitoring_cents=3999, customer_email="kirby.base2@example.com")

    fetched = validate_success(api_client.get_contract(contract["id"], _ANALYST), 200)
    assert fetched["equipment_financed_cents"] == 182
    assert fetched["equipment_payment_cents"] == 5  # round_half_up(182 / 36)


# ─── Difficulty: cross_entity_state_dependency / contract_funding_requires_provisioned_monitoring_account ───

def test_direct_contract_fund_refused_while_monitoring_account_unprovisioned(api):
    """PRD §3.4: "Finally, a contract needs a monitoring account already in the `PROVISIONED` state, or an approved onsite-install waiver standing in for it; without either, the gate fails with `ERR_MONITORING_NOT_PROVISIONED`."

    Design: Difficulty/cross_entity_state_dependency/contract_funding_requires_provisioned_monitoring_account
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    customer = register_customer(full_name="Xio Unprovisioned",
                                 email="xio.unprovisioned@example.com")
    contract = originate_direct_contract(
        customer["id"], equipment_config_code="PREMIUM",
        credit_score=700, contract_term_months=60)

    res = api_client.fund_contract(
        contract["id"],
        {"expected_contract_version": project_version(contract["id"])},
        _ANALYST,
    )
    err = validate_error(res, ApiErrorId.ERR_MONITORING_NOT_PROVISIONED, expected_status=422)
    assert err["error_id"] == "ERR_MONITORING_NOT_PROVISIONED"


def test_direct_contract_never_reaches_active_while_unprovisioned(api):
    """PRD §3.4: "A contract that fails a gate instead moves to `CANCELLED`, with the failing gate's name frozen into its `validation_failure_code`, its `cancelled_from_status` recorded as `PENDING_VALIDATION`, and its `cancelled_at` stamped from the logical clock."

    Design: Difficulty/cross_entity_state_dependency/contract_funding_requires_provisioned_monitoring_account
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    customer = register_customer(full_name="Xio Unprovisioned Two",
                                 email="xio.unprovisioned2@example.com")
    contract = originate_direct_contract(
        customer["id"], equipment_config_code="PREMIUM",
        credit_score=700, contract_term_months=60)

    api_client.fund_contract(
        contract["id"],
        {"expected_contract_version": project_version(contract["id"])},
        _ANALYST,
    )
    fetched = validate_success(api_client.get_contract(contract["id"], _ANALYST), 200)

    assert fetched["contract_status"] == "CANCELLED"
    assert fetched["validation_failure_code"] == "ERR_MONITORING_NOT_PROVISIONED"
    assert fetched["cancelled_from_status"] == "PENDING_VALIDATION"
    assert fetched["contract_status"] != "ACTIVE"


# ─── Corner: cross_cutting / stale_package_version_on_second_approve_returns_412 ───

def test_package_approve_with_stale_version_returns_412(api):
    """PRD §2.8: "Approving a package requires an `expected_dealer_package_version` field carrying the client's last observed version of the target `DealerPackage`. When the package's `version` has advanced since the client read it, the approval is refused with `ERR_STALE_VERSION` and HTTP 412"
    PRD §3.2: "The declared contract is created in `PENDING_VALIDATION` on the DEALER channel, its monitoring account is created `UNPROVISIONED`, an installation is created `SCHEDULED` when a schedule instant was supplied, and the package's `submitted_contract_count` and `version` both advance."

    Design: Corner/cross_cutting/stale_package_version_on_second_approve_returns_412
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    dealer, package, contract = setup_package_with_contract(
        dealer_code="D11", legal_name="Echo Alarms", holdback_rate=0.10,
        quality_tier="TIER_1", package_reference="PKG-P37",
        equipment_config_code="PREMIUM", contract_term_months=60)
    from test_helpers import make_dealer_headers
    get_success_data(api_client.submit_package(
        package["id"], make_dealer_headers(dealer["id"])))

    stale_version = package_version(package["id"])

    # A second declaration advances the package version while leaving it UNDER_REVIEW,
    # so state is not the pre-empting check and the stale observation is what fails.
    second_customer = register_customer(full_name="Mira Occ",
                                        email="mira.occ@example.com")
    from test_helpers import declare_package_contract
    declare_package_contract(
        package["id"], second_customer["id"], equipment_config_code="PREMIUM",
        credit_score=700, contract_term_months=60)
    assert package_version(package["id"]) > stale_version

    res = api_client.approve_package(
        package["id"], {"expected_dealer_package_version": stale_version}, _ANALYST)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    after = get_success_data(api_client.get_package(package["id"], _ANALYST))
    assert after["package_status"] == "UNDER_REVIEW"