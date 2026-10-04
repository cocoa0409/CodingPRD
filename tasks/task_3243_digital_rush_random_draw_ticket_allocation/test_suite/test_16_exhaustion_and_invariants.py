"""Inventory exhaustion, its consequences and the epoch that reverses it."""
import pytest

from test_helpers import (
    validate_error, validate_success, get_success_data, ApiErrorId,
)
from test_helpers import constants as C
from test_helpers import fixtures as X


def test_per_order_limit_is_an_inclusive_boundary(api):
    """PRD §3.5: "the quantity must be at least one and no more than the
    allocation's `per_order_limit`; a quantity above that limit is refused with
    `ERR_PER_ORDER_LIMIT_EXCEEDED` (HTTP 409), both here and on a draw claim."

    Design: Corner/validations/per_order_limit_violation_reports_the_constraint_error
    """
    production, performance, allocation = X.setup_released_allocation(
        ticket_type="RUSH", daily_quantity=6, discount_pct=0.5, refundable=True,
        per_order_limit=2,
    )
    patron = X.register_patron(email="limit_patron@example.com")
    X.join_queue(performance, allocation, patron)
    X.ops_run("2026-09-12T09:05:00Z")

    over = api.create_purchase(
        {"performance_id": performance["id"], "allocation_id": allocation["id"],
         "quantity": 3, "idempotency_key": "limit-over"},
        X.patron_headers(patron),
    )
    validate_error(over, ApiErrorId.ERR_PER_ORDER_LIMIT_EXCEEDED, expected_status=409)

    at_limit = validate_success(
        api.create_purchase(
            {"performance_id": performance["id"],
             "allocation_id": allocation["id"],
             "quantity": 2, "idempotency_key": "limit-at"},
            X.patron_headers(patron)),
        expected_status=201)

    assert at_limit["quantity"] == 2, (
        "the boundary is inclusive: quantity 2 is permitted and quantity 3 is "
        "not"
    )


def test_a_rejected_order_does_not_advance_the_sold_count(api):
    """PRD §3.5: "The order advances the allocation's `quantity_sold_today` by the
    quantity bought and increments the allocation's `version`."
    PRD §2.6: "Per-order limits bind only after the epoch cap has been satisfied,
    so a quantity above the allocation's per-order limit yields
    `ERR_PER_ORDER_LIMIT_EXCEEDED` (HTTP 409) on both order creation and draw
    claiming."

    Design: Corner/validations/per_order_limit_violation_reports_the_constraint_error
    """
    production, performance, allocation = X.setup_released_allocation(
        ticket_type="RUSH", daily_quantity=6, discount_pct=0.5, refundable=True,
        per_order_limit=2,
    )
    patron = X.register_patron(email="limit_patron_b@example.com")
    X.join_queue(performance, allocation, patron)
    X.ops_run("2026-09-12T09:05:00Z")

    api.create_purchase(
        {"performance_id": performance["id"], "allocation_id": allocation["id"],
         "quantity": 3, "idempotency_key": "limit-over-b"},
        X.patron_headers(patron),
    )
    X.buy_seats(performance, allocation, patron, quantity=2,
                idempotency_key="limit-at-b")

    refreshed = X.get_allocation(performance, allocation["id"])
    assert refreshed["quantity_sold_today"] == 2, (
        "the day's sold count is advanced only by the accepted order, got "
        f"{refreshed['quantity_sold_today']}"
    )


