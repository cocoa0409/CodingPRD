"""Corner coverage proving individual error catalogue entries are reachable."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    OrderKind,
    fixtures,
    factories,
    make_crew_headers,
    make_customer_headers,
    make_manager_headers,
    validate_error,
    validate_success,
)


def test_error_daypart_not_found_triggerable(client):
    """GET with an unknown daypart id surfaces the daypart-specific 404.

    "the request is rejected with the 404 error corresponding to the first
    identifier that does not resolve — `ERR_STORE_DAY_NOT_FOUND`,
    `ERR_DAYPART_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`"

    Design: Corner/errors/error_daypart_not_found_triggerable
    """
    resp = client.get_daypart(NON_EXISTENT_UUID, make_manager_headers())
    validate_error(resp, ApiErrorId.ERR_DAYPART_NOT_FOUND)


def test_error_duplicate_slot_number_triggerable(client):
    """A second slot with the same number in the same day is rejected.

    "A `StoreManager` installs slots for a store day by `slot_number`, a
    positive integer unique within the day (duplicates rejected with
    `ERR_DUPLICATE_SLOT_NUMBER`)"

    Design: Corner/errors/error_duplicate_slot_number_triggerable
    """
    sd = fixtures.create_store_day(client, "2026-11-04")
    fixtures.create_locker_slot(client, sd["id"], slot_number=1)

    resp = client.create_locker_slot(
        sd["id"], factories.locker_slot_payload(slot_number=1), make_manager_headers()
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SLOT_NUMBER)


def test_error_order_not_paid_on_portal_start_preparation(client):
    """An unpaid PORTAL_STANDARD order cannot begin preparation; COUNTER orders
    are exempt from the gate.

    "the order must be `PAID` unless it is a `COUNTER` order (otherwise
    `ERR_ORDER_NOT_PAID`)"

    Design: Corner/errors/error_order_not_paid_on_portal_start_preparation
    """
    day = fixtures.open_store_day_with_active_daypart(
        client, "2026-11-05", "2026-11-05T11:00:00Z"
    )
    product = fixtures.create_product(client)
    order = validate_success(
        client.create_order(
            factories.order_payload(
                day.store_day["id"],
                day.daypart["id"],
                "cust-e3",
                OrderKind.PORTAL_STANDARD,
                [factories.order_line(product["id"], quantity=1, customized=False)],
            ),
            make_customer_headers("cust-e3"),
        ),
        201,
    )
    assert order["payment_status"] == "UNPAID"

    resp = client.start_preparation(order["id"], make_crew_headers())
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PAID)

    stored = fixtures.read_order(client, order["id"], customer_id="cust-e3")
    assert stored["fulfillment_status"] == "PLACED"
