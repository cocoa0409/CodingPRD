"""The makeup-credit bank: grant/apply conservation across periods, the
balance-sufficiency gate, the temporal-over-fiscal tier ordering, and
cross-variant structural validation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_makeup_ledger_invariant,
    assert_settlement,
    create_settlement_payload,
    list_settlements,
    run_final_settlement,
    setup_standard_onsite_scenario,
    validate_error,
    validate_success,
)


def test_makeup_credit_bank_conservation(api):
    """PRD section 3.8: "The balance consulted when applying credit in step 11
    is deliberately the pre-grant balance: a period's own shortfall grant can
    never pay its own bill. And across the contract's life, the sum of all
    grants on `FINAL` statements always equals the sum of all applications plus
    the contract's current bank balance — nothing is created in the bank and
    nothing is lost."
    PRD section 3.8: "For a `FINAL` only, the contract's
    `makeup_credit_balance_cents` becomes the pre-grant balance plus the grant
    minus the application, and the contract's `version` increments by 1."

    Design: Difficulty/compensating_invariant/makeup_credit_bank_conservation
    """
    bundle = setup_standard_onsite_scenario()
    contract = bundle["contract"]
    granting = run_final_settlement(contract["id"], "2027-12", 1500000, 0.10)
    assert_settlement(granting)
    assert granting["makeup_credit_granted_cents"] == 3600000
    assert granting["makeup_credit_applied_cents"] == 0

    drawing = run_final_settlement(
        contract["id"], "2028-01", 2100000, 0.10, apply_makeup_cents=1000000
    )
    assert_settlement(drawing)
    assert drawing["makeup_credit_granted_cents"] == 0
    assert drawing["makeup_credit_applied_cents"] == 1000000
    assert drawing["total_due_cents"] == 25732640, (
        "subtotal 26732640 minus the 1000000 application"
    )

    contract_after = validate_success(api_client.get_contract(
        contract["id"], TEST_USERS["billing_specialist_headers"]
    ))
    assert contract_after["makeup_credit_balance_cents"] == 2600000
    assert_makeup_ledger_invariant(
        [granting["makeup_credit_granted_cents"],
         drawing["makeup_credit_granted_cents"]],
        [granting["makeup_credit_applied_cents"],
         drawing["makeup_credit_applied_cents"]],
        contract_after["makeup_credit_balance_cents"],
    )


def test_settlement_temporal_beats_fiscal(api):
    """PRD section 2.8: "Every request is checked against a fixed sequence of
    priority tiers, and a failure at an earlier tier masks every later check:"
    PRD section 2.8: "6. Business temporal rules: window durations, turnaround
    overlap, blackout conflicts, turnaround due-ness, telemetry ordering, and
    settlement period-in-term."
    PRD section 2.8: "8. Fiscal gates: credit watch and makeup-credit
    sufficiency."
    PRD section 3.8: "by supplying a `period_month` as a `YYYY-MM` string that
    must fall within the contract's term, from its start month through its end
    month inclusive (`ERR_PERIOD_OUT_OF_TERM` otherwise)"

    Design: Difficulty/priority_pair_validation_conflict/settlement_temporal_beats_fiscal
    """
    bundle = setup_standard_onsite_scenario()
    contract = bundle["contract"]
    run_final_settlement(contract["id"], "2027-12", 1500000, 0.10)

    response = api_client.create_settlement(
        contract["id"],
        create_settlement_payload(
            period_month="2040-01", variant="FINAL", metered_volume_nm3=1000000,
            power_index_actual=0.10, apply_makeup_cents=9999999,
        ),
        TEST_USERS["billing_specialist_headers"],
    )
    error_data = validate_error(response, ApiErrorId.ERR_PERIOD_OUT_OF_TERM)
    assert error_data["error_id"] != "ERR_MAKEUP_CREDIT_EXCEEDED", (
        "the temporal gate (tier 6) must mask the fiscal gate (tier 8) even "
        "though apply 9999999 exceeds the 3600000 balance"
    )
    contract_after = validate_success(api_client.get_contract(
        contract["id"], TEST_USERS["billing_specialist_headers"]
    ))
    assert contract_after["makeup_credit_balance_cents"] == 3600000


def test_makeup_apply_above_balance_rejected(api):
    """PRD section 3.8: "`makeup_credit_applied_cents` for a `FINAL` is the
    smallest of `apply_makeup_cents` (treated as 0 when omitted), the bank
    balance before this period's grant, and the subtotal. Requesting an
    application larger than that minimum is rejected with
    `ERR_MAKEUP_CREDIT_EXCEEDED` rather than silently clamped."

    Design: Corner/validations/makeup_apply_above_balance_rejected
    """
    bundle = setup_standard_onsite_scenario(with_plant=False)
    contract = bundle["contract"]
    response = api_client.create_settlement(
        contract["id"],
        create_settlement_payload(
            period_month="2027-12", variant="FINAL", metered_volume_nm3=2100000,
            power_index_actual=0.10, apply_makeup_cents=1,
        ),
        TEST_USERS["billing_specialist_headers"],
    )
    validate_error(response, ApiErrorId.ERR_MAKEUP_CREDIT_EXCEEDED)
    contract_after = validate_success(api_client.get_contract(
        contract["id"], TEST_USERS["billing_specialist_headers"]
    ))
    assert contract_after["makeup_credit_balance_cents"] == 0


def test_provisional_with_metered_fields_rejected(api):
    """PRD section 3.8: "Cross-variant input is forbidden: metered volume or a
    power index on a provisional, projected volume on a final, or
    `apply_makeup_cents` on a provisional are all rejected with
    `ERR_VALIDATION`, as is a missing required field — and per §2.8 these
    structural checks run at the lowest tier, behind the contract-state,
    period, duplicate, and makeup gates."

    Design: Corner/calculations/provisional_with_metered_fields_rejected
    """
    bundle = setup_standard_onsite_scenario(with_plant=False)
    contract = bundle["contract"]
    response = api_client.create_settlement(
        contract["id"],
        {
            "period_month": "2027-12",
            "variant": "PROVISIONAL",
            "metered_volume_nm3": 1500000,
            "power_index_actual": 0.10,
        },
        TEST_USERS["billing_specialist_headers"],
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION)
    statements = list_settlements(contract["id"])
    assert statements == [], "nothing may be persisted for a rejected statement"