def test_exhaustion_releases_held_seats_and_abandons_the_queue(api):
    """PRD §3.12: "Every queue position of the performance still in `WAITING`
    moves to `ABANDONED`, because a queue in front of an empty allocation is a
    queue with no prospect. Every `ALLOCATION` hold of the performance that is
    still `HELD` and whose `effective_to` lies in the future moves to `RELEASED`,
    freeing stock the platform can no longer sell this epoch."

    Design: Difficulty/compensating_invariant/invariant_seats_conserved_across_settle_refund_approve_cycle
    """
    production, performance, allocation = X.setup_released_allocation(
        ticket_type="RUSH", daily_quantity=2, discount_pct=0.5, refundable=True,
        per_order_limit=2,
    )
    patron = X.register_patron(email="exhaust_buyer@example.com")
    stander_by = X.register_patron(email="exhaust_by@example.com")
    X.admit_patron(performance, allocation, patron)
    X.join_queue(performance, allocation, stander_by)

    purchase = X.buy_seats(performance, allocation, patron, quantity=2,
                           idempotency_key="exhaust-1")

    refreshed = X.get_allocation(performance, allocation["id"])
    assert refreshed["quantity_sold_today"] == refreshed["daily_release_cap"], (
        "the order takes the day's sold count to the day's ceiling, got "
        f"{refreshed['quantity_sold_today']} against {refreshed['daily_release_cap']}"
    )

    rows = get_success_data(api.list_queue_positions(
        performance["id"], X.OPS, params={"limit": 100}))
    rows = rows.get("data", rows) if isinstance(rows, dict) else rows
    statuses = {row["patron_id"]: row["status"] for row in rows}
    assert statuses[patron["id"]] == "PURCHASED", (
        f"the order's own admission is consumed, got {statuses[patron['id']]}"
    )
    assert statuses[stander_by["id"]] == "ABANDONED", (
        "the exhaustion cascade abandons the position still waiting in front of "
        f"an empty allocation, got {statuses[stander_by['id']]}"
    )


def test_a_settled_refund_lifts_the_allocation_out_of_exhaustion(api):
    """PRD §3.12: "Exhaustion is also reversible within its epoch, and this is the
    one place in the domain where inventory genuinely comes back. When a refund
    settles and returns the purchase's seats to the allocation — decreasing the
    day's sold count — and that decrease takes the count back below the day's
    ceiling, the allocation moves from `EXHAUSTED` back to `RELEASED` and becomes
    dispensable again for the remainder of the current epoch."

    Design: Difficulty/compensating_invariant/invariant_seats_conserved_across_settle_refund_approve_cycle
    """
    production, performance, allocation, patron, purchase = \
        X.setup_settled_then_sold_out(quantity=8, daily_quantity=8)
    assert X.get_allocation(performance, allocation["id"])["status"] == "EXHAUSTED", \
        "selling the whole epoch exhausts the allocation"

    refund = X.open_refund(purchase, patron)
    X.approve_refund(refund, purchase)
    X.settle_refund(refund, X.get_purchase(purchase["id"]))

    reopened = X.get_allocation(performance, allocation["id"])
    assert reopened["quantity_sold_today"] < reopened["daily_release_cap"], (
        "the returned seats take the day's sold count back below its ceiling, got "
        f"{reopened['quantity_sold_today']} against {reopened['daily_release_cap']}"
    )
    assert reopened["status"] == "RELEASED", (
        f"the allocation becomes dispensable again, got {reopened['status']}"
    )


def test_the_dispensed_seat_figures_carry_no_drift_across_the_cycle(api):
    """PRD §3.12: "The seats returned are the seats released: the reversal is
    symmetric with the sale that exhausted the allocation in the first place."
    PRD §3.9: "the allocation's `quantity_sold_today` decreases by the number of
    tickets on the purchase."

    Design: Difficulty/compensating_invariant/invariant_seats_conserved_across_settle_refund_approve_cycle
    """
    production, performance, allocation, patron, purchase = \
        X.setup_settled_then_sold_out(quantity=3, daily_quantity=8)
    released_before = X.get_allocation(performance, allocation["id"])["quantity_released_today"]

    refund = X.open_refund(purchase, patron)
    X.approve_refund(refund, purchase)
    X.settle_refund(refund, X.get_purchase(purchase["id"]))

    final = X.get_allocation(performance, allocation["id"])
    assert final["quantity_sold_today"] == 0, (
        f"the three consumed seats are returned, got {final['quantity_sold_today']}"
    )
    assert final["quantity_released_today"] == released_before, (
        "the released quantity never moved, so the seat accounting shows zero "
        f"drift: {released_before} before the purchase and {final['quantity_released_today']} after"
    )