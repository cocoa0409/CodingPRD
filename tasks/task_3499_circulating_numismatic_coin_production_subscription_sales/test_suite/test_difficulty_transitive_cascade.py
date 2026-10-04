"""Difficulty rule transitive_cascade (PRD §3.1, §3.3, §3.6): one action
bubbles through a depth-3 chain of dependent entities — a run's PASS
inspection accumulates order fulfillment, flips the order to FULFILLED, and
finalizes realized seigniorage; an order cancel releases units, reopens the
product, and drives a waitlist-promotion chain that closes it again."""
import pytest

from test_helpers import TEST_USERS, get_success_data, make_collector_headers, validate_success
from test_helpers.assertions import (
    realized_seigniorage_cents,
    realized_unit_blank_cost_cents,
)
from test_helpers.constants import (
    DEFAULT_DENOMINATION,
    DEFAULT_LOCKED_COPPER_PRICE_CENTS_PER_TONNE,
)
from test_helpers.fixtures import (
    create_collector,
    create_run,
    get_order,
    get_product,
    inspect_run,
    place_order,
    setup_circulating_base,
    setup_on_sale_product,
    start_run,
)

LIAISON = TEST_USERS["fed_liaison_headers"]


def test_run_completion_bubbles_fulfillment_and_seigniorage(api):
    """PRD §3.1: "As runs complete, the order's `quantity_fulfilled_pieces`
    accumulates the `produced_pieces` of its `COMPLETED` linked runs. When a
    completing run pushes the fulfilled count to at least the ordered quantity,
    the order auto-transitions `FULFILLING → FULFILLED` and finalizes its
    `realized_seigniorage_cents`: the platform computes the denomination's
    realized unit blank cost by dividing the summed `realized_cost_cents` of
    that denomination's `DELIVERED` lots by the summed `blanks_produced` of
    those same lots, rounding the quotient half-up to 2 decimal places; it then
    subtracts that unit cost and the denomination's `striking_cost_cents` from
    `face_value_cents`, rounds the resulting unit margin half-up to 2 decimal
    places, and only then multiplies by `quantity_ordered_pieces`."
    PRD §2.5: "Nullable computed fields stay null until the event that fixes
    them: an order's `realized_seigniorage_cents` until the order is fulfilled,
    a lot's `realized_cost_cents` until the lot is delivered, an allocation's
    `total_price_cents` until the allocation is confirmed, and a case's
    `destroyed_by_user_ids` until destruction is certified."

    Design: Difficulty/transitive_cascade/run_completion_bubbles_fulfillment_and_seigniorage
    """
    # QUARTER; hedged 10t lot delivered (realized unit blank cost 5.11c);
    # FY2026 order for 100000 pieces; run1 60000 on P1, run2 40000 on P2.
    denomination, lot, fed_order = setup_circulating_base(
        api, quantity_ordered_pieces=100000)
    run1 = create_run(
        api, fed_order["id"], facility="PHILADELPHIA", press_line="P1",
        planned_start="2026-10-05T08:00:00Z", planned_end="2026-10-05T12:00:00Z",
        planned_quantity=60000)
    run2 = create_run(
        api, fed_order["id"], facility="PHILADELPHIA", press_line="P2",
        planned_start="2026-10-05T08:00:00Z", planned_end="2026-10-05T12:00:00Z",
        planned_quantity=40000)
    start_run(api, run1["id"])
    inspect_run(api, run1["id"], outcome="PASS", good_pieces=60000)

    # Depth 1-2 visible before the trigger: fulfillment accumulated, the order
    # is FULFILLING, and realized seigniorage is still null.
    order = get_success_data(api.get_fed_order(fed_order["id"], LIAISON))
    assert order["status"] == "FULFILLING"
    assert order["quantity_fulfilled_pieces"] == 60000
    assert order["realized_seigniorage_cents"] is None

    # Trigger: run2 completes and pushes fulfilled to exactly ordered.
    start_run(api, run2["id"])
    inspect_run(api, run2["id"], outcome="PASS", good_pieces=40000)

    resp = api.get_fed_order(fed_order["id"], LIAISON)
    order = validate_success(resp)
    assert order["quantity_fulfilled_pieces"] == 100000
    assert order["status"] == "FULFILLED"
    expected_unit_blank = realized_unit_blank_cost_cents(
        [(10 * DEFAULT_LOCKED_COPPER_PRICE_CENTS_PER_TONNE,
          10 * DEFAULT_DENOMINATION["blanks_per_tonne"])])
    assert expected_unit_blank == 5.11
    expected_realized = realized_seigniorage_cents(
        100000, DEFAULT_DENOMINATION["face_value_cents"],
        expected_unit_blank, DEFAULT_DENOMINATION["striking_cost_cents"])
    assert expected_realized == 1789000.0
    assert order["realized_seigniorage_cents"] == pytest.approx(expected_realized, abs=0.01)


