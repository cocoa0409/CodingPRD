"""Precedence between a state precondition and a clock-relative rule."""

from test_helpers import (
    ANY, TEST_USERS, api_client, get_success_data,
    setup_order_line_bought_confirmed, validate_error, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]
DOCK = TEST_USERS["cross_dock_headers"]


def _shipped_order(unit_price_cents=250, allocation_units=5):
    """An order driven all the way to SHIPPED, captured, with the clock far past its
    cancellation window.

    Returns (vendor, event, listing, customer, order, line).
    """
    api_client.set_clock("2026-09-01T00:00:00Z", MERCH)
    ctx = setup_order_line_bought_confirmed(
        confirm_units=2, quantity=2, unit_price_cents=unit_price_cents,
        vendor_unit_cost_cents=150, allocation_units=allocation_units,
        vendor_sku="NW-PRI-1")
    vendor, shop, event, listing, customer, order, line, po = ctx

    shipment = get_success_data(api_client.create_shipment({
        "purchase_order_id": po["id"], "quantity_shipped": 2,
        "carrier_tracking_code": "PRI-TRK-1",
        "shipped_at": "2026-09-01T00:00:00Z",
        "allocations": [{"listing_id": listing["id"], "quantity": 2}]},
        {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
         "Content-Type": "application/json"}))
    get_success_data(api_client.receive_shipment(
        shipment["id"], {"arrived_at": "2026-09-01T09:00:00Z",
                         "bucket_units_reported": 2}, DOCK))
    get_success_data(api_client.capture_order(order["id"], PLANNER))
    current = get_success_data(api_client.get_order(order["id"], ANY))
    parcel = get_success_data(api_client.consolidate_order(
        order["id"], {"expected_order_version": current["version"]}, DOCK))
    get_success_data(api_client.seal_parcel(parcel["id"], DOCK))
    get_success_data(api_client.dispatch_parcel(parcel["id"], DOCK))
    api_client.set_clock("2026-10-15T00:00:00Z", MERCH)
    return vendor, event, listing, customer, order, line


def test_shipped_order_cancellation_reports_the_state_error(api, merchandiser_headers):
    """PRD §2.12: "Then the platform asks whether the requested transition exists
    from the addressed resource's current state at all; a request that names a
    transition the state machine does not permit is refused with `ERR_INVALID_STATE`,
    and nothing else in the request is evaluated."

    Design: Difficulty/priority_pair_validation_conflict/cancellation_state_precondition_defeats_closed_window
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, customer, order, line = _shipped_order()

    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    res = api.cancel_order(order["id"], {"reason_code": "CHANGED_MIND"}, cust_h)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    order_after = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_after["order_status"] == "SHIPPED", (
        "the refused cancellation must leave the fulfilment posture untouched")
    assert order_after["payment_status"] == "CAPTURED"

    ledger = validate_success(api.get_credit_ledger(customer["id"], ANY), 200)
    rows = ledger if isinstance(ledger, list) else ledger.get("data", ledger)
    assert rows == [], "no ledger row is written by a refused cancellation"


def test_shipped_order_exposes_a_window_the_clock_has_already_left(
        api, merchandiser_headers):
    """PRD §3.3: "`cancellation_window_ends_at` is computed as the earliest, over the
    order's lines, of the line's `confirmed_at` plus 30 hours and the line's event's
    `ends_at`".

    PRD §3.3: "Once it is true, a cancellation request fails with
    `ERR_CANCELLATION_WINDOW_CLOSED` even if the clock is still inside the window.
    After delivery the order can still be returned — that is the path described in
    §3.8 — but it cannot be cancelled."

    Design: Difficulty/priority_pair_validation_conflict/cancellation_state_precondition_defeats_closed_window
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, customer, order, line = _shipped_order()

    order_after = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_after["cancellation_window_ends_at"] is not None, (
        "the window is defined because the order carries a priced line")
    assert order_after["cancellation_window_ends_at"].startswith("2026-09-02"), (
        "the line's event ends at 2026-09-02T00:00:00Z, which is earlier than the "
        "30-hour anchor, so the window is pinned to the event end, got "
        f"{order_after['cancellation_window_ends_at']}")
    assert order_after["cancellation_window_ends_at"] < "2026-10-15T00:00:00Z", (
        "the clock has genuinely moved past the window; the refusal is therefore an "
        "ordering result and not an unviolated rule")
    assert order_after["cancellation_waived"] is True, (
        "the line reached PURCHASE_ORDER_ISSUED, so cancellation is waived")