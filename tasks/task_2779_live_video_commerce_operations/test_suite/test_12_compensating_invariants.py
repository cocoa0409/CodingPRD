"""Round trips that must return both ledgers to the numbers they started from."""

from test_helpers import (
    abandon_cart,
    assert_both_ledgers_conserved,
    assert_inventory_pool_conserved,
    assert_offer_allotment_conserved,
    base_scenario,
    cancel_order,
    capture_order,
    checkout_cart_of,
    hold_line,
    read_cart,
    read_line,
    read_offer,
    read_order,
    read_product,
    read_show,
    recover_cart,
)


def _four_units_held():
    """Viewer 1 holds four units of the 3500-cent offer in a LIVE show at 18:10Z."""
    scenario = base_scenario(num_viewers=1, num_carts=1)
    line = hold_line(scenario, 4)
    return scenario, line


def test_the_hold_takes_four_units_out_of_availability():
    """INV-1 holds with four units reserved: 50 == 46 + 4 + 0.

    The PRD: "the product's reserved_qty is increased by the line's qty and
    available_qty is recomputed", under the invariant that on_hand_qty equals
    available plus reserved plus committed.

    Design: Difficulty/compensating_invariant/hold_release_rehold_conserves_product_units
    """
    scenario, _line = _four_units_held()

    product = read_product(scenario.product_id)
    assert product["reserved_qty"] == 4
    assert product["committed_qty"] == 0
    assert product["available_qty"] == 46
    assert_inventory_pool_conserved(product)

    offer = read_offer(scenario.offer_id)
    assert offer["held_qty"] == 4
    assert offer["remaining_qty"] == 6
    assert_offer_allotment_conserved(offer)


def test_the_held_line_prices_at_the_lower_bundle_tier():
    """A 14000-cent subtotal takes the 0.05 tier, so four units gross 13300.

    The PRD: "otherwise a subtotal of at least 50 dollars takes the lower tier of
    0.05", and "The line's line_gross_cents is effective_unit_price_cents
    multiplied by qty".

    Design: Difficulty/compensating_invariant/hold_release_rehold_conserves_product_units
    """
    _scenario, line = _four_units_held()

    held = read_line(line["id"])
    assert held["effective_unit_price_cents"] == 3325
    assert held["line_gross_cents"] == 13300
    assert held["line_tax_cents"] == 1164


def test_abandoning_returns_the_units_with_no_drift():
    """Availability goes back to exactly 50 and the allotment back to exactly 10.

    The PRD: "Per released line, the product's reserved_qty and the offer's
    held_qty are decremented by that line's qty, and available_qty and
    remaining_qty are recomputed."

    Design: Difficulty/compensating_invariant/hold_release_rehold_conserves_product_units
    """
    scenario, line = _four_units_held()

    abandon_cart(scenario.cart_id, scenario.viewer_id)

    product = read_product(scenario.product_id)
    assert product["reserved_qty"] == 0
    assert product["available_qty"] == 50

    offer = read_offer(scenario.offer_id)
    assert offer["held_qty"] == 0
    assert offer["remaining_qty"] == 10
    assert_both_ledgers_conserved(product, offer)

    released = read_line(line["id"])
    assert released["state"] == "RELEASED"
    assert released["released_reason"] == "CART_ABANDONED"


def test_abandoning_counts_the_lost_basket_on_the_show():
    """One abandoned cart out of one cart is a rate of ten thousand basis points.

    The PRD: "Finally the show's abandoned_cart_count is incremented and its
    abandonment_rate_bp recomputed".

    Design: Difficulty/compensating_invariant/hold_release_rehold_conserves_product_units
    """
    scenario, _line = _four_units_held()

    abandon_cart(scenario.cart_id, scenario.viewer_id)

    show = read_show(scenario.show_id)
    assert show["abandoned_cart_count"] == 1
    assert show["abandonment_rate_bp"] == 10000


