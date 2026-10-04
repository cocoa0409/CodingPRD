"""Order pricing: pinned per-line rounding and the clamp-before-subtract target."""

from test_helpers import (
    OrderKind,
    fixtures,
    factories,
    make_customer_headers,
    validate_success,
)


def _active_day(client, business_date, daypart_overrides=None):
    return fixtures.open_store_day_with_active_daypart(
        client, business_date, "%sT11:00:00Z" % business_date,
        daypart_overrides=daypart_overrides,
    )


def test_per_line_fee_rounding_beats_sum_then_round(client):
    """Three lines of 555x1: per-line fees round(27.75)=28 each, summed to 84;
    the forbidden sum-then-round order would give 83.

    "For portal kinds, each line additionally accrues a portal fee equal to the
    line subtotal multiplied by the 5 percent portal fee rate, rounded half-up to
    a whole cent per line"
    "its `portal_fee_cents` is the sum of the already-rounded per-line fees (per
    §2.6, per-line rounding precedes summation)"
    "the rounding order is pinned, and summing unrounded fees before rounding
    once is forbidden because it produces different cents."

    Design: Difficulty/combinatorial_formula/order_pricing_per_line_rounding_beats_sum_then_round
    """
    day = _active_day(client, "2026-09-12")
    product = fixtures.create_product(
        client, sku="CHZ", name="Cheese", list_price_cents=555
    )

    resp = client.create_order(
        factories.order_payload(
            day.store_day["id"],
            day.daypart["id"],
            "cust-1",
            OrderKind.PORTAL_STANDARD,
            [
                factories.order_line(product["id"], quantity=1, customized=False),
                factories.order_line(product["id"], quantity=1, customized=False),
                factories.order_line(product["id"], quantity=1, customized=False),
            ],
        ),
        make_customer_headers("cust-1"),
    )
    order = validate_success(resp, 201)

    assert order["subtotal_cents"] == 1665
    assert order["portal_fee_cents"] == 84, (
        "per-line rounding: 3 x round_half_up(27.75) = 3 x 28; sum-then-round (83) is forbidden"
    )
    assert order["total_cents"] == 1749


def test_pricing_computed_once_and_frozen(client):
    """A second read of the order reports the same frozen figures.

    "Pricing is computed once at placement and frozen on the order thereafter."

    Design: Difficulty/combinatorial_formula/order_pricing_per_line_rounding_beats_sum_then_round
    """
    day = _active_day(client, "2026-09-12")
    product = fixtures.create_product(
        client, sku="CHZ", name="Cheese", list_price_cents=555
    )
    order = validate_success(
        client.create_order(
            factories.order_payload(
                day.store_day["id"],
                day.daypart["id"],
                "cust-1",
                OrderKind.PORTAL_STANDARD,
                [
                    factories.order_line(product["id"], quantity=1, customized=False),
                    factories.order_line(product["id"], quantity=1, customized=False),
                    factories.order_line(product["id"], quantity=1, customized=False),
                ],
            ),
            make_customer_headers("cust-1"),
        ),
        201,
    )
    reread = fixtures.read_order(client, order["id"])
    assert reread["subtotal_cents"] == 1665
    assert reread["portal_fee_cents"] == 84
    assert reread["total_cents"] == 1749


def _preorder_target_setup(client, business_date, rack_capacity, base_demand):
    """A PLANNING DINNER daypart plus a paid PORTAL_PREORDER of 3 units."""
    bundle = fixtures.planned_store_day(
        client,
        business_date,
        daypart_overrides={
            "label": "DINNER",
            "window_start_minute": 960,
            "window_end_minute": 1080,
            "rack_capacity": rack_capacity,
            "base_demand_units": base_demand,
        },
    )
    product = fixtures.create_product(client)
    order = validate_success(
        client.create_order(
            factories.order_payload(
                bundle.store_day["id"],
                bundle.daypart["id"],
                "cust-2",
                OrderKind.PORTAL_PREORDER,
                [factories.order_line(product["id"], quantity=3, customized=False)],
            ),
            make_customer_headers("cust-2"),
        ),
        201,
    )
    fixtures.pay_order(client, order["id"], "cust-2")
    return bundle, product, order


def test_made_ahead_target_clamped_then_reservation_subtracted(client):
    """min(rack_capacity, round(20 x 0.6)) = min(10, 12) = 10, then the 3-unit
    preorder reservation is subtracted after the clamp: target 7.

    "the provisional forecast is multiplied by the made-ahead ratio of 0.6 and
    rounded half-up to a whole unit; that figure is then clamped so it never
    exceeds the daypart's `rack_capacity`; and finally the
    `preorder_reserved_units` (units already promised to paid preorders,
    initially 0) are subtracted — after the capacity clamp, not before — with
    the result never allowed to fall below zero."

    Design: Difficulty/combinatorial_formula/made_ahead_target_clamped_then_reservation_subtracted
    """
    bundle, _product, _order = _preorder_target_setup(
        client, "2026-09-13", rack_capacity=10, base_demand=20
    )

    daypart = fixtures.read_daypart(client, bundle.daypart["id"])
    assert daypart["forecast_units_provisional"] == 20
    assert daypart["preorder_reserved_units"] == 3
    assert daypart["made_ahead_target"] == 7, (
        "clamp-before-subtract: min(10, 12) - 3 = 7 (not min(10, 9) = 9)"
    )


def test_made_ahead_target_without_clamp_or_reservation(client):
    """Without a capacity clamp or reservation the target is round(20 x 0.6) = 12.

    "the provisional forecast is multiplied by the made-ahead ratio of 0.6 and
    rounded half-up to a whole unit; that figure is then clamped so it never
    exceeds the daypart's `rack_capacity`; and finally the
    `preorder_reserved_units` (units already promised to paid preorders,
    initially 0) are subtracted — after the capacity clamp, not before"

    Design: Difficulty/combinatorial_formula/made_ahead_target_clamped_then_reservation_subtracted
    """
    bundle = fixtures.planned_store_day(
        client,
        "2026-09-13",
        daypart_overrides={
            "label": "DINNER",
            "window_start_minute": 960,
            "window_end_minute": 1080,
            "rack_capacity": 20,
            "base_demand_units": 20,
        },
    )
    assert bundle.daypart["forecast_units_provisional"] == 20
    assert bundle.daypart["preorder_reserved_units"] == 0
    assert bundle.daypart["made_ahead_target"] == 12
