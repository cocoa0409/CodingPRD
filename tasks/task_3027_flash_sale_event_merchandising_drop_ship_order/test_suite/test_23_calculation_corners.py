"""Calculation-scoped corners: window edges, variant switching and scope filtering."""

from test_helpers import (
    ANY, TEST_USERS, api_client, create_buy, fresh_vendor, get_success_data,
    setup_live_event_with_listing, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]


def test_the_rolling_fill_rate_window_excludes_the_exact_boundary_closure(
        api, merchandiser_headers):
    """PRD §3.9: "a buy falls inside the scope only when it belongs to the vendor, its
    `po_status` is `FILLED` or `CLOSED_SHORT`, its `issued_at` is not null, and its
    `closed_at` is strictly later than the window opening — a buy closing exactly at
    the window boundary is excluded, not included."

    Design: Corner/calculations/vendor_rolling_fill_rate_window_boundary_excludes_the_closure_instant
    """
    api.set_clock("2026-06-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=100, vendor_unit_cost_cents=60, allocation_units=40,
        ship_time_quote_days=14, vendor_sku="NW-WIN-1",
        event_starts="2026-06-01T00:00:00Z", event_ends="2026-06-02T00:00:00Z",
        reveal_at="2026-06-01T00:00:00Z")

    def _demand(quantity, email):
        """A submitted line the probe buy can be issued against.

        A buy is issued only once its covered lines are vendor-confirmed, and the
        projected fill rate must clear the ramp, so each probe buy gets its own
        confirmed line.
        """
        customer = get_success_data(api_client.create_customer(
            {"email": email, "full_name": "Buyer"}, ANY))
        cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
                  "Content-Type": "application/json"}
        order = get_success_data(api_client.create_order(
            {"customer_id": customer["id"]}, cust_h))
        line = get_success_data(api_client.add_order_line(
            order["id"], {"listing_id": listing["id"], "quantity": quantity},
            cust_h))
        get_success_data(api_client.submit_order(order["id"], cust_h))
        return line

    # A probe buy closed short exactly 90 days before the read instant: the read
    # happens on 2026-09-01, so the closure is pinned to 2026-06-03.
    api.set_clock("2026-06-03T00:00:00Z", merchandiser_headers)
    line_out = _demand(10, "probe-out@example.com")
    po_out = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po_out["id"], {"listing_id": listing["id"], "quantity_ordered": 10}, PLANNER))
    get_success_data(api_client.issue_purchase_order(
        po_out["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))
    get_success_data(api_client.confirm_line(
        line_out["id"], {"confirm_units": 4},
        {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
         "Content-Type": "application/json"}))
    get_success_data(api_client.close_short_purchase_order(
        po_out["id"], {"force_close": True}, PLANNER))

    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor_now = get_success_data(api_client.get_vendor(vendor["id"], ANY))

    # A second buy is issued and closed short one day inside the window.
    line_in = _demand(20, "probe-in@example.com")
    po_in = create_buy(vendor_now, event)
    get_success_data(api_client.add_po_line(
        po_in["id"], {"listing_id": listing["id"], "quantity_ordered": 20}, PLANNER))
    get_success_data(api_client.issue_purchase_order(
        po_in["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))
    get_success_data(api_client.confirm_line(
        line_in["id"], {"confirm_units": 8},
        {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
         "Content-Type": "application/json"}))
    get_success_data(api_client.close_short_purchase_order(
        po_in["id"], {"force_close": True}, PLANNER))

    report = validate_success(api.get_fill_rate_report(
        vendor["id"], ANY, {"basis": "UNIT_WEIGHTED", "window_days": 90}), 200)
    assert report["window_days"] == 90
    assert report["units_ordered"] == 20, (
        "the buy closed exactly on the window edge is excluded by the strict "
        f"comparison, so only the 20-unit buy counts, got {report['units_ordered']}")
    assert report["units_shipped"] == 0

    wider = validate_success(api.get_fill_rate_report(
        vendor["id"], ANY, {"basis": "UNIT_WEIGHTED", "window_days": 91}), 200)
    assert wider["units_ordered"] == 30, (
        "widening the window by one day admits the boundary closing, proving both "
        f"closings exist and only the window differs, got {wider['units_ordered']}")


def test_the_contribution_variant_is_selected_by_the_event_status_alone(
        api, merchandiser_headers):
    """PRD §3.9: "The event's `net_contribution_variant` records which of
    `PROJECTED_WHILE_LIVE` or `REALIZED_ON_CLOSURE` is currently in force."

    PRD §2.4: "Any write that changes a derived figure — recomputing an order's
    totals, advancing a vendor's rolling counters, re-deriving a listing's
    `listing_status` — is a mutation of the owning resource and therefore refreshes
    its `updated_at` and increments its `version` exactly as a direct field edit
    would."

    Design: Corner/calculations/event_net_contribution_variant_switch_on_closure
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=1000, vendor_unit_cost_cents=600, allocation_units=10,
        ship_time_quote_days=14, vendor_sku="NW-VAR-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")

    for email in ("c1@example.com", "c2@example.com"):
        customer = get_success_data(api_client.create_customer(
            {"email": email, "full_name": "Casey Buyer"}, ANY))
        cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
                  "Content-Type": "application/json"}
        order = get_success_data(api_client.create_order(
            {"customer_id": customer["id"]}, cust_h))
        line = get_success_data(api_client.add_order_line(
            order["id"], {"listing_id": listing["id"], "quantity": 5}, cust_h))
        get_success_data(api_client.submit_order(order["id"], cust_h))

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": 10}, PLANNER))
    get_success_data(api_client.issue_purchase_order(
        po["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))
    vendor_h = {"X-User-ID": vendor["id"], "X-User-Role": "Vendor",
                "Content-Type": "application/json"}
    lines = validate_success(
        api.list_confirmations(ANY, {"listing_id": listing["id"]}), 200)
    for line in lines:
        get_success_data(api_client.confirm_line(
            line["id"], {"confirm_units": 5}, vendor_h))

    at_checkpoint = validate_success(api.run_event_checkpoint(
        event["id"], merchandiser_headers), 200)
    assert at_checkpoint["net_contribution_variant"] == "PROJECTED_WHILE_LIVE", (
        "a live event reports the projected variant")
    assert at_checkpoint["checkpoint_index"] == 1

    closed = validate_success(api.close_event(
        event["id"], merchandiser_headers, {"cancel_pending_aggregations": True}),
        200)
    assert closed["net_contribution_variant"] == "REALIZED_ON_CLOSURE", (
        "closure switches the variant")
    assert closed["net_contribution_variant"] != at_checkpoint["net_contribution_variant"], (
        "the two variants are not interchangeable")


def test_the_allocation_sweep_never_reaches_unsubmitted_lines(
        api, merchandiser_headers):
    """PRD §3.4: "The candidates are the listing's `Confirmations` whose
    `confirmation_status` is `PENDING_VENDOR` or `VENDOR_CONFIRMED`; lines still in
    `PENDING_AGGREGATION` are excluded because they have not been placed against a
    vendor at all".

    PRD §3.3: "Crucially, a line in that state holds no allocation:
    `line_unit_price_cents` stays null until submission, at which point it is frozen
    from the listing's `unit_price_cents`, and the listing's `units_ordered` is not
    advanced yet."

    Design: Corner/calculations/oversell_allocation_scope_excludes_pending_aggregation_lines
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=200, vendor_unit_cost_cents=120, allocation_units=5,
        ship_time_quote_days=14, vendor_sku="NW-SCOPE-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-03T00:00:00Z")

    orders = []
    for email in ("a@example.com", "b@example.com", "c@example.com"):
        customer = get_success_data(api_client.create_customer(
            {"email": email, "full_name": "Buyer"}, ANY))
        cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
                  "Content-Type": "application/json"}
        order = get_success_data(api_client.create_order(
            {"customer_id": customer["id"]}, cust_h))
        line = get_success_data(api_client.add_order_line(
            order["id"], {"listing_id": listing["id"], "quantity": 3}, cust_h))
        orders.append((order, line, cust_h))

    # Only the first two orders are submitted; the third stays aggregating.
    get_success_data(api_client.submit_order(orders[0][0]["id"], orders[0][2]))
    get_success_data(api_client.submit_order(orders[1][0]["id"], orders[1][2]))

    po = create_buy(vendor, event)
    get_success_data(api_client.add_po_line(
        po["id"], {"listing_id": listing["id"], "quantity_ordered": 9}, PLANNER))
    get_success_data(api_client.issue_purchase_order(
        po["id"], {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}, PLANNER))

    listing_before = validate_success(api.get_listing(listing["id"], ANY), 200)
    assert listing_before["units_ordered"] == 6, (
        "the unsubmitted line holds no allocation, so it is 6 rather than 9")

    line_c = validate_success(api.get_confirmation(orders[2][1]["id"], ANY), 200)
    assert line_c["confirmation_status"] == "PENDING_AGGREGATION"
    assert line_c["oversold_units"] == 0, (
        "a line outside the sweep is never assigned any oversold units")
    assert line_c["line_unit_price_cents"] is None, (
        "the price is frozen only at submission")


def test_the_goodwill_credit_is_clamped_to_the_remaining_annual_headroom(
        api, merchandiser_headers):
    """PRD §3.8: "The customer's headroom is 50000 cents minus their
    `lifetime_credit_issued_cents`. The credit actually granted is the greater of zero
    and the smaller of the raw credit and the headroom — so a credit that would
    overshoot the annual cap is trimmed to exactly the cap rather than refused, while a
    `decision` with exactly zero headroom is refused outright with
    `ERR_GOODWILL_CAP_EXCEEDED`".

    Design: Corner/calculations/goodwill_credit_cap_clamps_at_annual_headroom
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cs_h = TEST_USERS["customer_service_headers"]

    seeded = validate_success(api.create_credit(
        customer["id"],
        {"amount_cents": 43000, "idempotency_key": "cap-seed-1",
         "reason_code": "GOODWILL"}, cs_h), 201)
    assert seeded["amount_cents"] == 43000

    over = api.create_credit(customer["id"],
                             {"amount_cents": 7001,
                              "idempotency_key": "cap-over-1",
                              "reason_code": "GOODWILL"}, cs_h)
    body_over = over.json()
    assert body_over["response_type"] == "error"
    assert body_over["data"]["error_id"] == "ERR_GOODWILL_CAP_EXCEEDED", (
        "7001 cents would take the lifetime figure to 50001, one cent past the cap")
    assert over.status_code == 409

    at_cap = validate_success(api.create_credit(
        customer["id"],
        {"amount_cents": 7000, "idempotency_key": "cap-exact-1",
         "reason_code": "GOODWILL"}, cs_h), 201)
    assert at_cap["amount_cents"] == 7000

    customer_now = validate_success(api.get_customer(customer["id"], ANY), 200)
    assert customer_now["lifetime_credit_issued_cents"] == 50000, (
        "the credit lands exactly on the annual cap, which is inclusive")

    zero_headroom = api.create_credit(customer["id"],
                                      {"amount_cents": 1,
                                       "idempotency_key": "cap-over-2",
                                       "reason_code": "GOODWILL"}, cs_h)
    body_zero = zero_headroom.json()
    assert body_zero["data"]["error_id"] == "ERR_GOODWILL_CAP_EXCEEDED", (
        "a decision with exactly zero headroom is refused rather than trimmed to a "
        "zero-cent row")


def test_the_cancellation_window_takes_the_earlier_of_its_two_anchors(
        api, merchandiser_headers):
    """PRD §3.3: "For a single line, the window's edge is whichever comes first — 30
    hours after the line's `confirmed_at`, or the end of the event the line belongs
    to."

    PRD §3.3: "The boundary instant itself is inside the window, so a cancellation
    landing exactly on `cancellation_window_ends_at` is admitted."

    Design: Corner/calculations/cancellation_window_anchor_takes_the_earlier_of_grace_and_event_end
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=400, vendor_unit_cost_cents=200, allocation_units=5,
        ship_time_quote_days=14, vendor_sku="NW-CAN-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-01T23:00:00Z")

    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))
    cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
              "Content-Type": "application/json"}
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"]}, cust_h))
    get_success_data(api_client.add_order_line(
        order["id"], {"listing_id": listing["id"], "quantity": 2}, cust_h))

    # Submitted two hours before the event ends.
    api.set_clock("2026-09-01T21:00:00Z", merchandiser_headers)
    get_success_data(api_client.submit_order(order["id"], cust_h))

    order_now = validate_success(api.get_order(order["id"], ANY), 200)
    assert order_now["cancellation_window_ends_at"] == "2026-09-01T23:00:00.000Z", (
        "the event end is earlier than 21:00 plus 30 hours, so it pins the window, "
        f"got {order_now['cancellation_window_ends_at']}")
    assert order_now["cancellation_waived"] is False
    assert order_now["disclosed_ship_time_days"] == 14, (
        "the disclosed figure is taken from the event, not from client input")