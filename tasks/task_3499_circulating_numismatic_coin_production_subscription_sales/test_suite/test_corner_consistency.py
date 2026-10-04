"""Corner coverage — immediate read-after-write consistency: the GET issued
right after a mutating call reflects that call's effects in the same logical
clock instant (PRD §2.5, §3.6)."""

from test_helpers import ApiErrorId, TEST_USERS, validate_success  # noqa: F401
from test_helpers.assertions import assert_order_derived_status, assert_system_timestamp
from test_helpers.factories import order_payment_payload
from test_helpers.fixtures import (
    create_collector,
    place_order,
    setup_on_sale_product,
)
from test_helpers.test_users import make_collector_headers


def test_immediate_read_after_write_consistency(api):
    """PRD §3.6: "A successful payment moves `payment_status` to `PAID` and
    the derived status to `COMPLETED`."
    PRD §2.5: "`version` is an integer that starts at 1 on creation and
    increments by exactly 1 on every mutation of the resource, including
    system-driven auto-transitions."
    PRD §2.5: "`created_at` and `updated_at` are ISO 8601 UTC timestamps
    maintained by the server."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    product = setup_on_sale_product(api)  # ON_SALE, price 2000c
    collector = create_collector(api, full_name="Immediate",
                                 email="imm@example.com", household_id="HH-1")
    order = place_order(api, product["id"], collector, 1)
    assert order["total_cents"] == 2000
    assert order["version"] == 1

    owner = make_collector_headers(collector["id"])
    paid = validate_success(
        api.pay_order(order["id"], order_payment_payload(2000), owner))
    assert paid["payment_status"] == "PAID"
    assert paid["status"] == "COMPLETED"
    assert paid["version"] == order["version"] + 1, (
        "the payment is one mutation, so version advances by exactly 1")

    # The read issued immediately afterwards, in the same clock instant, must
    # already reflect the write — no lag, no recompute delay.
    reread = validate_success(api.get_order(order["id"], owner))
    assert reread["payment_status"] == "PAID", (
        f"immediate GET must show PAID, got {reread['payment_status']}")
    assert reread["status"] == "COMPLETED", (
        f"immediate GET must show derived status COMPLETED, got {reread['status']}")
    assert_order_derived_status(reread)
    assert reread["version"] == paid["version"]
    assert reread["updated_at"] == paid["updated_at"], (
        "the write's updated_at must be what the immediate read returns")
    assert_system_timestamp(reread["updated_at"], "updated_at")
