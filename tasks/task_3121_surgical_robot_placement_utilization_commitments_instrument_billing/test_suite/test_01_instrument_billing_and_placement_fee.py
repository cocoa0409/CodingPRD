"""Instrument billing: the quote recorded at booking versus the bill settled at completion,
and the placement-fee list/net divergence between submit and activation."""

from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    setup_agreement,
    setup_commissioned_system,
    validate_success,
)


def test_purchase_case_quotes_the_attempted_load_then_settles_on_the_clamped_load(api):
    """PRD §3.4: "At booking the figure reported is a quote computed from the attempted
    load, before clamping, and it exists so the hospital's scheduling paperwork can be
    produced; a case whose attempted load of 3 is clamped to 1 therefore quotes 375000
    cents while its eventual bill settles at 125000."
    PRD §3.4: "the load actually authorized is the smaller of the attempted load and the
    accessory set's remaining lives at booking, and it is stored as `approved_instrument_load`."

    Design: Difficulty/dual_variant_calc/instrument_billing_quote_vs_settle_on_same_case
    """
    ctx = setup_commissioned_system(
        config_overrides={"max_instrument_lives": 1,
                          "base_placement_fee_cents": 4800000,
                          "model_code": "DA_V1",
                          "integration_tier": 1})
    assert ctx.system["instrument_lives_remaining"] == 1

    booking = validate_success(api_client.create_procedure_case(
        ctx.system["id"],
        {"training_record_id": ctx.surgeon["id"], "procedure_family": "UROLOGY",
         "case_started_at": "2026-09-10T08:00:00Z", "duration_minutes": 120,
         "instrument_load": 3, "is_emergency": False},
        ctx.account_headers), 201)

    assert booking["instrument_billing_cents"] == 375000, (
        "the quote prices the attempted load of 3 at 125000 per whole load"
    )
    assert booking["approved_instrument_load"] == 1, (
        "the load is clamped to the accessory set's single remaining life"
    )
    assert get_success_data(
        api_client.get_robot_system(ctx.system["id"], ctx.account_headers))["instrument_lives_remaining"] == 0


def test_completing_the_case_recomputes_the_bill_from_the_approved_load(api):
    """PRD §3.4: "At completion the figure is recomputed from the approved, clamped load
    actually consumed, and the case is billable only because it is now `COMPLETED`."

    Design: Difficulty/dual_variant_calc/instrument_billing_quote_vs_settle_on_same_case
    """
    ctx = setup_commissioned_system(
        config_overrides={"max_instrument_lives": 1,
                          "base_placement_fee_cents": 4800000,
                          "model_code": "DA_V1",
                          "integration_tier": 1})
    booking = get_success_data(api_client.create_procedure_case(
        ctx.system["id"],
        {"training_record_id": ctx.surgeon["id"], "procedure_family": "UROLOGY",
         "case_started_at": "2026-09-10T08:00:00Z", "duration_minutes": 120,
         "instrument_load": 3, "is_emergency": False},
        ctx.account_headers), 201)
    assert booking["instrument_billing_cents"] == 375000

    settled = validate_success(api_client.mark_case_completed(
        booking["id"], {"expected_case_version": booking["version"]},
        ctx.account_headers), 200)

    assert settled["case_status"] == "COMPLETED"
    assert settled["instrument_billing_cents"] == 125000, (
        "the settle variant bills the lives-clamped load of 1, not the quoted load of 3"
    )


def test_submitted_purchase_agreement_is_written_at_the_full_list_fee(api):
    """PRD §3.1.2: "At submit the ladder is read while the submitting account is still
    `CONTRACTED`, so the account does not yet count toward its own `idn_scale` — a
    single-site IDN is placed at a volume discount rate of exactly 0.00 and the number
    written to `placement_fee_cents` is the full gross fee that contracts and purchase
    orders are cut against."

    Design: Difficulty/dual_variant_calc/placement_fee_list_at_submit_vs_net_at_activation
    """
    # gross = 6000000 + ceil(0/2)*150000 + 2*250000 = 6500000; idn_scale 0 -> rate 0.00
    ctx = setup_agreement(
        config_overrides={"model_code": "DA_V2", "base_placement_fee_cents": 6000000,
                          "integration_tier": 2, "max_instrument_lives": 12,
                          "requires_dark_fiber": True,
                          "requires_dedicated_power_circuit": True},
        agreement_overrides={"arrangement_type": "PURCHASE",
                             "base_monthly_fee_cents": 250000,
                             "minimum_procedures_per_cycle": 0,
                             "interval_months": 1,
                             "placement_fee_cents": 7000000},
        accepted=False)

    agreement = ctx.agreement
    assert agreement["agreement_status"] == "PENDING_ACCEPTANCE"
    assert agreement["placement_fee_cents"] == 6500000, (
        "the list fee carries the full gross fee at volume discount rate 0.00"
    )


def test_accepted_agreement_invoices_the_write_down_net_fee(api):
    """PRD §3.1.2: "At activation the ladder is re-evaluated, and the account has by then
    become `ACTIVE`, so it now counts 1 toward `idn_scale`, the rate moves to 0.02, and the
    same agreement re-prices strictly lower. That lower figure is what is actually invoiced,
    and it is stored separately as `net_placement_fee_cents`."

    Design: Difficulty/dual_variant_calc/placement_fee_list_at_submit_vs_net_at_activation
    """
    ctx = setup_agreement(
        config_overrides={"model_code": "DA_V2", "base_placement_fee_cents": 6000000,
                          "integration_tier": 2, "max_instrument_lives": 12,
                          "requires_dark_fiber": True,
                          "requires_dedicated_power_circuit": True},
        agreement_overrides={"arrangement_type": "PURCHASE",
                             "base_monthly_fee_cents": 250000,
                             "minimum_procedures_per_cycle": 0,
                             "interval_months": 1,
                             "placement_fee_cents": 7000000},
        accepted=False)
    list_fee = ctx.agreement["placement_fee_cents"]
    assert list_fee == 6500000

    accepted = validate_success(api_client.accept_agreement(
        ctx.agreement["id"],
        {"expected_agreement_version": ctx.agreement["version"],
         "expected_hospital_account_version": ctx.account["version"]},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)

    assert accepted["agreement_status"] == "ACTIVE"
    assert accepted["net_placement_fee_cents"] == 6370000, (
        "gross 6500000 less the 2 percent the now-ACTIVE account earns"
    )
    assert accepted["net_placement_fee_cents"] < list_fee, (
        "the invoiced fee is strictly below the list fee for the identical agreement"
    )
    account = get_success_data(
        api_client.get_account(ctx.account["id"], ctx.account_headers))
    assert account["account_status"] == "ACTIVE"
    assert account["account_posture"] == "ACTIVE"