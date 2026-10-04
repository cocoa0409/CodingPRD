"""The demand surge: three strict thresholds over the live epoch."""
import pytest

from test_helpers import validate_success
from test_helpers import constants as C
from test_helpers import fixtures as X


def test_fill_fraction_of_exactly_eighty_percent_adds_no_surge(api):
    """PRD §3.4: "Divide the seats sold in the epoch by the seats released and
    carried in, and when that filled fraction is strictly greater than 0.80, add
    1000 basis points. Every one of the three tests uses a strict comparison: a
    filled fraction of exactly 0.80 adds nothing."
    PRD §3.4: "The per-epoch ratios are carried at full precision through the
    comparison and only the resulting basis points are integral, so a fraction
    infinitesimally above its threshold still fires and a fraction exactly at it
    does not."

    Design: Difficulty/boundary_precision_check/boundary_surge_fill_fraction_strictly_greater_than_eighty_percent
    """
    production, performance, allocation, patron = \
        X.setup_unsold_then_sold_five_seat_epoch()

    order = X.buy_seats(performance, allocation, patron, quantity=4,
                        idempotency_key="surge-a")

    assert order["surge_multiplier_bp"] == 0, (
        "this four-seat order takes the epoch to a fill fraction of exactly 0.80 "
        "and the test is a strict greater-than, got "
        f"{order['surge_multiplier_bp']}"
    )
    assert order["unit_price_cents"] == C.SURGE_BOUNDARY_UNIT_AT_080_CENTS, (
        f"expected {C.SURGE_BOUNDARY_UNIT_AT_080_CENTS}, got {order['unit_price_cents']}"
    )


def test_fill_fraction_above_the_threshold_adds_a_thousand_basis_points(api):
    """PRD §3.4: "The third condition watches how much of it has gone. Divide the
    seats sold in the epoch by the seats released and carried in, and when that
    filled fraction is strictly greater than 0.80, add 1000 basis points."
    PRD §3.4: "The `unit_price_cents` on an order is the per-seat price after this
    surge; the allocation's own discounted rate is only the base it starts from."

    Design: Difficulty/boundary_precision_check/boundary_surge_fill_fraction_strictly_greater_than_eighty_percent
    """
    production, performance, allocation, patron = \
        X.setup_unsold_then_sold_five_seat_epoch()

    X.buy_seats(performance, allocation, patron, quantity=4,
                idempotency_key="surge-a")
    X.admit_patron(performance, allocation, patron)
    final = X.buy_seats(performance, allocation, patron, quantity=1,
                        idempotency_key="surge-c")

    assert final["surge_multiplier_bp"] == 1000, (
        "the fill fraction is now 1.00 and it clears the 0.80 threshold while "
        "the released-but-off fraction of 0.00 does not clear the 0.90 "
        f"threshold, got {final['surge_multiplier_bp']}"
    )
    assert final["unit_price_cents"] == C.SURGE_BOUNDARY_UNIT_AT_100_CENTS, (
        f"expected {C.SURGE_BOUNDARY_UNIT_AT_100_CENTS}, got {final['unit_price_cents']}"
    )


def test_one_seat_around_the_fill_boundary_moves_the_price_by_1899_cents(api):
    """PRD §3.4: "Every one of the three tests uses a strict comparison: a filled
    fraction of exactly 0.80 adds nothing, an off-sale fraction of exactly 0.90
    adds nothing, and an order book of exactly twelve adds nothing."
    PRD §3.4: "The surge is applied once, at the point of pricing, and it feeds
    the price that is actually charged."

    Design: Difficulty/boundary_precision_check/boundary_surge_fill_fraction_strictly_greater_than_eighty_percent
    """
    production, performance, allocation, patron = \
        X.setup_unsold_then_sold_five_seat_epoch()

    at_boundary = X.buy_seats(performance, allocation, patron, quantity=4,
                              idempotency_key="surge-a")
    X.admit_patron(performance, allocation, patron)
    past_boundary = X.buy_seats(performance, allocation, patron, quantity=1,
                                idempotency_key="surge-c")

    gap = past_boundary["unit_price_cents"] - at_boundary["unit_price_cents"]
    assert gap == 1899, (
        "the one-seat difference between 0.80 and 1.00 of fill moves the charged "
        f"price by exactly 1899 cents, got {gap}"
    )


def test_released_but_off_fraction_boundary_is_also_strict(api):
    """PRD §3.4: "Divide the difference between the seats released and carried
    into the epoch, on the one hand, and the seats sold in the epoch, on the
    other, by the total seats released and carried in; when that released-but-off
    fraction is strictly greater than 0.90, add 1500 basis points."
    PRD §3.4: "a filled fraction of exactly 0.80 adds nothing, an off-sale
    fraction of exactly 0.90 adds nothing."

    Design: Difficulty/boundary_precision_check/boundary_surge_fill_fraction_strictly_greater_than_eighty_percent
    """
    production, performance, allocation, patron = \
        X.setup_unsold_then_sold_five_seat_epoch(daily_quantity=10)

    one_seat = X.buy_seats(performance, allocation, patron, quantity=1,
                           idempotency_key="off-one")

    assert one_seat["surge_multiplier_bp"] == 0, (
        "ten released against one sold leaves a released-but-off fraction of "
        "exactly 0.90, which is not strictly greater than 0.90, so the term does "
        "not fire, and the fill fraction of exactly 0.10 clears neither of the "
        f"other tests either; got {one_seat['surge_multiplier_bp']}"
    )
    assert one_seat["unit_price_cents"] == 18991, (
        f"with no surge the discounted rate stands at 18991, got {one_seat['unit_price_cents']}"
    )


def test_released_but_off_fraction_above_the_threshold_adds_twenty_one_cents(api):
    """PRD §3.4: "when that released-but-off fraction is strictly greater than
    0.90, add 1500 basis points."
    PRD §3.4: "a fraction infinitesimally above its threshold still fires and a
    fraction exactly at it does not."

    Design: Difficulty/boundary_precision_check/boundary_surge_fill_fraction_strictly_greater_than_eighty_percent
    """
    production, performance, allocation, patron = \
        X.setup_unsold_then_sold_five_seat_epoch(daily_quantity=11)

    one_seat = X.buy_seats(performance, allocation, patron, quantity=1,
                           idempotency_key="off-one-strict")

    assert one_seat["surge_multiplier_bp"] == 1500, (
        "eleven released against one sold leaves a released-but-off fraction of "
        "0.909, which is strictly greater than 0.90, so the term fires; got "
        f"{one_seat['surge_multiplier_bp']}"
    )
    assert one_seat["unit_price_cents"] == 21840, (
        "the 1500 basis point term is fifteen hundredths of the base, so it "
        "carries the 18991 discounted rate to round_half_up(18991 * 1.15) = "
        f"21840, got {one_seat['unit_price_cents']}"
    )