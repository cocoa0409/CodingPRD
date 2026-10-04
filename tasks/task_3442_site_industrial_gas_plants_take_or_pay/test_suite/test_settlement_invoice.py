"""Monthly settlement invoice: the PROVISIONAL/FINAL dual variants, the
combinatorial formula with conditional capital recovery, per-year escalation
rounding, and the makeup-credit cap clip."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_settlement,
    create_accepted_evaluation,
    create_contract,
    activate_contract,
    list_settlements,
    run_final_settlement,
    run_settlement,
    set_logical_clock,
    setup_standard_onsite_scenario,
    validate_success,
)


def test_settlement_provisional_final_divergence(api):
    """PRD section 3.8: "`power_passthrough_cents` for a `FINAL` is the
    effective volume times `power_kwh_per_nm3` times the difference between
    `power_index_actual` and `base_power_index`, rounded half up to integer
    cents — negative when power came in below the contracted base. For a
    `PROVISIONAL` it is 0."
    PRD section 3.8: "A `FINAL` records the grant into the ledger; a
    `PROVISIONAL` reports the same figure as an estimate and mutates nothing."
    PRD section 3.8: "Creating a `FINAL` fails with `ERR_DUPLICATE_SETTLEMENT`
    only when a `FINAL` already exists for the period; otherwise the new
    `FINAL` supersedes the period's provisional, moving it from `PROVISIONAL`
    to `SUPERSEDED`."

    Design: Difficulty/dual_variant_calc/settlement_provisional_final_divergence
    """
    bundle = setup_standard_onsite_scenario()
    contract = bundle["contract"]
    provisional = run_settlement(
        contract["id"], period_month="2027-12", variant="PROVISIONAL",
        projected_volume_nm3=1800000,
    )
    assert_settlement(provisional)
    assert provisional["total_due_cents"] == 25515000
    assert provisional["power_passthrough_cents"] == 0
    assert provisional["makeup_credit_granted_cents"] == 1440000, (
        "the provisional reports the grant as an estimate"
    )

    final = run_final_settlement(contract["id"], "2027-12", 1500000, 0.10)
    assert_settlement(final)
    assert final["total_due_cents"] == 25527600
    assert final["power_passthrough_cents"] == 12600
    assert final["makeup_credit_granted_cents"] == 3600000
    assert final["total_due_cents"] - provisional["total_due_cents"] == 12600, (
        "the variant divergence on identical contract terms is the passthrough"
    )

    contract_after = validate_success(api_client.get_contract(
        contract["id"], TEST_USERS["billing_specialist_headers"]
    ))
    assert contract_after["makeup_credit_balance_cents"] == 3600000, (
        "only the FINAL moves the bank; the PROVISIONAL left it at 0"
    )
    statements = list_settlements(contract["id"])
    by_variant = {s["id"]: s for s in statements}
    assert by_variant[provisional["id"]]["status"] == "SUPERSEDED"
    assert by_variant[final["id"]]["status"] == "FINAL"


def test_settlement_invoice_max_and_conditional_capital(api):
    """PRD section 3.8: "`billable_volume_nm3` is the larger of the effective
    volume and `min_monthly_volume_nm3` — the take-or-pay floor bills even when
    offtake falls short."
    PRD section 3.8: "`capital_recovery_cents` applies only when the contract's
    mode is `ONSITE_PLANT` and a non-`DECOMMISSIONED` plant exists for it: the
    plant's `capital_cost_cents` divided by `term_months`, rounded down.
    Otherwise it is 0."
    PRD section 3.8: "`facility_fee_cents` is `monthly_facility_fee_cents`
    times the escalation multiplier, rounded half up to integer cents."

    Design: Difficulty/combinatorial_formula/settlement_invoice_max_and_conditional_capital
    """
    bundle = setup_standard_onsite_scenario()
    contract = bundle["contract"]
    statement = run_final_settlement(contract["id"], "2028-11", 2000000, 0.09)
    assert_settlement(statement)
    assert statement["billable_volume_nm3"] == 2000000, (
        "max branch at exact equality metered == min"
    )
    assert statement["volume_charge_cents"] == 24000000
    assert statement["power_passthrough_cents"] == 8400, (
        "round_half_up(2000000 * 0.42 * (0.09 - 0.08))"
    )
    assert statement["facility_fee_cents"] == 530450, (
        "per-year multiplier 1.0609 at 25 months elapsed"
    )
    assert statement["capital_recovery_cents"] == 1000000, (
        "an OPERATING plant takes the capital-recovery branch"
    )
    assert statement["total_due_cents"] == 25538850


def test_facility_fee_per_year_rounding(api):
    """PRD section 3.8: "`escalation_multiplier` compounds the annual
    facility-fee escalation: take the whole elapsed years (the floor of
    `months_elapsed` divided by 12), start the multiplier at 1.0000, and for
    each elapsed year multiply it by one plus
    `facility_fee_escalation_pct_annual`, rounding the multiplier half up to
    four decimal places after every annual multiplication. Rounding once at the
    end instead of once per year yields a different fee and is non-conformant."

    Design: Difficulty/combinatorial_formula/facility_fee_per_year_rounding
    """
    set_logical_clock()
    customer, evaluation = create_accepted_evaluation(
        {"name": "Cryo Med", "segment": "MEDICAL"},
        {
            "site_label": "MED-1", "demand_avg_nm3h": 50, "demand_peak_nm3h": 90,
            "required_purity_percent": 99.999, "required_product": "O2",
            "pipeline_available": False,
        },
    )
    contract = create_contract(
        customer["id"], evaluation["id"],
        min_monthly_volume_nm3=10000, unit_price_cents_per_nm3=20,
        monthly_facility_fee_cents=375000,
        facility_fee_escalation_pct_annual=0.025, base_power_index=0.08,
        power_kwh_per_nm3=0.10,
    )
    assert contract["mode"] == "CYLINDER"
    activate_contract(contract["id"])

    statement = run_final_settlement(contract["id"], "2028-11", 12000, 0.09)
    assert_settlement(statement)
    assert statement["escalation_multiplier"] == 1.0506, (
        f"per-year rounding pins 1.0506 (not the single-shot 1.050625), "
        f"got {statement['escalation_multiplier']}"
    )
    assert statement["facility_fee_cents"] == 393975, (
        "375000 * 1.0506 — the single-shot 393984 is non-conformant"
    )
    assert statement["capital_recovery_cents"] == 0, (
        "no plant exists for a CYLINDER-mode contract"
    )
    assert statement["power_passthrough_cents"] == 12, (
        "round_half_up(12000 * 0.10 * (0.09 - 0.08))"
    )
    assert statement["total_due_cents"] == 633987


def test_capital_recovery_zero_without_plant(api):
    """PRD section 3.8: "`capital_recovery_cents` applies only when the
    contract's mode is `ONSITE_PLANT` and a non-`DECOMMISSIONED` plant exists
    for it: the plant's `capital_cost_cents` divided by `term_months`, rounded
    down. Otherwise it is 0."

    Design: Corner/calculations/capital_recovery_zero_without_plant
    """
    bundle = setup_standard_onsite_scenario(with_plant=False)
    statement = run_final_settlement(
        bundle["contract"]["id"], "2027-12", 1500000, 0.10
    )
    assert_settlement(statement)
    assert statement["capital_recovery_cents"] == 0, (
        "with no plant created, the conditional branch is not taken"
    )
    assert statement["total_due_cents"] == 24527600, (
        "24000000 volume + 12600 passthrough + 515000 fee + 0 capital"
    )


def test_makeup_grant_clipped_by_cap(api):
    """PRD section 3.8: "`makeup_credit_granted_cents` is the shortfall volume
    times the unit price times sixty percent, rounded half up, then capped at
    the remaining grant room. The credit cap is `makeup_credit_cap_pct` times
    twelve times `min_monthly_volume_nm3` times `unit_price_cents_per_nm3`,
    rounded half up to integer cents; grant room is the cap minus the
    pre-grant balance, floored at zero; and any overflow above the cap is
    discarded, never banked."

    Design: Corner/calculations/makeup_grant_clipped_by_cap
    """
    bundle = setup_standard_onsite_scenario(
        with_plant=False, contract_overrides={"makeup_credit_cap_pct": 0.01}
    )
    contract = bundle["contract"]
    statement = run_final_settlement(contract["id"], "2027-12", 1500000, 0.10)
    assert_settlement(statement)
    assert statement["makeup_credit_granted_cents"] == 2880000, (
        "raw grant 3600000 clipped by cap 0.01 * 12 * 2000000 * 12 = 2880000"
    )
    contract_after = validate_success(api_client.get_contract(
        contract["id"], TEST_USERS["billing_specialist_headers"]
    ))
    assert contract_after["makeup_credit_balance_cents"] == 2880000, (
        "the overflow above the cap is discarded, never banked"
    )
