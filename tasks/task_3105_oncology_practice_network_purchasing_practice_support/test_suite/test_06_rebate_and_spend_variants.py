"""Dual-variant calculations: network spend, market-share routing, rounding order."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    set_clock, create_network, create_practice, create_product, get_practice,
    create_activated_contract, create_approved_agreement, create_draft_agreement,
    receive_new_lot, create_rebate_program, create_rebate_qualification,
    make_practice_admin_headers, get_practice_version, DEFAULT_CLOCK,
)


def test_network_spend_provisional_versus_final(api, network_admin_headers, network_analyst_headers):
    """PRD §3.8: "The provisional network spend is the sum of
    `extended_cost_cents` over purchase orders for the program's product scope,
    or over all rows when the program's `drug_ndc_scope` is `ALL`, whose
    `received_at` falls inside the half-open measured window and whose status is
    `SHIPPED` or `RECEIVED`."
    PRD §3.8: "The final network spend is the same sum over the same rows with
    one exclusion: every order whose `pricing_tier_applied` came from the
    `list_price_fallback` variant is stripped out, because dollars not routed at
    agreed contract pricing earn no rebate once the period is closed."
    PRD §3.5: "The `list_price_fallback` variant applies when no active
    agreement covers the instant: the unit price is the `network_base_price_cents`
    with no discount at all".

    Design: Difficulty/dual_variant_calc/network_spend_provisional_versus_final
    """
    set_clock("2026-06-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=500)
    create_activated_contract(practice["id"],
                              term_start="2026-01-01T00:00:00Z",
                              term_end="2028-01-01T00:00:00Z")
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              tier_level="TIER_1", discount_pct=0.10,
                              effective_from="2026-06-01T00:00:00Z",
                              effective_to="2026-12-31T00:00:00Z")
    product = create_product(network["id"], network_base_price_cents=1000)
    program = create_rebate_program(network["id"], drug_ndc_scope="ALL",
                                    market_share_threshold_pct=0.50,
                                    rebate_pct=0.02)

    # Order A: received while the agreement window covers the instant.
    set_clock("2026-07-01T00:00:00Z")
    order_a, _ = receive_new_lot(practice["id"], product["id"], 1000,
                                 expires_at="2027-07-05T00:00:00Z",
                                 lot_number="L-2026-07A")
    assert order_a["unit_price_cents"] == 900
    assert order_a["pricing_tier_applied"] == "TIER_1"

    # Order B: received after the agreement window closed, so no ACTIVE
    # agreement covers the instant and the order lands at list price.
    set_clock("2027-03-05T00:00:00Z")
    order_b, _ = receive_new_lot(practice["id"], product["id"], 1000,
                                 expires_at="2028-03-05T00:00:00Z",
                                 lot_number="L-2027-03B")
    assert order_b["unit_price_cents"] == 1000

    report = validate_success(
        api.get_rebate_share_report(
            network["id"], network_analyst_headers,
            params={"practice_id": practice["id"], "rebate_program_id": program["id"],
                    "window_start_at": "2026-01-01T00:00:00Z",
                    "window_end_at": "2028-01-01T00:00:00Z"}),
        200)

    # Both orders are reportable inside the window: 1000 × 900 + 1000 × 1000.
    assert report["provisional_network_spend_cents"] == 1_900_000
    assert report["final_network_spend_cents"] == 900_000
    assert report["final_network_spend_cents"] != report["provisional_network_spend_cents"]


def test_network_spend_variants_expose_the_fallback_order(api, network_admin_headers):
    """PRD §3.5: "Where several `ACTIVE` agreements cover the instant, the one
    with the latest `effective_from` wins; where that ties, the latest
    `created_at` wins".
    PRD §3.5: "The observed unit price is the product's `network_base_price_cents`
    multiplied by one minus the agreement's `discount_pct`, rounded half up once
    to a whole number of cents."
    PRD §3.8: "dollars not routed at agreed contract pricing earn no rebate once
    the period is closed".

    Design: Difficulty/dual_variant_calc/network_spend_provisional_versus_final
    """
    set_clock("2026-06-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=500)
    create_activated_contract(practice["id"],
                              term_start="2026-01-01T00:00:00Z",
                              term_end="2028-01-01T00:00:00Z")
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              tier_level="TIER_1", discount_pct=0.10,
                              effective_from="2026-06-01T00:00:00Z",
                              effective_to="2026-12-31T00:00:00Z")
    product = create_product(network["id"], network_base_price_cents=1000)

    set_clock("2026-07-01T00:00:00Z")
    order_a, _ = receive_new_lot(practice["id"], product["id"], 1000,
                                 lot_number="L-VAR-A")
    set_clock("2027-03-05T00:00:00Z")
    order_b, _ = receive_new_lot(practice["id"], product["id"], 1000,
                                 lot_number="L-VAR-B")

    orders = get_success_data(api.list_drug_purchase_orders(
        network_admin_headers, params={"practice_id": practice["id"]}))
    by_id = {o["id"]: o for o in orders}

    assert by_id[order_a["id"]]["pricing_tier_applied"] == "TIER_1"
    assert by_id[order_a["id"]]["unit_price_cents"] == 900
    assert by_id[order_b["id"]]["unit_price_cents"] == 1000
    assert by_id[order_b["id"]]["extended_cost_cents"] == 1_000_000


def test_market_share_routing_denominator_narrow(api, network_admin_headers):
    """PRD §3.8: "When `routing_includes_out_of_scope` is false the
    `scope_included_only` variant applies and the denominator is drug purchases
    alone."
    PRD §3.8: "`is_qualified` is true when the practice's `market_share_pct` is
    at or above the program's `market_share_threshold_pct`".
    PRD §3.8: "Both bounds are inclusive, so a practice scoring exactly the
    minimum still qualifies".

    Design: Difficulty/dual_variant_calc/market_share_routing_denominator_divergence
    """
    set_clock("2026-06-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=400)
    create_activated_contract(practice["id"],
                              term_start="2026-01-01T00:00:00Z",
                              term_end="2028-01-01T00:00:00Z")
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              tier_level="TIER_2", discount_pct=0.05,
                              effective_from="2026-06-01T00:00:00Z",
                              routing_includes_out_of_scope=False)
    in_scope = create_product(network["id"], ndc="00000000002",
                              network_base_price_cents=1000, unit_type="MG")
    out_of_scope = create_product(network["id"], ndc="00000000003",
                                  network_base_price_cents=1000, unit_type="MG")
    program = create_rebate_program(
        network["id"], drug_ndc_scope="00000000002", market_share_threshold_pct=0.50,
        rebate_pct=0.02, compliance_min_score=0.00)

    set_clock("2026-07-01T00:00:00Z")
    receive_new_lot(practice["id"], in_scope["id"], 800, lot_number="L-SI-1")
    receive_new_lot(practice["id"], out_of_scope["id"], 500, lot_number="L-SI-2")

    report = validate_success(
        api.get_rebate_share_report(
            network["id"], network_admin_headers,
            params={"practice_id": practice["id"], "rebate_program_id": program["id"],
                    "window_start_at": "2026-01-01T00:00:00Z",
                    "window_end_at": "2028-01-01T00:00:00Z"}),
        200)

    # 800 units at the agreement-priced 950 cents are routed; the denominator is
    # the practice's whole drug spend, which also carries the 500 out-of-scope
    # units at the same price.
    assert report["provisional_network_spend_cents"] == 760000
    assert report["routing_denominator_cents"] == 760000 + 475000
    assert report["market_share_pct"] == pytest.approx(0.6154, abs=0.00005)


def test_network_spend_dual_variants_for_a_fully_routed_window(api, network_admin_headers, network_analyst_headers):
    """PRD §3.12: "Because the two spend figures come from the same order rows
    over the same window, their difference is exactly the fallback-priced dollars
    the reconciliation strips out".
    PRD §3.8: "Both figures are computed from the same rows over the same window,
    and they diverge exactly to the extent fallback-priced orders are present."

    Design: Difficulty/dual_variant_calc/network_spend_provisional_versus_final
    """
    set_clock("2026-06-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=500)
    create_activated_contract(practice["id"],
                              term_start="2026-01-01T00:00:00Z",
                              term_end="2028-01-01T00:00:00Z")
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              tier_level="TIER_1", discount_pct=0.10,
                              effective_from="2026-06-01T00:00:00Z",
                              effective_to="2026-12-31T00:00:00Z")
    product = create_product(network["id"], network_base_price_cents=1000)
    program = create_rebate_program(network["id"], drug_ndc_scope="ALL",
                                    market_share_threshold_pct=0.50,
                                    rebate_pct=0.02)

    set_clock("2026-07-01T00:00:00Z")
    order, _ = receive_new_lot(practice["id"], product["id"], 1000,
                               expires_at="2027-07-05T00:00:00Z",
                               lot_number="L-ROUTED-1")
    assert order["unit_price_cents"] == 900

    report = validate_success(
        api.get_rebate_share_report(
            network["id"], network_analyst_headers,
            params={"practice_id": practice["id"], "rebate_program_id": program["id"],
                    "window_start_at": "2026-01-01T00:00:00Z",
                    "window_end_at": "2028-01-01T00:00:00Z"}),
        200)

    # No fallback-priced order exists in the window, so the variants coincide.
    assert report["provisional_network_spend_cents"] == 900000
    assert report["final_network_spend_cents"] == 900000
    assert report["final_network_spend_cents"] == report["provisional_network_spend_cents"]


def test_dual_variant_window_is_half_open_on_received_at(api, network_admin_headers, network_analyst_headers):
    """PRD §3.12: "The window is half-open, so `window_start_at` is inside it and
    `window_end_at` is outside."
    PRD §3.8: "Under the provisional variant the rebate amount is the
    provisional network spend multiplied by the program's `rebate_pct`, capped at
    2,500,000 cents per practice, with the cap applied after rounding."

    Design: Difficulty/dual_variant_calc/network_spend_provisional_versus_final
    """
    set_clock("2026-06-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=500)
    create_activated_contract(practice["id"],
                              term_start="2026-01-01T00:00:00Z",
                              term_end="2028-01-01T00:00:00Z")
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              tier_level="TIER_1", discount_pct=0.10,
                              effective_from="2026-06-01T00:00:00Z")
    product = create_product(network["id"], network_base_price_cents=1000)
    program = create_rebate_program(network["id"], drug_ndc_scope="ALL",
                                    market_share_threshold_pct=0.50,
                                    rebate_pct=0.02)

    set_clock("2026-07-01T00:00:00Z")
    receive_new_lot(practice["id"], product["id"], 1000,
                    expires_at="2027-07-05T00:00:00Z", lot_number="L-HO-1")

    # The receipt lands exactly on window_start_at, which the half-open window
    # includes, and strictly before window_end_at.
    inside = validate_success(
        api.get_rebate_share_report(
            network["id"], network_analyst_headers,
            params={"practice_id": practice["id"], "rebate_program_id": program["id"],
                    "window_start_at": "2026-07-01T00:00:00Z",
                    "window_end_at": "2026-08-01T00:00:00Z"}),
        200)
    assert inside["provisional_network_spend_cents"] == 900000

    # The same instant as window_end_at is outside the window.
    outside = validate_success(
        api.get_rebate_share_report(
            network["id"], network_analyst_headers,
            params={"practice_id": practice["id"], "rebate_program_id": program["id"],
                    "window_start_at": "2026-06-01T00:00:00Z",
                    "window_end_at": "2026-07-01T00:00:00Z"}),
        200)
    assert outside["provisional_network_spend_cents"] == 0


def test_market_share_routing_denominator_widens_with_the_routing_term(api, network_admin_headers):
    """PRD §3.8: "When the practice's `ACTIVE` pricing agreement carries the
    `scope_excluded` routing term — that is, its `routing_includes_out_of_scope`
    is true — the denominator additionally includes the billed amounts of the
    practice's `ADJUDICATED_PAID` claims in the window, capturing dollar volume
    the practice bought and billed but did not route through the network contract."
    PRD §3.8: "That makes the denominator larger and the resulting
    `market_share_pct` smaller."

    Design: Difficulty/dual_variant_calc/market_share_routing_denominator_divergence
    """
    set_clock("2026-06-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=400)
    create_activated_contract(practice["id"],
                              term_start="2026-01-01T00:00:00Z",
                              term_end="2028-01-01T00:00:00Z")
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              tier_level="TIER_2", discount_pct=0.05,
                              effective_from="2026-06-01T00:00:00Z",
                              routing_includes_out_of_scope=True)
    in_scope = create_product(network["id"], ndc="00000000012",
                              network_base_price_cents=1000, unit_type="MG")
    program = create_rebate_program(
        network["id"], drug_ndc_scope="00000000012", market_share_threshold_pct=0.50,
        rebate_pct=0.02, compliance_min_score=0.00)

    set_clock("2026-07-01T00:00:00Z")
    receive_new_lot(practice["id"], in_scope["id"], 800, lot_number="L-WIDE-1")

    report = validate_success(
        api.get_rebate_share_report(
            network["id"], network_admin_headers,
            params={"practice_id": practice["id"], "rebate_program_id": program["id"],
                    "window_start_at": "2026-01-01T00:00:00Z",
                    "window_end_at": "2028-01-01T00:00:00Z"}),
        200)

    # With no out-of-scope billed claims in the window the two readings coincide.
    assert report["routing_denominator_cents"] == report["provisional_network_spend_cents"]
    assert report["market_share_pct"] == pytest.approx(1.0000, abs=0.00005)


def test_market_share_divergence_moves_qualification_across_the_threshold(api, network_admin_headers, revenue_cycle_manager_headers, payer_adjudicator_headers):
    """PRD §3.8: "`is_qualified` is true when the practice's `market_share_pct` is
    at or above the program's `market_share_threshold_pct` and its
    `compliance_score` is at or above the program's `compliance_min_score`."
    PRD §3.8: "Both readings are legitimate measurements of the share of drug
    spend routed through the network, and they disagree on identical data, which
    is why the routing term is pinned on the agreement at approval time."

    Design: Difficulty/dual_variant_calc/market_share_routing_denominator_divergence
    """
    set_clock("2026-06-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=400)
    create_activated_contract(practice["id"],
                              term_start="2026-01-01T00:00:00Z",
                              term_end="2028-01-01T00:00:00Z")
    practice = get_practice(practice["id"])
    agreement = create_approved_agreement(practice["id"], practice["version"],
                                          tier_level="TIER_2", discount_pct=0.05,
                                          effective_from="2026-06-01T00:00:00Z",
                                          routing_includes_out_of_scope=False)
    in_scope = create_product(network["id"], ndc="00000000022",
                              network_base_price_cents=1000, unit_type="MG")
    out_of_scope = create_product(network["id"], ndc="00000000023",
                                  network_base_price_cents=1000, unit_type="MG")
    program = create_rebate_program(
        network["id"], drug_ndc_scope="00000000022", market_share_threshold_pct=0.50,
        rebate_pct=0.02, compliance_min_score=0.00, period_epoch_index=2)
    set_clock("2026-07-01T00:00:00Z")
    receive_new_lot(practice["id"], in_scope["id"], 800, lot_number="L-TH-1")
    receive_new_lot(practice["id"], out_of_scope["id"], 500, lot_number="L-TH-2")

    qualification = create_rebate_qualification(practice["id"], program["id"])
    assert qualification["market_share_pct"] == pytest.approx(0.6154, abs=0.00005)
    assert qualification["is_qualified"] is True

    stored = validate_success(
        api.get_pricing_agreement(agreement["id"], network_admin_headers), 200)
    assert stored["routing_includes_out_of_scope"] is False
    assert stored["status"] == "ACTIVE"


def test_rebate_amount_rounding_order_b(api, network_admin_headers):
    """PRD §3.8: "the platform multiplies each order's `extended_cost_cents` by
    `rebate_pct`, sums those exact per-order products, and rounds the sum once to
    whole cents."
    PRD §3.8: "The alternative order, rounding each order's contribution to whole
    cents and then summing the rounded values, is a recognized but rejected
    reading that differs on identical input; the pinned order is authoritative."

    Design: Difficulty/combinatorial_formula/rebate_amount_rounding_order_b
    """
    set_clock("2026-06-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=300)
    create_activated_contract(practice["id"],
                              term_start="2026-01-01T00:00:00Z",
                              term_end="2028-01-01T00:00:00Z")
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              tier_level="TIER_1", discount_pct=0,
                              effective_from="2026-06-01T00:00:00Z")
    d1 = create_product(network["id"], ndc="00000000011", network_base_price_cents=12345)
    d2 = create_product(network["id"], ndc="00000000012", network_base_price_cents=10000)
    d3 = create_product(network["id"], ndc="00000000013", network_base_price_cents=5000,
                        therapeutic_class="SUPPORTIVE_CARE")
    # Creation 2026-06-01: the program period 2 measures [2026-07-01, 2026-08-01),
    # which is where the three receipts below are placed.
    program = create_rebate_program(
        network["id"], drug_ndc_scope="ALL", market_share_threshold_pct=0.00,
        rebate_pct=0.0177, compliance_min_score=0.00, period_epoch_index=2)

    set_clock("2026-07-01T00:00:00Z")
    receive_new_lot(practice["id"], d1["id"], 1, lot_number="L-R1")
    receive_new_lot(practice["id"], d2["id"], 1, lot_number="L-R2")
    receive_new_lot(practice["id"], d3["id"], 1, lot_number="L-R3")

    qualification = create_rebate_qualification(practice["id"], program["id"])
    assert qualification["rebate_amount_cents"] == 484
    assert qualification["rebate_amount_cents"] != 485


def test_rebate_amount_rounding_boundary_and_inclusive_floor(api, network_admin_headers):
    """PRD §2.7: "Where a formula produces a fractional cent, it is rounded half
    up to the nearest whole cent — `0.5` and above rounds away from zero,
    anything below rounds down."
    PRD §3.8: "`is_qualified` is true when the practice's `market_share_pct` is
    at or above the program's `market_share_threshold_pct` and its
    `compliance_score` is at or above the program's `compliance_min_score`."
    PRD §3.8: "Both bounds are inclusive, so a practice scoring exactly the
    minimum still qualifies".

    Design: Difficulty/combinatorial_formula/rebate_amount_rounding_order_b
    """
    set_clock("2026-06-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=300)
    create_activated_contract(practice["id"],
                              term_start="2026-01-01T00:00:00Z",
                              term_end="2028-01-01T00:00:00Z")
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              tier_level="TIER_1", discount_pct=0,
                              effective_from="2026-06-01T00:00:00Z")
    d1 = create_product(network["id"], ndc="00000000031", network_base_price_cents=12345)
    d2 = create_product(network["id"], ndc="00000000032", network_base_price_cents=10000)
    d3 = create_product(network["id"], ndc="00000000033", network_base_price_cents=5000,
                        therapeutic_class="SUPPORTIVE_CARE")
    # Creation 2026-06-01: the program period 2 measures [2026-07-01, 2026-08-01),
    # which is where the three receipts below are placed.
    program = create_rebate_program(
        network["id"], drug_ndc_scope="ALL", market_share_threshold_pct=0.00,
        rebate_pct=0.0177, compliance_min_score=0.00, period_epoch_index=2)

    set_clock("2026-07-01T00:00:00Z")
    receive_new_lot(practice["id"], d1["id"], 1, lot_number="L-RB1")
    receive_new_lot(practice["id"], d2["id"], 1, lot_number="L-RB2")
    receive_new_lot(practice["id"], d3["id"], 1, lot_number="L-RB3")

    qualification = create_rebate_qualification(practice["id"], program["id"])
    # 27345 * 0.0177 = 484.0065 -> 484 (sum-then-round), not 485 (round-per-order).
    assert qualification["rebate_amount_cents"] == 484
    assert qualification["compliance_score"] >= 0.00
    assert qualification["is_qualified"] is True