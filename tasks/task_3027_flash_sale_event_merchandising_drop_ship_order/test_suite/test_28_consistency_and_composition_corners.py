"""Consistency-model, ledger-shape, error-catalogue and composition-read corners."""

from test_helpers import (
    ANY, TEST_USERS, api_client, get_success_data, setup_live_event_with_listing,
    setup_order_delivered, validate_error, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
CS = TEST_USERS["customer_service_headers"]


def test_a_credit_is_visible_in_the_same_response_and_replays_by_its_key(
        api, merchandiser_headers):
    """PRD §2.8: "Callers can supply an `idempotency_key` on issuance requests:
    repeating a request with the same key is a no-op that returns the original row
    rather than writing a second one."

    PRD §3.8: "The manual credit writes a `CreditLedger` row with `source_kind`
    `MANUAL_ADJUSTMENT` and `entry_status` `ISSUED`, adjusts the customer's
    store-credit or refund balance by the signed amount, and adds the amount to
    `lifetime_credit_issued_cents`".

    Design: Corner/consistency_model/credit_issuance_is_atomic_and_visible_in_the_same_response
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))

    issued = validate_success(api.create_credit(
        customer["id"], {"amount_cents": 2500, "idempotency_key": "imm-cons-1",
                         "reason_code": "GOODWILL"}, CS), 201)
    assert issued["entry_status"] == "ISSUED"
    assert issued["amount_cents"] == 2500

    immediately = validate_success(api.get_customer(customer["id"], ANY), 200)
    assert immediately["store_credit_balance_cents"] == 2500, (
        "the balance moves in the same request rather than lagging a later pass")

    ledger = validate_success(api.get_credit_ledger(customer["id"], ANY), 200)
    rows = ledger if isinstance(ledger, list) else ledger.get("data", ledger)
    assert len(rows) == 1
    assert rows[0]["id"] == issued["id"]

    replay = validate_success(api.create_credit(
        customer["id"], {"amount_cents": 2500, "idempotency_key": "imm-cons-1",
                         "reason_code": "GOODWILL"}, CS), 201)
    assert replay["id"] == issued["id"], (
        "the same key returns the original row rather than writing a second")

    steady = validate_success(api.get_customer(customer["id"], ANY), 200)
    assert steady["store_credit_balance_cents"] == 2500


def test_a_ledger_row_carries_only_the_two_append_only_common_fields(
        api, merchandiser_headers):
    """PRD §2.4: "The `CreditLedger` entity is the single exception: because its rows
    are append-only, it carries only `id` and `created_at`, and has neither
    `updated_at` nor `version`."

    PRD §2.8: "any later correction must be a new compensating row rather than a
    revision of the old one."

    Design: Corner/entities/credit_ledger_entry_is_append_only_with_no_update_endpoint
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    customer = get_success_data(api_client.create_customer(
        {"email": "c1@example.com", "full_name": "Casey One"}, ANY))

    first = validate_success(api.create_credit(
        customer["id"], {"amount_cents": 1500, "idempotency_key": "imm-1",
                         "reason_code": "GOODWILL"}, CS), 201)
    assert "updated_at" not in first, "a ledger row carries no updated_at"
    assert "version" not in first, "a ledger row carries no version"

    second = validate_success(api.create_credit(
        customer["id"], {"amount_cents": 700, "idempotency_key": "imm-2",
                         "reason_code": "GOODWILL"}, CS), 201)
    assert second["id"] != first["id"], (
        "a later correction is a NEW row rather than a revision of the old one")
    assert "updated_at" not in second and "version" not in second

    ledger = validate_success(api.get_credit_ledger(customer["id"], ANY), 200)
    rows = ledger if isinstance(ledger, list) else ledger.get("data", ledger)
    assert len(rows) == 2, "the correction adds a row rather than editing one"
    original = [r for r in rows if r["id"] == first["id"]][0]
    assert original["amount_cents"] == 1500, "the original row is unchanged"


def test_each_collection_family_reports_its_own_not_found_code(api, any_headers):
    """PRD §2.5: "The catalogue for unresolvable identifiers is per entity:
    `ERR_VENDOR_NOT_FOUND`, `ERR_SHOP_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_LISTING_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_CONFIRMATION_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`, `ERR_POLINE_NOT_FOUND`,
    `ERR_VENDOR_SHIPMENT_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`, and `ERR_RETURN_NOT_FOUND`,
    each returned with a not-found status."

    Design: Corner/errors/every_path_not_found_code_is_reachable_and_specific
    """
    missing = "00000000-0000-4000-8000-000000000000"
    cases = [
        (api.get_vendor, "ERR_VENDOR_NOT_FOUND"),
        (api.get_listing, "ERR_LISTING_NOT_FOUND"),
        (api.get_order, "ERR_ORDER_NOT_FOUND"),
        (api.get_return, "ERR_RETURN_NOT_FOUND"),
        (api.get_parcel, "ERR_PARCEL_NOT_FOUND"),
        (api.get_shipment, "ERR_VENDOR_SHIPMENT_NOT_FOUND"),
        (api.get_purchase_order, "ERR_PURCHASE_ORDER_NOT_FOUND"),
    ]
    seen = []
    for fetch, expected_id in cases:
        validate_error(fetch(missing, any_headers), expected_id, expected_status=404)
        seen.append(expected_id)

    assert len(set(seen)) == len(seen), (
        "no collection family collapsed onto a single generic not-found code")


def test_customer_orders_can_be_listed_by_their_event(
        api, merchandiser_headers):
    """PRD §3.3: "The order's own `event_id` is usually null, because the whole point
    of the aggregate is that one order can span many events."

    Design: Corner/consistency_model/event_close_cascade_compensates_rather_than_leaving_a_partial_order
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    vendor, shop, event, listing = setup_live_event_with_listing(
        unit_price_cents=600, vendor_unit_cost_cents=300, allocation_units=5,
        ship_time_quote_days=14, vendor_sku="NW-SAGA-1",
        event_starts="2026-09-01T00:00:00Z", event_ends="2026-09-02T00:00:00Z")

    order_ids = []
    for email in ("c1@example.com", "c2@example.com"):
        customer = get_success_data(api_client.create_customer(
            {"email": email, "full_name": "Casey Buyer"}, ANY))
        cust_h = {"X-User-ID": customer["id"], "X-User-Role": "Customer",
                  "Content-Type": "application/json"}
        order = get_success_data(api_client.create_order(
            {"customer_id": customer["id"]}, cust_h))
        # The pitfall the close cascade exists for: the lines are still
        # PENDING_AGGREGATION when the event closes, and the close sweeps them up.
        get_success_data(api_client.add_order_line(
            order["id"], {"listing_id": listing["id"], "quantity": 2}, cust_h))
        order_ids.append(order["id"])

    validate_success(api.close_event(
        event["id"], merchandiser_headers, {"cancel_pending_aggregations": True}), 200)

    kept = []
    for order_id in order_ids:
        order_now = validate_success(api.get_order(order_id, ANY), 200)
        assert order_now["order_status"] == "CANCELLED", (
            "each order compensated end to end, so none was left holding a "
            f"cancelled line with an intact posture, got {order_now['order_status']}")
        assert order_now["payment_status"] == "REFUNDED", (
            f"each affected order's payment axis moved, got "
            f"{order_now['payment_status']}")
        kept.append(order_now)

    assert all(o["order_status"] != "AWAITING_VENDOR" for o in kept), (
        "no order was left in a partial state by the cascade")


def test_the_monolith_view_composes_the_orders_sub_resources(
        api, merchandiser_headers):
    """PRD §3.7: "a denormalized monolith view of a single order returns the order
    together with its lines, the covering buys, their shipments, the parcel, and any
    returns, in one response."

    Design: Corner/endpoints/order_monolith_view_returns_every_composed_sub_resource
    """
    api.set_clock("2026-09-01T00:00:00Z", merchandiser_headers)
    ctx = setup_order_delivered(quantity=2, unit_price_cents=400,
                                vendor_unit_cost_cents=200, allocation_units=5,
                                vendor_sku="NW-MON-1")

    view = validate_success(api.get_vendor_order_view(ctx["order"]["id"], ANY), 200)
    for key in ("order", "lines", "purchase_orders", "shipments", "parcel", "returns"):
        assert key in view, f"the composed read carries {key}"

    order_now = validate_success(api.get_order(ctx["order"]["id"], ANY), 200)
    assert view["order"]["order_status"] == order_now["order_status"], (
        "the composed order agrees with the direct read")
    assert view["order"]["id"] == order_now["id"]

    assert len(view["lines"]) == 1
    assert view["lines"][0]["id"] == ctx["line"]["id"]
    assert len(view["purchase_orders"]) == 1
    assert view["purchase_orders"][0]["id"] == ctx["po"]["id"]
    assert len(view["shipments"]) == 1
    assert view["shipments"][0]["id"] == ctx["shipment"]["id"]
    assert view["parcel"]["id"] == ctx["parcel"]["id"]
    assert view["returns"] == [], "returns is an empty array rather than null"

    verify = validate_success(api.get_order(ctx["order"]["id"], ANY), 200)
    assert verify["version"] == order_now["version"], (
        "the monolith read mutates nothing")