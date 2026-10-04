"""Orders: lifecycle transition guards, line validation, the transit sweep,
and the allocate/cancel stock-conservation invariant.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    CLOCK_START_UTC,
    SUPPLY_OPS,
    ApiErrorId,
    api_client,
    assert_stock_invariant,
    create_account,
    create_allocated_order,
    create_catalog_item,
    create_order,
    create_shipped_order,
    get_catalog_item_by_sku,
    get_order,
    make_lab_procurement_headers,
    order_line,
    order_payload,
    plus_days,
    same_instant,
    set_clock,
    submit_order,
    cancel_order,
    validate_error,
)


def test_ship_draft_order_returns_invalid_state(api):
    """PRD section 3.6: "Shipping requires `ALLOCATED` status
    (`ERR_INVALID_STATE` otherwise), stamps `shipped_at` from the logical
    clock".

    Design: Corner/state_machines/ship_draft_order_returns_invalid_state
    """
    account = create_account(name="Ship Gate Lab", segment="INDUSTRIAL")
    item = create_catalog_item(base_price_cents=100, stock_on_hand=10)
    order = create_order(account, [order_line(item["sku"], 1)])

    response = api_client.ship_order(order["id"], headers=SUPPLY_OPS)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    fresh = get_order(order)
    assert fresh["status"] == "DRAFT", "the order must not move"


def test_cancel_shipped_order_returns_not_cancellable(api):
    """PRD section 3.6: "Cancelling from `SHIPPED`, `DELIVERED`, or an
    already-`CANCELLED` state is rejected with
    `ERR_ORDER_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_shipped_order_returns_not_cancellable
    """
    account = create_account(name="Cancel Gate Lab", segment="INDUSTRIAL")
    item = create_catalog_item(base_price_cents=100, stock_on_hand=10)
    shipped = create_shipped_order(account, [order_line(item["sku"], 1)])

    response = api_client.cancel_order(
        shipped["id"], headers=make_lab_procurement_headers(account["id"])
    )
    validate_error(response, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)
    fresh = get_order(shipped)
    assert fresh["status"] == "SHIPPED", "the shipment is unaffected"


def test_order_empty_lines_invalid_request(api):
    """PRD section 3.6: "an empty or malformed `lines` array is
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/order_empty_lines_invalid_request
    """
    account = create_account(name="Empty Lines Lab", segment="ACADEMIC")
    response = api_client.create_order(
        order_payload(account["id"], lines=[]),
        headers=make_lab_procurement_headers(account["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


def test_order_zero_quantity_rejected(api):
    """PRD section 3.6: "Each `quantity` must be a positive integer, failing
    `ERR_INVALID_QUANTITY` otherwise".

    Design: Corner/validations/order_zero_quantity_rejected
    """
    account = create_account(name="Qty Lab", segment="ACADEMIC")
    item = create_catalog_item(base_price_cents=100, stock_on_hand=10)
    response = api_client.create_order(
        order_payload(account["id"], lines=[order_line(item["sku"], 0)]),
        headers=make_lab_procurement_headers(account["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_QUANTITY)


def test_order_unknown_sku_not_found(api):
    """PRD section 3.6: "each `sku` must exist in the catalog, failing
    `ERR_CATALOG_ITEM_NOT_FOUND` otherwise".

    Design: Corner/validations/order_unknown_sku_not_found
    """
    account = create_account(name="Sku Lab", segment="ACADEMIC")
    response = api_client.create_order(
        order_payload(account["id"], lines=[order_line("NOPE-1", 1)]),
        headers=make_lab_procurement_headers(account["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CATALOG_ITEM_NOT_FOUND)


def test_transit_delivery_after_three_days(api):
    """PRD section 3.8: "An order whose transit window has elapsed moves to
    `DELIVERED`: its `delivered_at` is set to `shipped_at` plus the transit
    days of its `shipping_class`, which are 3 days for `STANDARD`" and "An
    order is swept once the logical clock has reached `shipped_at` plus its
    transit days; reading an order never advances it."

    Design: Corner/calculations/transit_delivery_after_three_days
    """
    account = create_account(name="Transit Lab", segment="INDUSTRIAL")
    item = create_catalog_item(base_price_cents=100, stock_on_hand=10)
    shipped = create_shipped_order(account, [order_line(item["sku"], 1)])
    assert same_instant(shipped["shipped_at"], CLOCK_START_UTC)

    set_clock(plus_days(CLOCK_START_UTC, 2))
    early = get_order(shipped)
    assert early["status"] == "SHIPPED", "at +2 days the transit window is still open"

    set_clock(plus_days(CLOCK_START_UTC, 3))
    delivered = get_order(shipped)
    assert delivered["status"] == "DELIVERED", (
        "the sweep delivers once the clock reaches shipped_at + 3 days"
    )
    assert same_instant(delivered["delivered_at"], plus_days(CLOCK_START_UTC, 3))


def test_allocate_reserves_stock_probe(api):
    """PRD section 3.6: "the order becomes `ALLOCATED`, and each line adds its
    `quantity` to its catalog item's `reserved_quantity` to hold the stock."
    and "`available_stock`, which is `stock_on_hand` minus
    `reserved_quantity` and never goes negative."

    Design: Difficulty/compensating_invariant/stock_allocate_cancel_conserves_available
    """
    account = create_account(name="Stock Lab", segment="INDUSTRIAL")
    item = create_catalog_item(base_price_cents=500, stock_on_hand=100)
    allocated = create_allocated_order(account, [order_line(item["sku"], 30)])
    assert allocated["status"] == "ALLOCATED"

    probe = get_catalog_item_by_sku(item["sku"])
    assert probe["stock_on_hand"] == 100, "allocation reserves; it does not ship"
    assert probe["reserved_quantity"] == 30
    assert probe["available_stock"] == 70
    assert_stock_invariant(probe)


def test_allocate_then_cancel_conserves_available_stock(api):
    """PRD section 3.6: "cancelling an `ALLOCATED` order additionally releases
    its reservations, subtracting each line's quantity from its item's
    `reserved_quantity`."  The allocate-then-cancel pair restores
    available_stock exactly, leaving zero drift.

    Design: Difficulty/compensating_invariant/stock_allocate_cancel_conserves_available
    """
    account = create_account(name="Stock Lab", segment="INDUSTRIAL")
    item = create_catalog_item(base_price_cents=500, stock_on_hand=100)
    allocated = create_allocated_order(account, [order_line(item["sku"], 30)])
    cancelled = cancel_order(allocated, account)
    assert cancelled["status"] == "CANCELLED"

    probe = get_catalog_item_by_sku(item["sku"])
    assert probe["stock_on_hand"] == 100
    assert probe["reserved_quantity"] == 0, "the release restores reservations"
    assert probe["available_stock"] == 100
    assert_stock_invariant(probe)