def test_recovering_re_consumes_exactly_the_same_four_units():
    """The re-hold reprices at the same tier and lands on the same ledger figures.

    The PRD: "the line returns to state HELD with released_reason and released_at
    cleared, and its effective_unit_price_cents, line_gross_cents and
    line_tax_cents are re-locked at the current bundle tier"; "Per re-held line,
    the product's reserved_qty and the offer's held_qty are incremented".

    Design: Difficulty/compensating_invariant/hold_release_rehold_conserves_product_units
    """
    scenario, line = _four_units_held()

    abandon_cart(scenario.cart_id, scenario.viewer_id)
    recover_cart(scenario.cart_id, scenario.viewer_id)

    reheld = read_line(line["id"])
    assert reheld["state"] == "HELD"
    assert reheld["released_reason"] is None
    assert reheld["effective_unit_price_cents"] == 3325

    product = read_product(scenario.product_id)
    assert product["reserved_qty"] == 4
    assert product["available_qty"] == 46

    offer = read_offer(scenario.offer_id)
    assert offer["held_qty"] == 4
    assert offer["remaining_qty"] == 6
    assert_both_ledgers_conserved(product, offer)


def test_recovering_unwinds_the_cart_and_the_show_counter():
    """The recovery clears the deadline and takes the show's loss counter back to zero.

    The PRD: "The cart's recovered_count is incremented by one, abandoned_at and
    recovery_deadline_at are cleared back to null, the show's abandoned_cart_count
    is decremented and abandonment_rate_bp recomputed".

    Design: Difficulty/compensating_invariant/hold_release_rehold_conserves_product_units
    """
    scenario, _line = _four_units_held()

    abandon_cart(scenario.cart_id, scenario.viewer_id)
    recover_cart(scenario.cart_id, scenario.viewer_id)

    cart = read_cart(scenario.cart_id, scenario.viewer_id)
    assert cart["status"] == "OPEN"
    assert cart["recovered_count"] == 1
    assert cart["abandoned_at"] is None
    assert cart["recovery_deadline_at"] is None

    show = read_show(scenario.show_id)
    assert show["abandoned_cart_count"] == 0
    assert show["abandonment_rate_bp"] == 0


def _three_units_ordered():
    """Three units committed into one order: merchandise 9975, total 10848."""
    scenario = base_scenario(num_viewers=1, num_carts=1)
    line = hold_line(scenario, 3)
    order = checkout_cart_of(scenario, 0)
    return scenario, line, order


def test_checkout_moves_the_allotment_sideways_from_held_to_sold():
    """INV-2 still reads 10 == 7 + 0 + 3 after the commitment.

    The PRD: "the offer's held_qty is decreased and its sold_qty increased by that
    qty, leaving remaining_qty unchanged"; "the product's reserved_qty is decreased
    by that line's qty and its committed_qty increased by the same amount — so
    available_qty is unchanged".

    Design: Difficulty/compensating_invariant/capture_refund_conserves_offer_allotment_and_money
    """
    scenario, line, _order = _three_units_ordered()

    assert read_line(line["id"])["state"] == "COMMITTED"

    offer = read_offer(scenario.offer_id)
    assert offer["held_qty"] == 0
    assert offer["sold_qty"] == 3
    assert offer["remaining_qty"] == 7
    assert_offer_allotment_conserved(offer)

    product = read_product(scenario.product_id)
    assert product["reserved_qty"] == 0
    assert product["committed_qty"] == 3
    assert product["available_qty"] == 47
    assert_inventory_pool_conserved(product)


