"""Bundle pricing: the pinned four-step order and per-line tax rounding."""

from test_helpers import (
    DEFAULT_PRODUCT,
    add_line,
    build_scenario,
    checkout,
    read_cart,
    read_line,
    read_order,
)

SASH = {
    "sku": "SKU-SASH",
    "title": "Silk Sash",
    "base_price_cents": 2500,
    "unit_cost_cents": 900,
    "on_hand_qty": 40,
    "claim_text": "Hand rolled hem",
    "evidence_ref": "LAB-89",
}


def _two_product_basket():
    """A live show offering two distinct products, with one unit of each held in one cart."""
    scenario = build_scenario(
        products=[dict(DEFAULT_PRODUCT), dict(SASH)],
        slots=[
            {
                "slot_sequence": 1,
                "planned_start_at": "2026-08-10T18:05:00Z",
                "planned_end_at": "2026-08-10T18:35:00Z",
                "planned_qty": 20,
            },
            {
                "product_index": 1,
                "slot_sequence": 2,
                "planned_start_at": "2026-08-10T18:40:00Z",
                "planned_end_at": "2026-08-10T19:00:00Z",
                "planned_qty": 10,
            },
        ],
        offers=[
            {"offer_price_cents": 3333, "max_qty": 5},
            {"slot_index": 1, "offer_price_cents": 2222, "max_qty": 5},
        ],
        take_live=True,
        activate=True,
        num_carts=1,
    )
    first_line = add_line(scenario.cart_id, scenario.offers[0]["id"], scenario.viewer_id, 1)
    second_line = add_line(scenario.cart_id, scenario.offers[1]["id"], scenario.viewer_id, 1)
    return scenario, first_line, second_line


def _single_line_basket():
    """A live show whose only offer is 1700 cents, with an empty cart ready."""
    return build_scenario(
        offers=[{"offer_price_cents": 1700, "max_qty": 5}],
        take_live=True,
        activate=True,
        num_carts=1,
    )


def test_first_line_keeps_the_tier_that_applied_when_it_was_added():
    """A single 3333-cent line sits below the 50-dollar floor and takes no discount.

    The PRD: a line "keeps the effective price it locked at its own add time: a
    later add that lifts the cart into a higher tier does not reprice the earlier
    lines", and line tax is "line_gross_cents multiplied by a tax rate of 8.75
    percent, rounded half up to a whole cent, per line".

    Design: Difficulty/combinatorial_formula/order_totals_per_line_tax_then_sum
    """
    scenario, first_line, second_line = _two_product_basket()

    line = read_line(first_line["id"])
    assert line["effective_unit_price_cents"] == 3333
    assert line["line_gross_cents"] == 3333
    assert line["line_tax_cents"] == 292


def test_second_line_prices_at_the_tier_its_own_arrival_created():
    """The 2222-cent line lifts the subtotal to 5555 and prices itself at 5 percent off.

    The PRD: the subtotal sums "that line's offer_unit_price_cents multiplied by its
    qty, then add the incoming offer's offer_price_cents multiplied by the incoming
    qty", and "a subtotal of at least 50 dollars takes the lower tier of 0.05".

    Design: Difficulty/combinatorial_formula/order_totals_per_line_tax_then_sum
    """
    scenario, first_line, second_line = _two_product_basket()

    line = read_line(second_line["id"])
    assert line["effective_unit_price_cents"] == 2111
    assert line["line_gross_cents"] == 2111
    assert line["line_tax_cents"] == 185

    cart = read_cart(scenario.cart_id, scenario.viewer_id)
    assert cart["pre_discount_subtotal_cents"] == 5555
    assert cart["bundle_discount_pct"] == 0.05


def test_order_tax_adds_the_per_line_rounded_taxes_rather_than_taxing_the_sum():
    """Taxes of 292 and 185 add to 477, where taxing the 5444 merchandise once gives 476.

    The PRD: tax_cents "is the sum, across those same lines, of each line's gross
    multiplied by the 8.75 percent tax rate and rounded half up per line — the
    per-line rounded taxes are then added, and summing the gross first and taxing
    once is explicitly not the rule."

    Design: Difficulty/combinatorial_formula/order_totals_per_line_tax_then_sum
    """
    scenario, first_line, second_line = _two_product_basket()

    order = checkout(scenario.cart_id, scenario.viewer_id)
    order = read_order(order["id"])
    assert order["merchandise_cents"] == 5444
    assert order["tax_cents"] == 477
    assert order["shipping_cents"] == 599
    assert order["total_cents"] == 6520


def test_bundle_tier_is_selected_from_the_undiscounted_subtotal():
    """Three units at 1700 make an undiscounted subtotal of 5100, which earns the lower tier.

    The PRD: the subtotal "is computed first, from undiscounted offer prices" and
    "Because this subtotal is built from undiscounted prices, it can never depend on
    the discount it is about to determine"; the tier "is never re-derived from the
    discounted subtotal".

    Design: Difficulty/combinatorial_formula/effective_unit_price_pinned_four_step_order
    """
    scenario = _single_line_basket()

    line = add_line(scenario.cart_id, scenario.offer_id, scenario.viewer_id, 3)

    cart = read_cart(scenario.cart_id, scenario.viewer_id)
    assert cart["pre_discount_subtotal_cents"] == 5100
    assert cart["bundle_discount_pct"] == 0.05

    line = read_line(line["id"])
    assert line["offer_unit_price_cents"] == 1700
    assert line["list_unit_price_cents"] == 4000


def test_line_gross_multiplies_the_already_rounded_effective_unit_price():
    """The line prices at 1615 per unit for a gross of 4845, not the undiscounted 5100.

    The PRD: "The line's line_gross_cents is effective_unit_price_cents multiplied
    by qty, computed from the already-rounded per-unit figure — no fractional
    intermediate is carried into this multiplication."

    Design: Difficulty/combinatorial_formula/effective_unit_price_pinned_four_step_order
    """
    scenario = _single_line_basket()

    line = add_line(scenario.cart_id, scenario.offer_id, scenario.viewer_id, 3)

    line = read_line(line["id"])
    assert line["effective_unit_price_cents"] == 1615
    assert line["line_gross_cents"] == 4845
    assert line["line_tax_cents"] == 424


def test_order_totals_are_built_from_the_discounted_line():
    """The order carries the discounted merchandise figure, its tax and flat shipping.

    The PRD: "merchandise_cents is the sum of line_gross_cents across the committed
    lines", "shipping_cents is a flat 5.99 dollars, except that it is zero when
    merchandise_cents reaches at least 75 dollars", and "total_cents is
    merchandise_cents plus tax_cents plus shipping_cents".

    Design: Difficulty/combinatorial_formula/effective_unit_price_pinned_four_step_order
    """
    scenario = _single_line_basket()

    add_line(scenario.cart_id, scenario.offer_id, scenario.viewer_id, 3)
    order = checkout(scenario.cart_id, scenario.viewer_id)

    order = read_order(order["id"])
    assert order["merchandise_cents"] == 4845
    assert order["tax_cents"] == 424
    assert order["shipping_cents"] == 599
    assert order["total_cents"] == 5868
