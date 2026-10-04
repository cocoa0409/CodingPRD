"""Corner coverage of the calculation rules: forecast, pricing, waste, locker, FIFO."""

import pytest

from test_helpers import (
    OrderKind,
    fixtures,
    factories,
    make_crew_headers,
    make_customer_headers,
    make_manager_headers,
    validate_paginated,
    validate_success,
)


def test_event_cancel_removes_it_from_provisional_forecast(client):
    """Cancelling the SCHEDULED overlapping event drops the provisional forecast
    from 20 back to 10 and the target from 12 to 6.

    "cancellation sets `cancelled` to true, moves the event to `CANCELLED`, and
    immediately recomputes the provisional forecast and made-ahead target of
    every `PLANNED` or `ACTIVE` daypart of the same store day whose window
    intersects the event's, with the cancelled event removed from the inclusion
    set."
    "the provisional forecast is multiplied by the made-ahead ratio of 0.6 and
    rounded half-up to a whole unit"

    Design: Corner/calculations/event_cancel_removes_it_from_provisional_forecast
    """
    bundle = fixtures.planned_store_day(
        client,
        "2026-10-12",
        daypart_overrides={
            "label": "DINNER",
            "window_start_minute": 960,
            "window_end_minute": 1080,
            "rack_capacity": 20,
            "base_demand_units": 10,
        },
    )
    event = fixtures.create_demand_event(
        client,
        bundle.store_day["id"],
        name="Rally",
        window_start_at="2026-10-12T16:00:00Z",
        window_end_at="2026-10-12T19:00:00Z",
        demand_multiplier=2.0,
    )
    before = fixtures.read_daypart(client, bundle.daypart["id"])
    assert before["forecast_units_provisional"] == 20
    assert before["made_ahead_target"] == 12

    validate_success(
        client.cancel_demand_event(event["id"], make_manager_headers()), 200
    )

    after = fixtures.read_daypart(client, bundle.daypart["id"])
    assert after["forecast_units_provisional"] == 10
    assert after["made_ahead_target"] == 6


def test_overlapping_event_multipliers_sum_with_floor(client):
    """Two overlapping SCHEDULED events sum: M = max(1, 1.5 + 2.0) = 3.5, so the
    provisional forecast is round(10 x 3.5) = 35, not a max-only 20.

    "The demand multiplier is the larger of 1.0 and the sum of the overlapping
    events' `demand_multiplier` values, so a daypart with no overlapping events
    forecasts at its base. The provisional forecast is then the
    `base_demand_units` multiplied by that multiplier, rounded half-up to a
    whole unit."

    Design: Corner/calculations/overlapping_event_multipliers_sum_with_floor
    """
    bundle = fixtures.planned_store_day(
        client,
        "2026-10-13",
        daypart_overrides={
            "label": "DINNER",
            "window_start_minute": 960,
            "window_end_minute": 1080,
            "rack_capacity": 40,
            "base_demand_units": 10,
        },
    )
    fixtures.create_demand_event(
        client,
        bundle.store_day["id"],
        name="E1",
        window_start_at="2026-10-13T16:00:00Z",
        window_end_at="2026-10-13T17:00:00Z",
        demand_multiplier=1.5,
    )
    fixtures.create_demand_event(
        client,
        bundle.store_day["id"],
        name="E2",
        window_start_at="2026-10-13T17:01:00Z",
        window_end_at="2026-10-13T19:00:00Z",
        demand_multiplier=2.0,
    )

    daypart = fixtures.read_daypart(client, bundle.daypart["id"])
    assert daypart["forecast_units_provisional"] == 35, (
        "multipliers sum with the max(1, ...) floor: 10 x 3.5 = 35"
    )


def test_promo_price_applies_only_to_non_customized_lines(client):
    """Same product, same order: the non-customized line pays promo 500, the
    customized line pays list 600; fees round per line.

    "For each line, the unit price is the product's `promo_price_cents` when the
    product carries one and the line is not customized, and the
    `list_price_cents` otherwise — a customized line never receives the
    promotional price. The line subtotal is that unit price times the line
    `quantity`. For portal kinds, each line additionally accrues a portal fee
    equal to the line subtotal multiplied by the 5 percent portal fee rate,
    rounded half-up to a whole cent per line"

    Design: Corner/calculations/promo_price_applies_only_to_non_customized_lines
    """
    day = fixtures.open_store_day_with_active_daypart(
        client, "2026-10-14", "2026-10-14T11:00:00Z"
    )
    product = fixtures.create_product(
        client, list_price_cents=600, promo_price_cents=500, customization_allowed=True
    )

    order = validate_success(
        client.create_order(
            factories.order_payload(
                day.store_day["id"],
                day.daypart["id"],
                "cust-c5",
                OrderKind.PORTAL_STANDARD,
                [
                    factories.order_line(product["id"], quantity=1, customized=False),
                    factories.order_line(product["id"], quantity=1, customized=True),
                ],
            ),
            make_customer_headers("cust-c5"),
        ),
        201,
    )
    assert order["subtotal_cents"] == 1100, "500 promo + 600 list"
    assert order["portal_fee_cents"] == 55, "round(500*.05)=25 + round(600*.05)=30"
    assert order["total_cents"] == 1155


