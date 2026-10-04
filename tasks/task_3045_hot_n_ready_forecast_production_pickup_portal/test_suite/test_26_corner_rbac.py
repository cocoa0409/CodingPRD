"""Corner coverage of the role matrix: denials, ownership, and missing headers."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    factories,
    headers_without_identity,
    make_crew_headers,
    make_customer_headers,
    make_manager_headers,
    validate_error,
    validate_paginated,
)


def test_crew_member_cannot_create_products(client):
    """Product creation is StoreManager-exclusive; a crew member is denied and
    no row is created.

    "Each operation is restricted to a designated set of roles (enumerated per
    endpoint in §4); an authenticated caller whose role is not permitted for the
    attempted operation is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/crew_member_cannot_create_products
    """
    resp = client.create_product(factories.product_payload(), make_crew_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    rows, meta = validate_paginated(client.list_products(make_manager_headers()))
    assert meta["total_count"] == 0


def test_customer_cannot_discard_hold_unit(client):
    """Manual discard is ShiftLead-exclusive; a Customer caller is denied and
    the unit stays HOLDING.

    "And it is **discarded**, moving from `HOLDING` to the terminal `DISCARDED`
    state, either automatically when the expiry sweep finds the clock at or past
    `hold_expires_at`, or manually by a `ShiftLead`."
    "an authenticated caller whose role is not permitted for the attempted
    operation is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_discard_hold_unit
    """
    bundle = fixtures.open_day_with_stock(
        client, "2026-11-06", active_at="10:35:00Z", run_quantity=1, batch_size=5
    )
    units = fixtures.holding_units(client, bundle.run["id"])

    resp = client.discard_hold_unit(
        units[0]["id"], {"reason": "DAMAGED"}, make_customer_headers("cust-rbac")
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    stored = fixtures.get_success_data(
        client.get_hold_unit(units[0]["id"], make_crew_headers())
    )
    assert stored["status"] == "HOLDING"


def test_customer_cannot_touch_other_customers_order(client):
    """Ownership: a customer paying another customer's order is denied even
    though pay is a Customer operation.

    "When `X-User-Role` is `Customer`, `X-User-ID` is an opaque customer handle
    with one additional ownership rule: on order-scoped calls it must equal the
    `customer_id` recorded on the target `Order` at creation. A portal customer
    attempting to pay, claim, cancel, or otherwise act on an order whose
    `customer_id` does not match the presented `X-User-ID` is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_touch_other_customers_order
    """
    day = fixtures.open_store_day_with_active_daypart(
        client, "2026-11-07", "2026-11-07T11:00:00Z"
    )
    product = fixtures.create_product(client)
    order = fixtures.create_order(
        client,
        day.store_day["id"],
        day.daypart["id"],
        "cust-Y",
        "PORTAL_STANDARD",
        [factories.order_line(product["id"], quantity=1, customized=False)],
    )

    resp = client.pay_order(order["id"], make_customer_headers("cust-X"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    stored = fixtures.read_order(client, order["id"], customer_id="cust-Y")
    assert stored["payment_status"] == "UNPAID"


def test_missing_headers_rejected(client):
    """No identity headers at all fails before any role check.

    "A request in which either header is missing or invalid is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
    "First the authentication context is checked (missing or invalid headers
    yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization
    and customer ownership (`ERR_UNAUTHORIZED`)."

    Design: Corner/rbac/missing_headers_rejected
    """
    resp = client.list_store_days(headers_without_identity())
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
