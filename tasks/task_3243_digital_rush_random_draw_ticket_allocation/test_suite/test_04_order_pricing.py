"""Per-seat pricing: the pinned rounding order and the demand surge thresholds."""
import pytest

from test_helpers import validate_success, get_success_data
from test_helpers import constants as C
from test_helpers import fixtures as X


def test_unit_price_prices_the_pinned_two_step_order(api):
    """PRD §3.5: "Take the performance's `face_value_cents`, multiply it by one
    minus the allocation's `discount_pct`, and round that product half-up to a
    whole number of cents — call this the base. Then take the surge in basis
    points determined for this allocation and this performance, and compute the
    base multiplied by ten thousand plus that surge, divided by ten thousand,
    rounding half-up to a whole cent."
    PRD §3.5: "The order is pinned and is not interchangeable: apply the discount
    and round it first, then apply the surge and round it second."

    Design: Difficulty/dual_variant_calc/dual_variant_per_seat_price_rounding_order
    """
    production, performance, allocation, buyer, headers, orders = \
        X.setup_premium_allocation_with_decoy_purchase()

    response = api.create_purchase(
        {"performance_id": performance["id"], "allocation_id": allocation["id"],
         "quantity": 1, "idempotency_key": "dual-price-2"},
        headers,
    )
    purchase = validate_success(response, expected_status=201)

    assert purchase["surge_multiplier_bp"] == 1500, (
        "the released-but-off fraction of 0.909 clears the 0.90 threshold, so the "
        f"surge is 1500 bp, got {purchase['surge_multiplier_bp']}"
    )
    assert purchase["unit_price_cents"] == C.PER_SEAT_PRICE_ROUND_PER_STEP_UNIT_CENTS, (
        "rounding the discounted base before the surge gives "
        f"{C.PER_SEAT_PRICE_ROUND_PER_STEP_UNIT_CENTS}, got {purchase['unit_price_cents']}"
    )


def test_fused_product_variant_sits_one_cent_below_the_charged_price(api):
    """PRD §3.5: "Rounding once over the fused product — face value times the
    discounted fraction times the surged fraction, all before any rounding — is a
    different rule, and it is reserved for the producer's audit reporting; that
    reporting path reads the face value and the discount percentage directly and
    never reads the rounded base."
    PRD §2.7: "a per-seat price applies its discount and rounds, and only then
    applies its surge and rounds again — rounding once over the fused product is a
    different rule and is reserved for producer reporting, never for a charged
    amount."

    Design: Difficulty/dual_variant_calc/dual_variant_per_seat_price_rounding_order
    """
    production, performance, allocation, buyer, headers, orders = \
        X.setup_premium_allocation_with_decoy_purchase()

    response = api.create_purchase(
        {"performance_id": performance["id"], "allocation_id": allocation["id"],
         "quantity": 1, "idempotency_key": "dual-price-3"},
        headers,
    )
    purchase = validate_success(response, expected_status=201)

    fused = round(19990 * (1 - 0.05) * (10000 + 1500) / 10000)
    assert fused == C.PER_SEAT_PRICE_ROUND_ONCE_UNIT_CENTS, (
        f"the fused variant must return {C.PER_SEAT_PRICE_ROUND_ONCE_UNIT_CENTS}, got {fused}"
    )
    assert purchase["unit_price_cents"] - fused == 1, (
        "the two variants differ by exactly 1 cent; the charged price is "
        f"{purchase['unit_price_cents']} against a fused {fused}"
    )


def test_unit_price_is_unchanged_when_the_allocation_never_surges(api):
    """PRD §3.4: "Two of the four ticket classes never surge. A `RUSH` allocation
    and a `DRAW` allocation price at their discounted rate and stay there
    regardless of how busy the day is, because the whole point of those classes
    is that the price is known and low."

    Design: Difficulty/dual_variant_calc/dual_variant_per_seat_price_rounding_order
    """
    production, performance, allocation = X.setup_released_allocation(
        face_value_cents=19990, ticket_type="RUSH", daily_quantity=11,
        discount_pct=0.05, refundable=True, per_order_limit=3,
    )
    patron = X.register_patron(email="no_surge_buyer@example.com")
    X.join_queue(performance, allocation, patron)
    X.ops_run("2026-09-12T09:05:00Z")

    purchase = X.buy_seats(performance, allocation, patron, quantity=1,
                           idempotency_key="no-surge-1")

    assert purchase["surge_multiplier_bp"] == 0, (
        "a RUSH allocation never carries a demand surge, got "
        f"{purchase['surge_multiplier_bp']}"
    )
    assert purchase["unit_price_cents"] == 18991, (
        f"the discounted rate stands alone at 18991, got {purchase['unit_price_cents']}"
    )


