"""Difficulty queue: dual pricing moments and pinned per-unit rounding order."""
from test_helpers import (
    make_customer, make_inventory_manager_headers, place_order,
    setup_lot_in_distribution, validate_success,
)


def _setup_order_date_ship_date(api):
    """Program (price 1000, ACCREDITED_LAB discount 10) + ACCREDITED_LAB
    customer + lot IN_DISTRIBUTION; order qty 5 placed by the customer."""
    program_overrides = {"program_code": "NIST-RM-02"}
    ctx = setup_lot_in_distribution(total=20, material_code="SRM-C",
                                    program_overrides=program_overrides)
    customer = make_customer(name="Accredited Lab Co", tier="ACCREDITED_LAB")
    order = place_order(ctx["lot"]["id"], customer["id"], 5)
    return ctx, customer, order


def test_order_date_price_frozen_at_creation(api, program_admin_headers):
    """PRD §3.5: "its order-date price is frozen immediately into
    `quoted_unit_price_cents`: the program's `material_unit_price_cents` reduced
    by the discount percentage matching the customer's `tier`, rounded half up
    to a whole cent per unit".
    PRD §3.5: "It reprices the order at the ship date: `final_unit_price_cents`
    is recomputed from the program's pricing as it stands at fulfillment".

    Design: Difficulty/dual_variant_calc/order_date_vs_ship_date_unit_pricing
    """
    ctx, _customer, order = _setup_order_date_ship_date(api)
    assert order["quoted_unit_price_cents"] == 900
    validate_success(
        api.pricing_update(ctx["program"]["id"],
                           {"expected_program_version": ctx["program"]["version"],
                            "material_unit_price_cents": 1200},
                           program_admin_headers))
    fulfilled = validate_success(
        api.transition_sales_order(order["id"], {"to": "FULFILLED"},
                                   make_inventory_manager_headers()))
    assert fulfilled["final_unit_price_cents"] == 1080
    assert fulfilled["final_unit_price_cents"] != order["quoted_unit_price_cents"]


def test_ship_date_invoice_assembly(api, program_admin_headers):
    """PRD §3.5: "`invoice_subtotal_cents` is `allocated_quantity` times
    `final_unit_price_cents`; `handling_fee_cents` is the program's
    `handling_fee_flat_cents` when the subtotal is strictly below
    `handling_fee_threshold_cents` and zero when the subtotal reaches or exceeds
    the threshold; `invoice_total_cents` is their sum".

    Design: Difficulty/dual_variant_calc/order_date_vs_ship_date_unit_pricing
    """
    ctx, _customer, order = _setup_order_date_ship_date(api)
    validate_success(
        api.pricing_update(ctx["program"]["id"],
                           {"expected_program_version": ctx["program"]["version"],
                            "material_unit_price_cents": 1200},
                           program_admin_headers))
    fulfilled = validate_success(
        api.transition_sales_order(order["id"], {"to": "FULFILLED"},
                                   make_inventory_manager_headers()))
    assert fulfilled["invoice_subtotal_cents"] == 5400
    assert fulfilled["handling_fee_cents"] == 500
    assert fulfilled["invoice_total_cents"] == 5900


def _setup_per_unit_rounding():
    """Program price 995 with GENERAL discount 10; GENERAL customer; lot
    IN_DISTRIBUTION with 20 produced units."""
    ctx = setup_lot_in_distribution(
        total=20, material_code="SRM-E",
        program_overrides={"program_code": "NIST-RM-04",
                           "material_unit_price_cents": 995,
                           "discount_pct_accredited_lab": 0,
                           "discount_pct_general": 10})
    customer = make_customer(name="Gen Cust")
    order = place_order(ctx["lot"]["id"], customer["id"], 2)
    return ctx, customer, order


def test_per_unit_rounded_before_multiply(api):
    """PRD §2.6: "the per-unit price is rounded to integer cents before it is
    multiplied by any quantity; multiplying an unrounded unit price is
    forbidden."
    PRD §3.5: "its order-date price is frozen immediately into
    `quoted_unit_price_cents`".

    Design: Difficulty/combinatorial_formula/per_unit_then_multiply_price_rounding
    """
    _ctx, _customer, order = _setup_per_unit_rounding()
    assert order["quoted_unit_price_cents"] == 896
    fulfilled = validate_success(
        api.transition_sales_order(order["id"], {"to": "FULFILLED"},
                                   make_inventory_manager_headers()))
    assert fulfilled["invoice_subtotal_cents"] == 1792


def test_per_unit_invoice_total_with_handling_fee(api):
    """PRD §3.5: "`invoice_subtotal_cents` is `allocated_quantity` times
    `final_unit_price_cents`; `handling_fee_cents` is the program's
    `handling_fee_flat_cents` when the subtotal is strictly below
    `handling_fee_threshold_cents`".

    Design: Difficulty/combinatorial_formula/per_unit_then_multiply_price_rounding
    """
    _ctx, _customer, order = _setup_per_unit_rounding()
    fulfilled = validate_success(
        api.transition_sales_order(order["id"], {"to": "FULFILLED"},
                                   make_inventory_manager_headers()))
    assert fulfilled["invoice_subtotal_cents"] == 1792
    assert fulfilled["handling_fee_cents"] == 500
    assert fulfilled["invoice_total_cents"] == 2292