def test_the_order_totals_lock_the_discounted_money():
    """9975 of merchandise ships free and carries 873 cents of tax.

    The PRD: "merchandise_cents is the sum of line_gross_cents across the committed
    lines", "shipping_cents is a flat 5.99 dollars, except that it is zero when
    merchandise_cents reaches at least 75 dollars", and "total_cents is
    merchandise_cents plus tax_cents plus shipping_cents".

    Design: Difficulty/compensating_invariant/capture_refund_conserves_offer_allotment_and_money
    """
    _scenario, _line, order = _three_units_ordered()

    fresh = read_order(order["id"])
    assert fresh["merchandise_cents"] == 9975
    assert fresh["tax_cents"] == 873
    assert fresh["shipping_cents"] == 0
    assert fresh["total_cents"] == 10848


def test_capture_accrues_the_commission_and_the_gross():
    """Eight percent of 9975 is 798, and the show's captured gross is 9975.

    The PRD: "It stamps host_commission_accrued_cents as the order's
    merchandise_cents multiplied by the commission_pct of the host holding this
    show's PRIMARY booking, rounded half up to a whole cent."

    Design: Difficulty/compensating_invariant/capture_refund_conserves_offer_allotment_and_money
    """
    scenario, _line, order = _three_units_ordered()

    capture_order(order["id"])

    assert read_order(order["id"])["host_commission_accrued_cents"] == 798
    assert read_show(scenario.show_id)["gross_merchandise_cents"] == 9975


def test_the_refund_unwinds_the_money_it_accrued():
    """A captured order refunds its whole total and gives back the commission.

    The PRD: "A captured order moves CAPTURED -> REFUNDED, its fulfillment_state
    moving ALLOCATED -> CANCELLED; refunded_cents is set to the order's
    total_cents, host_commission_accrued_cents is reset to 0".

    Design: Difficulty/compensating_invariant/capture_refund_conserves_offer_allotment_and_money
    """
    _scenario, _line, order = _three_units_ordered()

    capture_order(order["id"])
    cancel_order(order["id"], cancel_reason="FULL_RETURN")

    refunded = read_order(order["id"])
    assert refunded["payment_state"] == "REFUNDED"
    assert refunded["fulfillment_state"] == "CANCELLED"
    assert refunded["refunded_cents"] == 10848
    assert refunded["host_commission_accrued_cents"] == 0


def test_the_refund_restores_both_ledgers_exactly():
    """sold_qty unwinds to 0 and the units return to availability with no drift.

    The PRD: both cancellation branches "release every COMMITTED line of the
    order's cart to RELEASED with released_reason set to ORDER_CANCELLED, decrement
    the product's committed_qty and the offer's sold_qty by each released qty while
    recomputing available_qty and remaining_qty".

    Design: Difficulty/compensating_invariant/capture_refund_conserves_offer_allotment_and_money
    """
    scenario, line, order = _three_units_ordered()

    capture_order(order["id"])
    cancel_order(order["id"], cancel_reason="FULL_RETURN")

    offer = read_offer(scenario.offer_id)
    assert offer["sold_qty"] == 0
    assert offer["held_qty"] == 0
    assert offer["remaining_qty"] == 10
    assert offer["status"] == "ACTIVE"

    product = read_product(scenario.product_id)
    assert product["committed_qty"] == 0
    assert product["available_qty"] == 50
    assert_both_ledgers_conserved(product, offer)

    released = read_line(line["id"])
    assert released["state"] == "RELEASED"
    assert released["released_reason"] == "ORDER_CANCELLED"


def test_the_refund_empties_the_show_level_money():
    """The refunded order leaves both aggregates, so gross and margin fall to zero.

    The PRD: "the show's gross_merchandise_cents and margin_provisional_cents are
    both recomputed, because the refunded order leaves both aggregates."

    Design: Difficulty/compensating_invariant/capture_refund_conserves_offer_allotment_and_money
    """
    scenario, _line, order = _three_units_ordered()

    capture_order(order["id"])
    cancel_order(order["id"], cancel_reason="FULL_RETURN")

    show = read_show(scenario.show_id)
    assert show["gross_merchandise_cents"] == 0
    assert show["margin_provisional_cents"] == 0
