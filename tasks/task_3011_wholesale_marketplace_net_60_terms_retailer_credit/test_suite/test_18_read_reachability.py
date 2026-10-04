"""Queue B (Corner/endpoints): nested reverse reachability and the logical
clock."""

from test_helpers import (
    ADMIN,
    DEFAULT_CLOCK_ISO,
    clock_payload,
    get_order_lines,
    get_success_data,
    order_line,
    place_order,
    ship_order,
    standard_market,
    validate_success,
)


def test_order_children_reverse_reachable(api):
    """PRD §3.11: "An order's lines, its invoice (returned as an array of zero
    or one entries, since an invoice exists only after shipment), and its
    return authorizations are each reachable from the order; a return
    authorization's lines are reachable from the authorization; and the return
    lines recorded against a specific order line are reachable from that order
    line, anchoring reverse reachability across the return flow."

    Design: Corner/endpoints/order_lines_and_invoice_reverse_reachable
    """
    retailer, _, brand = standard_market(
        api, {"lead_time_days": 0}, {"store_type": "ONLINE"}
    )
    order = place_order(api, retailer["id"], brand["id"], [order_line("S1", 5000, 2)])

    # Before shipment: no invoice, no return authorizations.
    invoice_list = get_success_data(api.get_order_invoice(order["id"], ADMIN))
    assert invoice_list == []
    ras = get_success_data(api.list_order_return_authorizations(order["id"], ADMIN))
    assert ras == []

    lines = get_order_lines(api, order["id"])
    assert len(lines) == 1
    assert lines[0]["amount_cents"] == 10000
    assert lines[0]["net_sold_qty"] == 2

    # After shipment: exactly one invoice appears in the 0-or-1 array.
    ship_order(api, order["id"], brand["id"])
    invoice_list = get_success_data(api.get_order_invoice(order["id"], ADMIN))
    assert len(invoice_list) == 1
    assert invoice_list[0]["amount_due_cents"] == 10000

    # Return lines are reachable from the order line.
    return_lines = get_success_data(
        api.list_order_line_return_lines(lines[0]["id"], ADMIN)
    )
    assert return_lines == []


def test_clock_default_and_set(api):
    """PRD §2.5: "On server startup the logical clock is exactly
    2026-09-01T00:00:00Z, and it advances only when a `PlatformAdmin`
    explicitly sets it by supplying a `to_iso8601` instant, after which the
    server reports the new logical time as `now_iso8601`."

    Design: Corner/endpoints/clock_default_and_set
    """
    first = validate_success(api.set_clock(clock_payload(DEFAULT_CLOCK_ISO), ADMIN))
    assert first["now_iso8601"] == "2026-09-01T00:00:00Z"

    second = validate_success(api.set_clock(clock_payload("2026-09-15T12:00:00Z"), ADMIN))
    assert second["now_iso8601"] == "2026-09-15T12:00:00Z"
