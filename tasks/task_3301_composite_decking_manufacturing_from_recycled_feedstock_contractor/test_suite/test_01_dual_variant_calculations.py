"""Dual-variant calculations: dealer invoicing (provisional vs final) and
claim credit (prorated vs expired)."""
from test_helpers import (
    confirm_order,
    deliver_order,
    get_success_data,
    make_active_formulation,
    make_certified_contractor,
    make_completed_run,
    make_contractor_headers,
    make_dealer,
    make_installed_registration,
    make_order,
    make_plant,
    make_price_book,
    make_product_line,
    make_stocking_commitment,
    make_supplier,
    make_under_review_claim,
    set_clock,
    ship_order,
    stock_resin,
)
from test_helpers.test_users import TEST_USERS

DSR = TEST_USERS["dealer_sales_rep_headers"]
CA = TEST_USERS["claims_adjuster_headers"]
CM = TEST_USERS["channel_manager_headers"]


def _base_distribution_setup(api):
    """Plant + activated formulation + product line + price book + dealer +
    supplier + resin + one completed 2000-lf SELLABLE run (fg_store 2000).
    Clock ends at 2026-03-01. The price book is effective from 2025-01-01 so
    season-2025 fulfillment orders can also pin it."""
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(lines=2)
    form = make_active_formulation()
    line = make_product_line(form["id"])
    make_price_book(base_prices={line["id"]: 500}, effective_from="2025-01-01")
    dealer = make_dealer()
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=3000)
    make_completed_run(plant["id"], line["id"], 2000, "2026-03-01")
    return plant, line, dealer


def test_provisional_standard_vs_final_preferred_invoice(api):
    """PRD §3.6: "The projection uses the provisional invoicing variant: it is
    computed exactly like the final invoice described below but is never
    persisted, because the dealer's tier can change between confirmation and
    shipment."
    PRD §3.6: "The dealer's tier is `PREFERRED` when the dealer has at least
    one stocking commitment that closed `MET` with a `season_year` equal to
    the year of the ship date minus one, and `STANDARD` otherwise."

    Design: Difficulty/dual_variant_calc/dealer_invoicing_provisional_vs_final
    """
    plant, line, dealer = _base_distribution_setup(api)

    # Control order M: ships on 2026-03-02 while the dealer has no MET
    # commitment for season 2025 -> STANDARD tier, 200 * 500 = 100000.
    order_m = make_order(dealer["id"], line["id"], 200, "2026-03-02")
    confirm_order(order_m["id"])
    set_clock("2026-03-02T00:00:00Z")
    shipped_m = ship_order(order_m["id"])
    deliver_order(order_m["id"], dealer["id"])

    # Close a season-2025 commitment to MET so that later ships price at
    # PREFERRED (ship year 2026 -> season_year 2025 lookup). Delivery advances
    # the commitment whose season_year equals the ship date's year, so the
    # fulfilling order ships in 2025.
    set_clock("2025-12-15T00:00:00Z")
    sc25 = make_stocking_commitment(dealer["id"], "VA-N", line["id"], 1, 2025)
    order25 = make_order(dealer["id"], line["id"], 1, "2025-12-15")
    confirm_order(order25["id"])
    ship_order(order25["id"])
    deliver_order(order25["id"], dealer["id"])
    assert get_success_data(api.get_stocking_commitment(sc25["id"], CM))["status"] == "MET"

    # Order A: identical 200-lf order data, ships after the tier flip ->
    # final invoice at PREFERRED 1000 bp: floor(100000 * 0.9) = 90000.
    order_a = make_order(dealer["id"], line["id"], 200, "2026-04-06")
    confirm_order(order_a["id"])
    set_clock("2026-04-06T00:00:00Z")
    shipped_a = ship_order(order_a["id"])

    assert shipped_m["invoiced_cents"] == 100000, (
        f"expected STANDARD invoice 100000, got {shipped_m['invoiced_cents']}"
    )
    assert shipped_a["invoiced_cents"] == 90000, (
        f"expected PREFERRED invoice 90000, got {shipped_a['invoiced_cents']}"
    )
    assert shipped_m["invoiced_cents"] - shipped_a["invoiced_cents"] == 10000

    dealer_after = get_success_data(api.get_dealer(dealer["id"], CM))
    assert dealer_after["outstanding_cents"] == 100000 + 500 + 90000


