"""Conserved quantities: a forward action followed by its compensation restores them."""

from test_helpers import (
    ANY, TEST_USERS, api_client, create_buy, fresh_vendor, get_success_data,
    setup_live_event_with_listing, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]
CS = TEST_USERS["customer_service_headers"]


def test_issuing_a_buy_moves_only_the_committed_quantity(
        api, merchandiser_headers):
    """PRD §3.4: "On success the buy moves to `ISSUED`, `issued_at` is stamped with
    the current instant, `due_at` is set to that instant plus 14 days,
    `fill_rate_floor_pct` is snapshotted from the vendor's own `fill_rate_floor_pct` so
    that later changes to the vendor's floor do not retroactively move the bar for this
    buy, the vendor's `version` is incremented by one, every covered line in
    `VENDOR_CONFIRMED` moves to `PURCHASE_ORDER_ISSUED` with its order's
    `cancellation_waived` set to true, and the event's `units_po_committed_total` is
    recomputed."

    PRD §3.9: "The listing is repaired to that computed value on drift, and the
    event's `units_ordered_total` is then the sum of its listings' `units_ordered`
    while `units_po_committed_total` is the summed `quantity_ordered` across the
    event's buys that are not `CANCELLED`."

    Design: Difficulty/compensating_invariant/buy_cancellation_restores_listing_units_ordered_exactly
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=300, vendor_unit_cost_cents=180,
        allocation_units=10, ship_time_quote_days=14, vendor_sku="NW-CONS-1")

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    line = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": 4}, cust_h))
    get_success_data(api_client.submit_order(order["id"], cust_h))
    vendor_h = {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
                "Content-Type": "application/json"}

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": 4}, PLANNER))
    # The vendor confirms while the buy is still DRAFT: the effective floor has
    # ramped to zero on an unissued buy, so the confirmation is admitted.
    get_success_data(api_client.confirm_line(line["id"], {"confirm_units": 4}, vendor_h))

    before = validate_success(api.get_event(event["id"], ANY), 200)
    assert before["units_ordered_total"] == 4
    assert before["units_po_committed_total"] == 0

    validate_success(api.issue_purchase_order(
        po["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER), 200)

    after_issue = validate_success(api.get_event(event["id"], ANY), 200)
    assert after_issue["units_po_committed_total"] == 4, (
        "the issued buy's ordered units count as committed")
    assert after_issue["units_ordered_total"] == 4, (
        "issuing a buy does not move the demand figure")

    order_after = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_after["cancellation_waived"] is True, (
        "the covered line reached PURCHASE_ORDER_ISSUED, which waives cancellation")


def test_cancelling_the_buy_restores_the_committed_quantity_exactly(
        api, merchandiser_headers):
    """PRD §3.6: "The buy moves to `CANCELLED` with `closed_at` stamped, every
    `POLine` moves to `OPEN` with `quantity_ordered` and `quantity_confirmed` reset to
    0, every covered line in `PURCHASE_ORDER_ISSUED` reverts to `VENDOR_CONFIRMED`
    with the owning order's `cancellation_waived` recomputed, and the event's
    `units_po_committed_total` is recomputed."

    PRD §3.9: "`CANCELLED` lines are excluded because a cancelled line returns its
    units to the listing."

    Design: Difficulty/compensating_invariant/buy_cancellation_restores_listing_units_ordered_exactly
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=300, vendor_unit_cost_cents=180,
        allocation_units=10, ship_time_quote_days=14, vendor_sku="NW-CONS-1")

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    line = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": 4}, cust_h))
    get_success_data(api_client.submit_order(order["id"], cust_h))
    vendor_h = {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
                "Content-Type": "application/json"}

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": 4}, PLANNER))
    validate_success(api.issue_purchase_order(
        po["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER), 200)
    get_success_data(api_client.confirm_line(line["id"], {"confirm_units": 4}, vendor_h))

    listing_after_submit = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert listing_after_submit["units_ordered"] == 4

    validate_success(api.cancel_purchase_order(
        po["id"], {"reason_code": "VENDOR_CAPACITY_LOST"}, PLANNER), 200)

    after_cancel = validate_success(api.get_event(event["id"], ANY), 200)
    assert after_cancel["units_po_committed_total"] == 0, (
        "the cancellation restores the committed quantity to its pre-issue value")
    assert after_cancel["units_ordered_total"] == 4, (
        "the conserved quantity is demand, which the buy never moved")

    listing_now = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert listing_now["units_ordered"] == 4, (
        "the buy never moved the listing counter, so cancelling it cannot either")

    line_now = validate_success(api.get_confirmation(line["id"], ANY), 200)
    assert line_now["confirmation_status"] == "VENDOR_CONFIRMED", (
        "the compensating hop restored the line rather than cancelling it")

    order_now = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_now["cancellation_waived"] is False, (
        "no line has reached PURCHASE_ORDER_ISSUED any more")


def _short_shipped_order(unit_price_cents=300, quantity=5, confirm_units=3,
                         allocation_units=10):
    """An order whose single line was bought, captured and then closed short.

    Returns (vendor, event, listing, customer, order, line).
    """
    api_client.set_clock("2026-09-01T00:00:00Z", MERCH)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=unit_price_cents, vendor_unit_cost_cents=180,
        allocation_units=allocation_units, ship_time_quote_days=14,
        vendor_sku="NW-CONS-2")

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    line = get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": quantity}, cust_h))
    get_success_data(api_client.submit_order(order["id"], cust_h))

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": quantity},
        PLANNER))
    get_success_data(api_client.issue_purchase_order(
        po["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))
    get_success_data(api_client.confirm_line(
        line["id"], {"confirm_units": confirm_units},
        {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
         "Content-Type": "application/json"}))
    get_success_data(api_client.capture_order(order["id"], PLANNER))
    get_success_data(api_client.close_short_purchase_order(
        po["id"], {"force_close": True}, PLANNER))
    return vendor, event, listing, customer, order, line


def test_a_refund_moves_the_owed_balance_by_exactly_the_missing_units_value(
        api, merchandiser_headers):
    """PRD §3.6: "Each refund writes one `CreditLedger` row per refunded line with
    `source_kind` `OVERSELL` or `SHORT_SHIP`, adds the refunded amount to the
    customer's `refund_balance_cents`, and recomputes `refund_due_cents` in the
    selected `variant`."

    Design: Difficulty/compensating_invariant/refund_payout_restores_customer_refund_balance_exactly
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, customer, order, line = _short_shipped_order()

    line_now = validate_success(api.get_confirmation(line["id"], ANY), 200)
    assert line_now["short_shipped_units"] == 2, (
        f"5 ordered minus 3 confirmed is 2, got {line_now['short_shipped_units']}")

    before = validate_success(api.get_customer(customer["id"], ANY), 200)
    assert before["refund_balance_cents"] == 0

    validate_success(api.refund_order(
        order["id"], {"write_off_full_line": False}, PLANNER), 200)

    after = validate_success(api.get_customer(customer["id"], ANY), 200)
    assert after["refund_balance_cents"] == 600, (
        f"two missing units at 300 cents each is 600, got "
        f"{after['refund_balance_cents']}")


def test_a_payout_returns_the_balance_to_its_pre_refund_value(
        api, merchandiser_headers):
    """PRD §3.8: "A manual payout is the mirror image: a `CustomerService` operator
    records the cash payout of an owed balance by supplying an `amount_cents` and an
    `idempotency_key`, which writes a ledger row with a negative amount and
    `source_kind` `MANUAL_ADJUSTMENT` labelled as a payout, and decrements the
    customer's `refund_balance_cents` without ever taking it below zero."

    PRD §2.8: "Callers can supply an `idempotency_key` on issuance requests: repeating
    a request with the same key is a no-op that returns the original row rather than
    writing a second one."

    Design: Difficulty/compensating_invariant/refund_payout_restores_customer_refund_balance_exactly
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, event, listing, customer, order, line = _short_shipped_order()

    validate_success(api.refund_order(
        order["id"], {"write_off_full_line": False}, PLANNER), 200)
    mid = validate_success(api.get_customer(customer["id"], ANY), 200)
    assert mid["refund_balance_cents"] == 600

    payout = validate_success(api.create_payout(
        customer["id"],
        {"amount_cents": 600, "idempotency_key": "payout-cons-1"}, CS), 201)
    assert payout["amount_cents"] == -600, "a payout is a negative ledger row"

    after = validate_success(api.get_customer(customer["id"], ANY), 200)
    assert after["refund_balance_cents"] == 0, (
        "the compensation restores the balance to its pre-refund value")

    # Replaying the same key must not pay twice.
    replay = api.create_payout(
        customer["id"],
        {"amount_cents": 600, "idempotency_key": "payout-cons-1"}, CS)
    assert 200 <= replay.status_code < 300, "a replayed payout is not an error"
    replay_body = replay.json()["data"]
    assert replay_body["id"] == payout["id"], (
        "the same idempotency_key returns the original row")

    steady = validate_success(api.get_customer(customer["id"], ANY), 200)
    assert steady["refund_balance_cents"] == 0, (
        "the compensation cannot be applied twice")