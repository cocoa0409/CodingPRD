"""Refunds, their window rule and their seat-returning settlement."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
)
from test_helpers import constants as C
from test_helpers import fixtures as X


def test_refund_inside_the_window_reports_the_unfee_d_figure(api):
    """PRD §3.9: "A fixed processing fee of 200 cents is then deducted, but only
    on the two terminal branches: when the request's status is `SETTLED` or
    `COMPENSATED` the fee is subtracted, and when it is `REQUESTED` or
    `PROCESSING` it is not, so a request still in flight reports the un-fee'd
    figure."
    PRD §3.9: "If, on the other hand, the remaining hours before the performance
    start are at least the production's refund window, the base is the full
    `subtotal_cents` — the seat retains its full value while the window is open."

    Design: Difficulty/dual_variant_calc/dual_variant_refund_amount_unit_granularity
    """
    production, performance, allocation, patron, purchase = \
        X.setup_refund_variant_purchase()

    refund = X.open_refund(purchase, patron)

    assert purchase["subtotal_cents"] == 61171, (
        f"expected the four-ticket subtotal 61171, got {purchase['subtotal_cents']}"
    )
    assert refund["refunded_amount_cents"] == C.REFUND_PER_PURCHASE_AMOUNT_CENTS, (
        "the whole subtotal is priced as one unit while the window is open, got "
        f"{refund['refunded_amount_cents']}"
    )
    assert refund["status"] == "REQUESTED"
    assert refund["approved_by"] is None, "no operator has acted on the request yet"
    assert refund["requested_by"] == patron["id"], \
        "the requesting principal is recorded on the request"


def test_the_per_ticket_variant_would_not_apply_to_a_single_ticket_type(api):
    """PRD §3.9: "One variant exists on the half-value step: the default halves
    the whole `subtotal_cents` as one unit and rounds once, whereas the
    alternative is used when an order carries more than one ticket type among its
    `seat_labels` and instead distributes the subtotal per ticket, rounds the
    per-ticket share, and multiplies back."

    Design: Difficulty/dual_variant_calc/dual_variant_refund_amount_unit_granularity
    """
    production, performance, allocation, patron, purchase = \
        X.setup_refund_variant_purchase()

    refund = X.open_refund(purchase, patron)

    assert refund["refunded_amount_cents"] == C.REFUND_PER_PURCHASE_AMOUNT_CENTS, (
        "an order carrying one ticket type prices the whole subtotal as one unit, "
        f"got {refund['refunded_amount_cents']}"
    )
    assert refund["refunded_amount_cents"] != C.REFUND_PER_TICKET_AMOUNT_CENTS, (
        "the per-ticket rule is reserved for orders spanning more than one ticket "
        f"type and must not be applied here; got {refund['refunded_amount_cents']}"
    )


def test_opening_a_refund_does_not_move_the_orders_payment_posture(api):
    """PRD §3.9: "A new request sits in `REQUESTED` with its `patron_id` recorded
    as the requester and its `refunded_amount_cents` stamped by the refund
    calculation below; the purchase's `version` advances by one."

    Design: Difficulty/dual_variant_calc/dual_variant_refund_amount_unit_granularity
    """
    production, performance, allocation, patron, purchase = \
        X.setup_refund_variant_purchase()

    X.open_refund(purchase, patron)
    after = X.get_purchase(purchase["id"])

    assert after["payment_status"] == "SETTLED", (
        "opening a request leaves the payment posture where it was, got "
        f"{after['payment_status']}"
    )
    assert after["version"] == purchase["version"] + 1, (
        f"opening a refund advances the purchase version once, got {after['version']}"
    )


def test_a_non_refundable_allocation_inside_the_window_prices_at_zero(api):
    """PRD §3.9: "If the allocation is not refundable and the remaining hours
    before the performance start are fewer than the production's refund window,
    the base is zero — the seat is non-refundable and the window is closed."
    PRD §3.9: "Finally the result is floored at zero, and that floor is the last
    operation applied."

    Design: Corner/calculations/refund_amount_non_refundable_allocation_inside_window_is_zero
    """
    production, performance, allocation = X.setup_released_allocation(
        ticket_type="RUSH", daily_quantity=6, discount_pct=0.5, refundable=False,
        per_order_limit=2, starts_at="2026-09-12T20:00:00Z",
    )
    patron = X.register_patron(email="norefund@example.com")
    X.join_queue(performance, allocation, patron)
    X.ops_run("2026-09-12T09:05:00Z")
    purchase = X.settle_purchase(
        X.buy_seats(performance, allocation, patron, quantity=2,
                    idempotency_key="norefund-1"))

    refund = X.open_refund(purchase, patron, reason_code="PERFORMANCE_CANCELLED")

    assert refund["refunded_amount_cents"] == 0, (
        "the non-refundable flag inside the window forces a zero base and the "
        f"floor holds it there, got {refund['refunded_amount_cents']}"
    )
    assert refund["status"] == "REQUESTED"
    assert X.get_purchase(purchase["id"])["refunded_cents"] == 0, \
        "no money has moved while the request sits in flight"


def test_a_refundable_allocation_inside_the_window_takes_half_the_subtotal(api):
    """PRD §3.9: "The third branch catches the remaining case, where the
    allocation is refundable but the remaining hours have fallen inside the
    window, and takes half the subtotal, rounding that half-value upward."

    Design: Corner/calculations/refund_amount_non_refundable_allocation_inside_window_is_zero
    """
    production, performance, allocation = X.setup_released_allocation(
        ticket_type="RUSH", daily_quantity=6, discount_pct=0.5, refundable=True,
        per_order_limit=2, starts_at="2026-09-12T20:00:00Z",
    )
    patron = X.register_patron(email="half_window@example.com")
    X.join_queue(performance, allocation, patron)
    X.ops_run("2026-09-12T09:05:00Z")
    purchase = X.settle_purchase(
        X.buy_seats(performance, allocation, patron, quantity=2,
                    idempotency_key="half-window-1"))

    refund = X.open_refund(purchase, patron)

    assert purchase["subtotal_cents"] == 10000, (
        f"the discounted two-seat subtotal is 10000, got {purchase['subtotal_cents']}"
    )
    assert refund["refunded_amount_cents"] == 5000, (
        "a refundable allocation inside the production's window returns half the "
        f"subtotal, got {refund['refunded_amount_cents']}"
    )
    assert refund["status"] == "REQUESTED"


def test_settling_a_refund_returns_the_seats_and_lifts_exhaustion(api):
    """PRD §3.9: "Settlement does four things at once: the request moves to
    `SETTLED`; the purchase's `refunded_cents` increases by the request's
    `refunded_amount_cents` and the purchase's `payment_status` moves to
    `REFUNDED`; the allocation's `quantity_sold_today` decreases by the number of
    tickets on the purchase; and, when that decrease takes the day's sold count
    back below the day's release ceiling, the allocation is lifted out of
    `EXHAUSTED` and back to `RELEASED`."

    Design: Corner/calculations/refund_amount_non_refundable_allocation_inside_window_is_zero
    """
    production, performance, allocation, patron, purchase = \
        X.setup_settled_then_sold_out(quantity=3, daily_quantity=8)
    refund = X.open_refund(purchase, patron)
    X.approve_refund(refund, purchase)
    processing = X.get_purchase(purchase["id"])

    X.settle_refund(refund, processing)

    after = X.get_purchase(purchase["id"])
    refreshed = X.get_allocation(performance, allocation["id"])
    assert after["payment_status"] == "REFUNDED", \
        f"a settled refund moves payment to REFUNDED, got {after['payment_status']}"
    assert after["refunded_cents"] > 0, "the refunded figure rises by the settled amount"
    assert refreshed["quantity_sold_today"] == 0, (
        "the returned tickets come off the day's sold count, got "
        f"{refreshed['quantity_sold_today']}"
    )