def test_group_discount_rounds_once_after_the_quantity_extension(api):
    """PRD §3.5: "Compute the unit price multiplied by the quantity, apply the
    group discount to that product by multiplying it by ten thousand minus the
    group discount over ten thousand, and round the result half-up exactly once —
    at the end."
    PRD §3.5: "The four-step order is pinned: the unit price is already a whole
    number of cents from the first stage, the multiplication by quantity comes
    next, the group discount is applied to that extended product, and the single
    rounding closes the sequence."

    Design: Difficulty/combinatorial_formula/combinatorial_line_subtotal_rounds_once_after_quantity_extension
    """
    production, performance, allocation, patron, purchase = \
        X.setup_four_seat_rush_order()

    assert purchase["unit_price_cents"] == C.SUBTOTAL_UNIT_CENTS, (
        f"expected the rounded unit price {C.SUBTOTAL_UNIT_CENTS}, got {purchase['unit_price_cents']}"
    )
    assert purchase["subtotal_cents"] == C.SUBTOTAL_GROUP_DISCOUNTED_CENTS, (
        "extending the unit price and discounting the product gives "
        f"{C.SUBTOTAL_GROUP_DISCOUNTED_CENTS}, got {purchase['subtotal_cents']}"
    )
    assert purchase["quantity"] == 4


def test_discounting_the_unit_first_would_produce_a_different_subtotal(api):
    """PRD §3.5: "Applying the discount to the unit price and rounding before
    extension is a different rule retained only to detect implementations that
    reorder the steps — for a unit price of 8385 cents and a quantity of four it
    yields 30188 cents, two cents above the 30186 cents the charged order
    produces on identical inputs."

    Design: Difficulty/combinatorial_formula/combinatorial_line_subtotal_rounds_once_after_quantity_extension
    """
    production, performance, allocation, patron, purchase = \
        X.setup_four_seat_rush_order()

    from decimal import Decimal, ROUND_HALF_UP

    def rhu(value):
        return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    reordered = rhu(C.SUBTOTAL_UNIT_CENTS * (10000 - 1000) / 10000) * 4
    assert reordered == C.SUBTOTAL_DISCOUNT_BEFORE_QUANTITY_CENTS, (
        f"the reordered rule must give {C.SUBTOTAL_DISCOUNT_BEFORE_QUANTITY_CENTS}, got {reordered}"
    )
    assert purchase["subtotal_cents"] == C.SUBTOTAL_GROUP_DISCOUNTED_CENTS, (
        f"the charged subtotal is {C.SUBTOTAL_GROUP_DISCOUNTED_CENTS}, not the reordered {reordered}"
    )
    assert reordered - purchase["subtotal_cents"] == 2, \
        "the reordered rule sits exactly two cents above the charged subtotal"


def test_no_group_discount_applies_below_four_seats(api):
    """PRD §3.5: "A group discount of 1000 basis points applies when the order's
    `quantity` is at least four, and no discount applies below four."

    Design: Difficulty/combinatorial_formula/combinatorial_line_subtotal_rounds_once_after_quantity_extension
    """
    production, performance, allocation, patron, purchase = \
        X.setup_four_seat_rush_order()

    third_buyer = X.register_patron(email="subtotal_three@example.com")
    X.join_queue(performance, allocation, third_buyer)
    X.ops_run("2026-09-12T09:10:00Z")
    small = X.buy_seats(performance, allocation, third_buyer, quantity=3,
                        idempotency_key="subtotal-3")

    assert small["quantity"] == 3
    assert small["subtotal_cents"] == small["unit_price_cents"] * 3, (
        "below four seats no concession applies, so the subtotal is the plain "
        f"extension: expected {small['unit_price_cents'] * 3}, got {small['subtotal_cents']}"
    )