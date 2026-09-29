"""One order, two independent dimensions: payment and fulfilment."""

from test_helpers import (
    base_scenario,
    cancel_order,
    capture_order,
    checkout_cart_of,
    hold_line,
    read_offer,
    read_order,
    read_product,
    read_show,
)


def _two_single_unit_orders():
    """Each of two viewers buys one unit at 3500 cents; both orders start authorised."""
    scenario = base_scenario()
    hold_line(scenario, 1, cart_index=0)
    hold_line(scenario, 1, cart_index=1)
    first = checkout_cart_of(scenario, 0)
    second = checkout_cart_of(scenario, 1)
    return scenario, first, second


def test_capture_advances_both_dimensions_in_a_single_request():
    """One capture call moves payment to captured and fulfilment to allocated.

    The PRD: "Capture moves both dimensions: payment_state goes AUTHORIZED ->
    CAPTURED with captured_at stamped at the logical instant, and fulfillment_state
    goes PENDING -> ALLOCATED".

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    scenario, first, second = _two_single_unit_orders()

    capture_order(first["id"])

    order = read_order(first["id"])
    assert order["payment_state"] == "CAPTURED"
    assert order["fulfillment_state"] == "ALLOCATED"
    assert order["host_commission_accrued_cents"] == 280
    assert read_show(scenario.show_id)["gross_merchandise_cents"] == 3500


def test_cancelling_a_never_captured_order_voids_it_without_a_refund():
    """The authorised order voids, refunds nothing, and leaves the show's revenue alone.

    The PRD: "A never-captured order — payment_state of AUTHORIZED — moves
    AUTHORIZED -> VOIDED, its fulfillment_state moving PENDING -> CANCELLED;
    refunded_cents stays 0, and the show's gross_merchandise_cents is unchanged,
    because a never-captured order was never inside that figure."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    scenario, first, second = _two_single_unit_orders()

    capture_order(first["id"])
    cancel_order(second["id"], cancel_reason="VIEWER_CHANGED_MIND")

    order = read_order(second["id"])
    assert order["payment_state"] == "VOIDED"
    assert order["fulfillment_state"] == "CANCELLED"
    assert order["refunded_cents"] == 0
    assert read_show(scenario.show_id)["gross_merchandise_cents"] == 3500


def test_voiding_returns_the_unit_to_inventory_and_to_the_allotment():
    """The voided order's committed unit goes back to available stock and to remaining allotment.

    The PRD: both cancellation branches "decrement the product's committed_qty and
    the offer's sold_qty by each released qty while recomputing available_qty and
    remaining_qty".

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    scenario, first, second = _two_single_unit_orders()

    capture_order(first["id"])
    cancel_order(second["id"], cancel_reason="VIEWER_CHANGED_MIND")

    product = read_product(scenario.product_id)
    assert product["committed_qty"] == 1
    assert product["available_qty"] == 49

    offer = read_offer(scenario.offer_id)
    assert offer["sold_qty"] == 1
    assert offer["remaining_qty"] == 9


def test_cancelling_a_captured_order_refunds_the_total_and_clears_the_commission():
    """The same endpoint takes the captured order down a different money branch.

    The PRD: "A captured order moves CAPTURED -> REFUNDED, its fulfillment_state
    moving ALLOCATED -> CANCELLED; refunded_cents is set to the order's total_cents,
    host_commission_accrued_cents is reset to 0".

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    scenario, first, second = _two_single_unit_orders()

    capture_order(first["id"])
    cancel_order(second["id"], cancel_reason="VIEWER_CHANGED_MIND")
    cancel_order(first["id"], cancel_reason="DAMAGED_ON_ARRIVAL")

    order = read_order(first["id"])
    assert order["payment_state"] == "REFUNDED"
    assert order["fulfillment_state"] == "CANCELLED"
    assert order["refunded_cents"] == 4405
    assert order["host_commission_accrued_cents"] == 0


def test_a_refund_takes_the_revenue_out_of_the_shows_aggregates():
    """Refunding the only captured order empties both money aggregates on the show.

    The PRD: for the captured branch "the show's gross_merchandise_cents and
    margin_provisional_cents are both recomputed, because the refunded order leaves
    both aggregates."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    scenario, first, second = _two_single_unit_orders()

    capture_order(first["id"])
    cancel_order(second["id"], cancel_reason="VIEWER_CHANGED_MIND")
    cancel_order(first["id"], cancel_reason="DAMAGED_ON_ARRIVAL")

    show = read_show(scenario.show_id)
    assert show["gross_merchandise_cents"] == 0
    assert show["margin_provisional_cents"] == 0


def test_a_refund_restocks_the_offer_back_to_its_full_allotment():
    """With both orders cancelled the product and the offer are whole again.

    The PRD says both cancellation branches "restock any offer that was EXHAUSTED
    and now shows remaining_qty of at least 1 back to ACTIVE when its window is
    still open and the show is still LIVE", the ledgers returning to their opening
    figures.

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    scenario, first, second = _two_single_unit_orders()

    capture_order(first["id"])
    cancel_order(second["id"], cancel_reason="VIEWER_CHANGED_MIND")
    cancel_order(first["id"], cancel_reason="DAMAGED_ON_ARRIVAL")

    product = read_product(scenario.product_id)
    assert product["committed_qty"] == 0
    assert product["available_qty"] == 50

    offer = read_offer(scenario.offer_id)
    assert offer["sold_qty"] == 0
    assert offer["remaining_qty"] == 10
    assert offer["status"] == "ACTIVE"
