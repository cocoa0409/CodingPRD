"""Reachability of the declare-to-endpoint errors and conditional actions."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId, set_clock, create_network, create_practice,
    create_activated_contract, create_approved_agreement, get_practice,
    get_practice_version, make_practice_admin_headers, setup_operational_practice,
    create_rebate_program, receive_new_lot, DEFAULT_CLOCK,
    create_treatment_payload, create_administer_payload,
)

def test_insufficient_stock_error_is_reachable_from_the_administer_endpoint(api, network_admin_headers):
    """PRD §3.7: "The sum of `quantity_remaining` across the practice's lots for
    this product that are `AVAILABLE` and whose `expires_at` is strictly later
    than `administered_at` must be at least the dose requirement that
    `administered_units` implies once `vial_yield_units` is accounted for; a
    shortfall is refused with `ERR_INSUFFICIENT_STOCK`."

    Design: Corner/errors/insufficient_stock_error_is_reachable_from_the_administer_endpoint
    """
    ctx = setup_operational_practice(
        stock_units=100,
        product_overrides={"unit_type": "VIAL", "network_base_price_cents": 1000})
    practice_id = ctx["practice"]["id"]
    practice_headers = make_practice_admin_headers(practice_id)

    set_clock("2026-09-02T00:00:00Z")
    treatment = validate_success(
        api.create_treatment(
            create_treatment_payload(practice_id, ctx["provider"]["id"],
                                     ctx["product"]["id"], ctx["protocol"]["id"],
                                     patient_reference="PT-SHORT-1",
                                     administered_units=150, dose_count=1,
                                     vial_yield_units=100,
                                     administered_at="2026-09-02T00:00:00Z"),
            practice_headers),
        201)

    res = api.administer_treatment(
        treatment["id"],
        create_administer_payload(get_practice_version(practice_id)),
        practice_headers)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_STOCK, expected_status=409)

    lot = validate_success(
        api.get_inventory_lot(ctx["lot"]["id"], network_admin_headers), 200)
    assert lot["quantity_remaining"] == 100
    assert lot["status"] == "AVAILABLE"

    current = validate_success(
        api.get_patient_treatment(treatment["id"], network_admin_headers), 200)
    assert current["status"] == "SCHEDULED"
    consumptions = get_success_data(
        api.list_treatment_consumptions(treatment["id"], network_admin_headers))
    assert consumptions == []


def test_rebate_share_read_returns_both_variants_and_routing_denominator(api, network_admin_headers, network_analyst_headers):
    """PRD §3.12: "It reports the practice's provisional network spend and final
    network spend over the measured window as `provisional_network_spend_cents`
    and `final_network_spend_cents`, the denominator used for the share as
    `routing_denominator_cents`, the resulting `market_share_pct`, and the
    practice's current `denial_ratio`."
    PRD §3.8: "The base denominator is the practice's total drug spend in the
    window on the same basis, deliberately including orders for products outside
    the rebate program's NDC scope."
    PRD §3.8: "When `routing_includes_out_of_scope` is false the
    `scope_included_only` variant applies and the denominator is drug purchases
    alone."

    Design: Corner/endpoints/rebate_share_read_returns_both_variants_and_routing_denominator
    """
    ctx = setup_operational_practice(
        agreement_overrides={"discount_pct": 0.0},
        product_overrides={"unit_type": "VIAL", "network_base_price_cents": 1000})
    program = create_rebate_program(
        ctx["network"]["id"], drug_ndc_scope="ALL", market_share_threshold_pct=0.50,
        period_epoch_index=0)

    receive_new_lot(ctx["practice"]["id"], ctx["product"]["id"], 500,
                    expires_at="2027-09-15T00:00:00Z")

    res = api.get_rebate_share_report(
        ctx["network"]["id"], network_analyst_headers,
        params={"practice_id": ctx["practice"]["id"], "rebate_program_id": program["id"],
                "window_start_at": "2026-09-01T00:00:00Z",
                "window_end_at": "2027-09-01T00:00:00Z"})
    data = validate_success(res, 200)

    assert data["provisional_network_spend_cents"] == 500000
    assert data["final_network_spend_cents"] == 500000
    assert data["routing_denominator_cents"] == 500000
    assert data["market_share_pct"] == pytest.approx(1.0000, abs=0.00005)


def test_void_endpoint_is_gated_to_draft_or_unappealed_denied_claims(api, network_admin_headers):
    """PRD §3.9: "A `NetworkAdmin` may void a `DENIED` claim that has not been
    appealed — that is, one with `appeal_round` still zero — and any other status
    fails with `ERR_CLAIM_NOT_VOIDABLE`".
    PRD §3.9: "A `RevenueCycleManager` may void a claim that is still `DRAFT`".

    Design: Corner/endpoints/void_endpoint_is_gated_to_draft_or_unappealed_denied_claims
    """
    from test_helpers import find_draft_claim

    ctx = setup_operational_practice(
        stock_units=400,
        product_overrides={"unit_type": "VIAL", "network_base_price_cents": 1000})

    set_clock("2026-09-02T00:00:00Z")
    treatment = validate_success(
        api.create_treatment(
            create_treatment_payload(ctx["practice"]["id"], ctx["provider"]["id"],
                                     ctx["product"]["id"], ctx["protocol"]["id"],
                                     patient_reference="PT-VG-1",
                                     administered_units=100, dose_count=1,
                                     vial_yield_units=100, admin_fee_cents=3000,
                                     administered_at="2026-09-02T00:00:00Z"),
            make_practice_admin_headers(ctx["practice"]["id"])),
        201)
    validate_success(
        api.administer_treatment(
            treatment["id"],
            create_administer_payload(get_practice_version(ctx["practice"]["id"])),
            make_practice_admin_headers(ctx["practice"]["id"])),
        200)

    claim = find_draft_claim(treatment["id"])

    voided = validate_success(api.void_claim(claim["id"], network_admin_headers), 200)
    assert voided["status"] == "VOIDED"

    current = validate_success(api.get_payer_claim(claim["id"], network_admin_headers), 200)
    assert current["status"] == "VOIDED"

    # A second void names a status that is neither DRAFT nor an un-appealed
    # DENIED, so the NetworkAdmin path refuses it with ERR_CLAIM_NOT_VOIDABLE.
    res = api.void_claim(claim["id"], network_admin_headers)
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_VOIDABLE, expected_status=409)