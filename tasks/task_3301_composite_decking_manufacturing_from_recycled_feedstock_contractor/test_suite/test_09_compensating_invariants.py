"""Compensating invariants: dealer outstanding_cents conservation and the
plant reserved_fg_store pool conservation."""
from test_helpers import (
    get_success_data,
    make_active_formulation,
    make_allocation_commitment,
    make_certified_contractor,
    make_completed_run,
    make_dealer,
    make_delivered_order,
    make_enhanced_registration,
    make_plant,
    make_price_book,
    make_product_line,
    make_supplier,
    make_under_review_claim,
    set_clock,
    stock_resin,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_manager_headers"]
DSR = TEST_USERS["dealer_sales_rep_headers"]
CA = TEST_USERS["claims_adjuster_headers"]
CM = TEST_USERS["channel_manager_headers"]


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


def test_outstanding_cents_credit_invariant(api):
    """PRD §3.6: "Shipping decrements the line's `fg_store` by the order
    footage, computes the final invoice ... and the amount is added to the
    dealer's `outstanding_cents`."
    PRD §3.10: "The credit is debited against the selling dealer's
    `outstanding_cents`."

    Design: Difficulty/compensating_invariant/outstanding_cents_credit_invariant
    """
    plant, line, dealer, contractor, lot = _claim_setup(api)
    reg = make_enhanced_registration(contractor["id"], dealer["id"], line["id"],
                                     "2020-01-01", lot["id"],
                                     registered_date="2020-01-01")
    set_clock("2026-08-01T00:00:00Z")
    claim, _sample = make_under_review_claim(reg["id"], category="STRUCTURAL",
                                             filed_date="2026-08-01")

    before = get_success_data(api.get_dealer(dealer["id"], CM))
    assert before["outstanding_cents"] == 200000

    approved = get_success_data(api.adjudicate_claim(
        claim["id"], {"decision": "APPROVE", "adjudication": "CREDIT"}, CA))
    assert approved["credit_amount_cents"] == 80000

    after = get_success_data(api.get_dealer(dealer["id"], CM))
    assert after["outstanding_cents"] == before["outstanding_cents"] - 80000 == 120000


def test_outstanding_accumulates_across_two_shipments(api):
    """PRD §3.6: "the amount is added to the dealer's `outstanding_cents`."

    Design: Difficulty/compensating_invariant/outstanding_cents_credit_invariant
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(lines=2)
    form = make_active_formulation()
    line = make_product_line(form["id"])
    make_price_book(base_prices={line["id"]: 500})
    dealer = make_dealer()
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=2000)
    make_completed_run(plant["id"], line["id"], 1000, "2026-03-01")
    make_delivered_order(dealer["id"], line["id"], 400, "2026-03-02", ship_date="2026-03-02")
    make_delivered_order(dealer["id"], line["id"], 100, "2026-03-02", ship_date="2026-03-02")
    dealer_after = get_success_data(api.get_dealer(dealer["id"], CM))
    assert dealer_after["outstanding_cents"] == 200000 + 50000


def test_finished_goods_reservation_invariant(api):
    """PRD §3.7: "Creation adds `reserved_lf` to the plant's
    `reserved_fg_store` for the line and increments the plant's `version`."
    PRD §3.7: "explicitly released by a `DealerSalesRep` (`OPEN → RELEASED`,
    which subtracts the remaining reserved footage from the reserved ledger)"

    Design: Difficulty/compensating_invariant/finished_goods_reservation_invariant
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(daily_capacity_lf=10000, lines=1)
    form = make_active_formulation()
    line = make_product_line(form["id"])
    book = make_price_book(base_prices={line["id"]: 500})
    dealer = make_dealer()

    plant0 = get_success_data(api.get_plant(plant["id"], OPS))
    assert plant0["reserved_fg_store"].get(line["id"], 0) == 0

    ac = make_allocation_commitment(plant["id"], dealer["id"], line["id"], 500, book["id"])
    plant1 = get_success_data(api.get_plant(plant["id"], OPS))
    assert plant1["reserved_fg_store"][line["id"]] == 500
    assert plant1["version"] == plant0["version"] + 1

    released = get_success_data(api.release_allocation_commitment(ac["id"], DSR))
    assert released["status"] == "RELEASED"
    plant2 = get_success_data(api.get_plant(plant["id"], OPS))
    assert plant2["reserved_fg_store"].get(line["id"], 0) == 0


def test_reservation_pool_conserved_across_two_allocations(api):
    """PRD §2.10: "The reserved ledger is additive-only and independent of
    `fg_store`; it is incremented when a reservation is created and
    decremented when the reservation is consumed, released, or expired."

    Design: Difficulty/compensating_invariant/finished_goods_reservation_invariant
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant(daily_capacity_lf=10000, lines=1)
    form = make_active_formulation()
    line = make_product_line(form["id"])
    book = make_price_book(base_prices={line["id"]: 500})
    dealer = make_dealer()

    ac1 = make_allocation_commitment(plant["id"], dealer["id"], line["id"], 300, book["id"])
    ac2 = make_allocation_commitment(plant["id"], dealer["id"], line["id"], 200, book["id"])
    plant_now = get_success_data(api.get_plant(plant["id"], OPS))
    assert plant_now["reserved_fg_store"][line["id"]] == 500

    get_success_data(api.release_allocation_commitment(ac1["id"], DSR))
    plant_now = get_success_data(api.get_plant(plant["id"], OPS))
    assert plant_now["reserved_fg_store"][line["id"]] == 200

    get_success_data(api.release_allocation_commitment(ac2["id"], DSR))
    plant_now = get_success_data(api.get_plant(plant["id"], OPS))
    assert plant_now["reserved_fg_store"].get(line["id"], 0) == 0
