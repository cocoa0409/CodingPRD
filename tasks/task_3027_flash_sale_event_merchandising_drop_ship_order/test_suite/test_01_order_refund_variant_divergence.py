"""The two settlement variants on an order's refund money domain."""

from test_helpers import (
    ANY, TEST_USERS, api_client, get_success_data, setup_order_line_bought_confirmed,
    validate_success,
)

PLANNER = TEST_USERS["inventory_planner_headers"]


def _build_short_shipped_line(unit_price_cents=100, quantity=5, confirm_units=4):
    """One order carrying a single line that has been closed short.

    Returns (vendor, event, listing, customer, order, line, po).
    """
    ctx = setup_order_line_bought_confirmed(
        confirm_units=confirm_units, quantity=quantity,
        unit_price_cents=unit_price_cents, vendor_unit_cost_cents=60,
        allocation_units=10)
    vendor, shop, event, listing, customer, order, line, po = ctx
    get_success_data(api_client.capture_order(order["id"], PLANNER))
    get_success_data(api_client.close_short_purchase_order(
        po["id"], {"force_close": True}, PLANNER))
    return vendor, event, listing, customer, order, line, po


def test_short_shipped_line_is_marked_with_the_missing_units(api, merchandiser_headers):
    """PRD §3.6: "At the second hop, every `Confirmation` covering those listings
    whose `confirmed_units` is below its `quantity` moves to `SHORT_SHIPPED` with
    `short_shipped_units` set to `quantity` minus `confirmed_units`."

    Design: Difficulty/dual_variant_calc/order_refund_variant_divergence_on_short_shipped_line
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, customer, order, line, po = _build_short_shipped_line()

    after = validate_success(api.get_confirmation(line["id"], ANY), 200)
    assert after["confirmation_status"] == "SHORT_SHIPPED", (
        f"expected SHORT_SHIPPED, got {after['confirmation_status']}")
    assert after["quantity"] == 5
    assert after["confirmed_units"] == 4
    assert after["short_shipped_units"] == 1, (
        f"quantity - confirmed_units must be 1, got {after['short_shipped_units']}")


def test_full_line_writeoff_variant_refunds_the_whole_line_not_the_missing_units(
        api, merchandiser_headers):
    """PRD §3.6: "A `CustomerService`-approved full-line write-off instead refunds,
    for any line with positive `short_shipped_units`, the line's entire `quantity`
    multiplied by its `line_unit_price_cents` rather than only the missing units —
    so a five-unit line with four confirmed units refunds five units' value where
    the base behaviour refunds one."

    PRD §3.6: "A separate recompute operation, available to an `InventoryPlanner`
    or a `CustomerService` operator, names the `variant` explicitly and is the
    disciplined writer for an intentional change of basis; it recomputes
    `order_total_cents` and `refund_due_cents` in the named variant".

    Design: Difficulty/dual_variant_calc/order_refund_variant_divergence_on_short_shipped_line
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    planner = PLANNER
    vendor, event, listing, customer, order, line, po = _build_short_shipped_line()

    # Base variant: only the one unit the customer did not receive.
    validate_success(api.refund_order(
        order["id"], {"write_off_full_line": False}, planner), 200)
    reprice = validate_success(api.reprice_order(
        order["id"], {"variant": "NET_OF_ALLOCATION"}, planner), 200)
    base_refund = reprice["refund_due_cents"]
    assert base_refund == 100, (
        f"missing_units * line_unit_price_cents must be 1 * 100 = 100, got {base_refund}")

    # Gross line write-off: the whole quantity's value.
    written_off = validate_success(api.reprice_order(
        order["id"], {"variant": "GROSS_LINE_WRITEOFF"}, planner), 200)
    assert written_off["refund_due_cents"] == 500, (
        "quantity * line_unit_price_cents must be 5 * 100 = 500, got "
        f"{written_off['refund_due_cents']}")
    assert written_off["refund_due_cents"] != base_refund, (
        "the two variants must return different numbers for identical inputs")