def test_final_invoice_uses_ship_date_tier_not_confirm_tier(api):
    """PRD §3.6: "Because tier derives from prior-season performance, a
    commitment closing `MET` between confirmation and shipment legitimately
    makes the provisional and final figures disagree for identical order
    data."

    Design: Difficulty/dual_variant_calc/dealer_invoicing_provisional_vs_final
    """
    plant, line, dealer = _base_distribution_setup(api)
    # Order A confirmed while the dealer has NO MET 2025 commitment
    # (provisional evaluation at confirm would be STANDARD).
    order_a = make_order(dealer["id"], line["id"], 200, "2026-03-02")
    confirm_order(order_a["id"])
    # Close a season-2025 commitment to MET between confirm and ship.
    # Delivery advances the commitment whose season_year equals the ship
    # date's year, so the fulfilling order ships in 2025.
    sc25 = make_stocking_commitment(dealer["id"], "VA-N", line["id"], 1, 2025)
    order25 = make_order(dealer["id"], line["id"], 1, "2025-12-15")
    confirm_order(order25["id"])
    set_clock("2025-12-15T00:00:00Z")
    ship_order(order25["id"])
    deliver_order(order25["id"], dealer["id"])
    assert get_success_data(api.get_stocking_commitment(sc25["id"], CM))["status"] == "MET"
    # Ship order A: tier is evaluated at ship time -> PREFERRED.
    set_clock("2026-03-02T00:00:00Z")
    shipped_a = ship_order(order_a["id"])
    assert shipped_a["invoiced_cents"] == 90000, (
        f"final invoice must use ship-date tier PREFERRED: {shipped_a['invoiced_cents']}"
    )


def _claim_credit_setup(api):
    """Shared setup for the claim-credit dual-variant instance: one shipped
    400-lf order (200000 cents at STANDARD), one certified SILVER contractor,
    one board lot lineage."""
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(lines=2)
    form = make_active_formulation()
    line = make_product_line(form["id"], name="Enhance", color="Brown",
                             profile="SQUARE", emboss="SMOOTH", board_length_ft=12)
    make_price_book(base_prices={line["id"]: 500})
    dealer = make_dealer()
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=2000)
    _run, lot = make_completed_run(plant["id"], line["id"], 1000, "2026-03-01")
    from test_helpers import make_delivered_order
    make_delivered_order(dealer["id"], line["id"], 400, "2026-03-02", ship_date="2026-03-02")
    contractor, _module = make_certified_contractor(name="Pro Carol", email="carol@build.example")
    return plant, line, dealer, contractor, lot


def test_claim_credit_prorated_variant(api):
    """PRD §3.10: "With zero remaining years the credit is zero — the claim may
    still be approved as `REPAIR` — and otherwise the credit is the original
    value multiplied by the ratio of remaining years to total warranty years,
    with a single truncation to whole cents applied once at the very end; the
    ratio itself is never pre-rounded."
    PRD §3.8: "`SILVER` grants ten warranty years"

    Design: Difficulty/dual_variant_calc/claim_credit_prorated_vs_expired
    """
    plant, line, dealer, contractor, lot = _claim_credit_setup(api)
    # Enhanced registration (SILVER tier -> warranty_years 10), install 2020-01-01.
    # registered_date back-dated to the install date so the 60-day window holds.
    reg = make_installed_registration(contractor["id"], dealer["id"], line["id"],
                                      "2020-01-01", lot["id"],
                                      registered_date="2020-01-01")
    reg = get_success_data(api.activate_warranty(
        reg["id"], make_contractor_headers(contractor["id"])))
    assert reg["warranty_years"] == 10
    # Filed 2026-08-01: elapsed 2404 days -> floor(2404/365) = 6 -> remaining 4.
    set_clock("2026-08-01T00:00:00Z")
    claim, _sample = make_under_review_claim(reg["id"], category="STRUCTURAL",
                                             filed_date="2026-08-01")
    approved = get_success_data(api.adjudicate_claim(
        claim["id"], {"decision": "APPROVE", "adjudication": "CREDIT"}, CA))
    assert approved["status"] == "APPROVED"
    assert approved["credit_amount_cents"] == 80000, (
        f"expected floor(200000*4/10) == 80000, got {approved['credit_amount_cents']}"
    )


def test_claim_credit_expired_variant_zero_remaining_years(api):
    """PRD §3.10: "the elapsed time from `install_date` to the claim's
    `filed_at` date, converted to whole years by dividing by 365 and
    truncating, is subtracted from the registration's `warranty_years` to give
    the remaining years (floored at zero)"
    PRD §3.10: "With zero remaining years the credit is zero — the claim may
    still be approved as `REPAIR`"

    Design: Difficulty/dual_variant_calc/claim_credit_prorated_vs_expired
    """
    plant, line, dealer, contractor, lot = _claim_credit_setup(api)
    # Enhanced registration (SILVER tier -> warranty_years 10), install
    # 2020-01-01. Filed 2029-12-29: exactly 3650 days elapsed, inside the
    # warranty-window gate (3650 <= 10*365) while floor(3650/365) = 10 leaves
    # zero remaining years -> the credit is zero.
    reg = make_installed_registration(contractor["id"], dealer["id"], line["id"],
                                      "2020-01-01", lot["id"],
                                      registered_date="2020-01-01")
    reg = get_success_data(api.activate_warranty(
        reg["id"], make_contractor_headers(contractor["id"])))
    assert reg["warranty_years"] == 10
    set_clock("2029-12-29T00:00:00Z")
    claim, _sample = make_under_review_claim(reg["id"], category="STRUCTURAL",
                                             filed_date="2029-12-29")
    approved = get_success_data(api.adjudicate_claim(
        claim["id"], {"decision": "APPROVE", "adjudication": "CREDIT"}, CA))
    assert approved["status"] == "APPROVED"
    assert approved["credit_amount_cents"] == 0, (
        f"expected expired-variant credit 0, got {approved['credit_amount_cents']}"
    )