def test_waste_pct_zero_produced_is_zero_not_error(client):
    """With nothing produced both percentages are 0.0 and the target is not
    breached — a defined value, not an error and not null.

    "rounded half-up to 2 decimal places — and is defined as 0.0 while
    `produced_units` is zero."
    "a `target_breached` boolean that is true exactly when the standard
    percentage has reached or exceeded that target"

    Design: Corner/calculations/waste_pct_zero_produced_is_zero_not_error
    """
    sd = fixtures.create_store_day(client, "2026-10-15")

    report = validate_success(
        client.get_waste_report(sd["id"], make_manager_headers()), 200
    )
    assert report["waste_pct_standard"] == pytest.approx(0.0, abs=0.005)
    assert report["waste_pct_net"] == pytest.approx(0.0, abs=0.005)
    assert report["target_breached"] is False
    assert report["produced_units"] == 0


def test_locker_selection_lowest_slot_number(client):
    """Slots created in reversed order (2 then 1): the first ready order takes
    slot 1, the next takes slot 2 — selection is by slot_number, never id.

    "The winner is deterministic — the `IDLE` slot with the lowest
    `slot_number`, with the slot's `id` never consulted — and it flips to
    `OCCUPIED` with `current_order_id` set and `occupied_at` stamped."

    Design: Corner/calculations/locker_selection_lowest_slot_number
    """
    day = fixtures.open_store_day_with_active_daypart(
        client, "2026-10-16", "2026-10-16T11:00:00Z"
    )
    fixtures.create_locker_slot(client, day.store_day["id"], slot_number=2)
    slot1 = fixtures.create_locker_slot(client, day.store_day["id"], slot_number=1)
    product = fixtures.create_product(client)

    order_a = fixtures.ready_portal_order(
        client, day.store_day["id"], day.daypart["id"], "cust-c6", product["id"]
    )
    order_b = fixtures.ready_portal_order(
        client, day.store_day["id"], day.daypart["id"], "cust-c7", product["id"]
    )

    assert order_a["locker_slot_id"] == slot1["id"], (
        "lowest slot_number wins regardless of creation order"
    )
    assert order_b["locker_slot_id"] != slot1["id"]


def test_hold_pull_fifo_earliest_racked_first(client):
    """Two runs of the same product racked ten minutes apart: a one-unit pull
    drains the earlier run first.

    "The pool is drawn oldest first, ordered by `racked_at` ascending with ties
    broken by `created_at` ascending, and the line takes the smaller of its
    desired pull and the pool's size; whatever remains is made to order."

    Design: Corner/calculations/hold_pull_fifo_earliest_racked_first
    """
    business_date = "2026-10-17"
    bundle = fixtures.open_day_with_stock(
        client, business_date, active_at="10:35:00Z", run_quantity=2, batch_size=10
    )
    run1 = bundle.run
    # Second run racked at 10:45 from the same batches.
    fixtures.set_clock(client, "%sT10:45:00Z" % business_date)
    run2 = fixtures.racked_run(
        client,
        bundle.daypart["id"],
        bundle.product["id"],
        bundle.dough_batch["id"],
        bundle.cheese_batch["id"],
        2,
    )

    order = validate_success(
        client.create_order(
            factories.order_payload(
                bundle.store_day["id"],
                bundle.daypart["id"],
                "cust-c8",
                OrderKind.PORTAL_STANDARD,
                [factories.order_line(bundle.product["id"], quantity=1, customized=False)],
            ),
            make_customer_headers("cust-c8"),
        ),
        201,
    )
    fixtures.pay_order(client, order["id"], "cust-c8")

    prepared = validate_success(
        client.start_preparation(order["id"], make_crew_headers()), 200
    )
    assert prepared["made_ahead_units"] == 1
    assert prepared["made_to_order_units"] == 0

    run1_after = fixtures.read_run(client, run1["id"])
    run2_after = fixtures.read_run(client, run2["id"])
    assert run1_after["units_available"] == 1, "FIFO consumed from the earlier-racked run"
    assert run2_after["units_available"] == 2, "the later run is untouched"