def test_order_cancel_releases_units_and_promotes_waitlist(api):
    """PRD §3.6: "Cancellation flips `allocation_status` to `RELEASED` — and
    therefore the derived status to `CANCELLED` — refunds a `PAID` order to
    `REFUNDED`, and, for an order that held allocated units, returns its
    quantity to the product's `remaining_units`, reopening a `SOLD_OUT` product
    to `ON_SALE` when the count dips below the limit."
    PRD §3.6: "Released units immediately trigger waitlist promotion: the
    platform scans the product's `WAITLISTED` orders oldest first by
    `created_at`, ties broken by server receipt order, under strict
    head-of-line blocking — the earliest waiting order is promoted to
    `ALLOCATED` if its `quantity` fits the remaining units, growing
    `allocated_units` and possibly closing the product at `SOLD_OUT` again, and
    the scan repeats with the new earliest; the moment the earliest waiting
    order does not fit, promotion stops and no later order is considered, even
    one that would fit."

    Design: Difficulty/transitive_cascade/order_cancel_releases_units_and_promotes_waitlist
    """
    product = setup_on_sale_product(
        api, product_code="PROMO-1", product_family="PF1", price_cents=3000,
        mintage_limit=3, household_order_limit=10)
    c1 = create_collector(api, full_name="A", email="a@example.com",
                          household_id="HH-A")
    c2 = create_collector(api, full_name="B", email="b@example.com",
                          household_id="HH-B")
    c3 = create_collector(api, full_name="C", email="c@example.com",
                          household_id="HH-C")
    o_a = place_order(api, product["id"], c1, 3)
    assert o_a["allocation_status"] == "ALLOCATED"
    o_b = place_order(api, product["id"], c2, 2)
    assert o_b["allocation_status"] == "WAITLISTED"
    o_c = place_order(api, product["id"], c3, 1)
    assert o_c["allocation_status"] == "WAITLISTED"
    product = get_product(api, product["id"])
    assert product["status"] == "SOLD_OUT"
    assert product["allocated_units"] == 3

    # Trigger: cancel the 3-unit order. Chain: release -> SOLD_OUT flips back
    # -> B (qty 2) promotes -> C (qty 1) promotes -> allocated == limit again.
    resp = api.cancel_order(o_a["id"], make_collector_headers(c1["id"]))
    o_a = validate_success(resp)
    assert o_a["allocation_status"] == "RELEASED"
    assert o_a["status"] == "CANCELLED"
    assert o_a["payment_status"] == "UNPAID"  # never paid, no refund owed

    o_b = get_order(api, o_b["id"])
    assert o_b["allocation_status"] == "ALLOCATED"
    o_c = get_order(api, o_c["id"])
    assert o_c["allocation_status"] == "ALLOCATED"

    product = get_product(api, product["id"])
    assert product["allocated_units"] == 3
    assert product["remaining_units"] == 0
    assert product["status"] == "SOLD_OUT"
