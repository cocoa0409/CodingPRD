"""Transitive cascades: deliver -> commitment MET -> tier flip -> cheaper
invoice; claim approval -> credit -> dealer outstanding decrement."""
from test_helpers import (
    confirm_order,
    deliver_order,
    get_success_data,
    make_active_formulation,
    make_certified_contractor,
    make_completed_run,
    make_contractor_headers,
    make_dealer,
    make_delivered_order,
    make_enhanced_registration,
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

CA = TEST_USERS["claims_adjuster_headers"]
CM = TEST_USERS["channel_manager_headers"]


def _base_distribution(api):
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(lines=2)
    form = make_active_formulation()
    line = make_product_line(form["id"])
    # effective_from 2025 so season-2025 fulfillment orders can pin the book
    make_price_book(base_prices={line["id"]: 500}, effective_from="2025-01-01")
    dealer = make_dealer()
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=3000)
    make_completed_run(plant["id"], line["id"], 2000, "2026-03-01")
    return plant, line, dealer


def test_deliver_flips_commitment_met_then_tier_discounts_next_invoice(api):
    """PRD §3.6: "Delivery, performed by the `Dealer` whose `X-User-ID` equals
    the order's `dealer_id`, advances the matching open stocking commitment —
    the one for the same dealer, product line, and the season year of the ship
    date — by adding the order's footage to `fulfilled_lf`; when
    `fulfilled_lf` reaches or exceeds `committed_lf` the commitment
    transitions `OPEN → MET`."
    PRD §3.6: "The dealer's tier is `PREFERRED` when the dealer has at least
    one stocking commitment that closed `MET` with a `season_year` equal to
    the year of the ship date minus one, and `STANDARD` otherwise."

    Design: Difficulty/transitive_cascade/deliver_to_commitment_met_to_tier_flip_to_cheaper_invoice
    """
    plant, line, dealer = _base_distribution(api)

    # Order M ships BEFORE the 2025 commitment exists: STANDARD, 100000 cents.
    order_m = make_order(dealer["id"], line["id"], 200, "2026-03-02")
    confirm_order(order_m["id"])
    set_clock("2026-03-02T00:00:00Z")
    shipped_m = ship_order(order_m["id"])

    # Commitment for season 2025 with committed 1 lf; deliver a 1-lf order
    # shipped in 2025 to flip it MET (the cascade hop 1: deliver -> fulfilled
    # -> MET). Delivery advances the commitment whose season_year equals the
    # ship date's year, so the fulfilling order ships in 2025.
    set_clock("2025-12-15T00:00:00Z")
    sc25 = make_stocking_commitment(dealer["id"], "VA-N", line["id"], 1, 2025)
    order_fill = make_order(dealer["id"], line["id"], 1, "2025-12-15")
    confirm_order(order_fill["id"])
    ship_order(order_fill["id"])
    deliver_order(order_fill["id"], dealer["id"])
    sc_after = get_success_data(api.get_stocking_commitment(sc25["id"], CM))
    assert sc_after["status"] == "MET"
    assert sc_after["fulfilled_lf"] == 1

    # Order N: identical data, ships after the cascade -> PREFERRED 90000.
    set_clock("2026-03-02T00:00:00Z")
    order_n = make_order(dealer["id"], line["id"], 200, "2026-03-02")
    confirm_order(order_n["id"])
    shipped_n = ship_order(order_n["id"])

    assert shipped_m["invoiced_cents"] == 100000
    assert shipped_n["invoiced_cents"] == 90000, (
        f"tier flip must discount the post-cascade invoice: {shipped_n['invoiced_cents']}"
    )


def test_commitment_met_only_at_fulfillment_threshold(api):
    """PRD §3.6: "when `fulfilled_lf` reaches or exceeds `committed_lf` the
    commitment transitions `OPEN → MET`."

    Design: Difficulty/transitive_cascade/deliver_to_commitment_met_to_tier_flip_to_cheaper_invoice
    """
    plant, line, dealer = _base_distribution(api)
    sc = make_stocking_commitment(dealer["id"], "VA-N", line["id"], 1000, 2026)
    # Deliver 800: below threshold -> stays OPEN.
    make_delivered_order(dealer["id"], line["id"], 800, "2026-03-02", ship_date="2026-03-02")
    sc_mid = get_success_data(api.get_stocking_commitment(sc["id"], CM))
    assert sc_mid["status"] == "OPEN"
    assert sc_mid["fulfilled_lf"] == 800
    # Deliver the remaining 200: threshold reached -> MET.
    make_delivered_order(dealer["id"], line["id"], 200, "2026-03-02", ship_date="2026-03-02")
    sc_done = get_success_data(api.get_stocking_commitment(sc["id"], CM))
    assert sc_done["status"] == "MET"
    assert sc_done["fulfilled_lf"] == 1000


def _claim_setup(api):
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
    make_delivered_order(dealer["id"], line["id"], 400, "2026-03-02", ship_date="2026-03-02")
    contractor, _module = make_certified_contractor(name="Pro Carol", email="carol@build.example")
    return plant, line, dealer, contractor, lot


def test_claim_credit_approval_cascades_to_dealer_outstanding(api):
    """PRD §3.10: "The credit is debited against the selling dealer's
    `outstanding_cents`."

    Design: Difficulty/transitive_cascade/claim_credit_approval_cascades_to_dealer_outstanding
    """
    plant, line, dealer, contractor, lot = _claim_setup(api)
    reg = make_enhanced_registration(contractor["id"], dealer["id"], line["id"],
                                     "2020-01-01", lot["id"],
                                     registered_date="2020-01-01")
    assert reg["warranty_years"] == 10
    set_clock("2026-08-01T00:00:00Z")
    claim, _sample = make_under_review_claim(reg["id"], category="STRUCTURAL",
                                             filed_date="2026-08-01")

    dealer_before = get_success_data(api.get_dealer(dealer["id"], CM))
    assert dealer_before["outstanding_cents"] == 200000

    approved = get_success_data(api.adjudicate_claim(
        claim["id"], {"decision": "APPROVE", "adjudication": "CREDIT"}, CA))
    assert approved["status"] == "APPROVED"
    assert approved["credit_amount_cents"] == 80000

    dealer_after = get_success_data(api.get_dealer(dealer["id"], CM))
    assert dealer_after["outstanding_cents"] == 120000, (
        "the credit approval itself must debit the dealer ledger; got "
        f"{dealer_after['outstanding_cents']}"
    )


def test_claim_repair_approval_leaves_dealer_outstanding_unchanged(api):
    """PRD §3.10: "The credit is debited against the selling dealer's
    `outstanding_cents`." (the debit is specific to CREDIT adjudication)

    Design: Difficulty/transitive_cascade/claim_credit_approval_cascades_to_dealer_outstanding
    """
    plant, line, dealer, contractor, lot = _claim_setup(api)
    reg = make_enhanced_registration(contractor["id"], dealer["id"], line["id"],
                                     "2020-01-01", lot["id"],
                                     registered_date="2020-01-01")
    set_clock("2026-08-01T00:00:00Z")
    claim, _sample = make_under_review_claim(reg["id"], category="STRUCTURAL",
                                             filed_date="2026-08-01")
    approved = get_success_data(api.adjudicate_claim(
        claim["id"], {"decision": "APPROVE", "adjudication": "REPAIR"}, CA))
    assert approved["status"] == "APPROVED"
    dealer_after = get_success_data(api.get_dealer(dealer["id"], CM))
    assert dealer_after["outstanding_cents"] == 200000
