"""Compensating invariants: reservation round-trip and produced-unit conservation."""

from test_helpers import (
    OrderKind,
    fixtures,
    factories,
    make_customer_headers,
    make_shift_lead_headers,
    validate_success,
)


def _preorder_round_trip_setup(client, business_date="2026-09-26"):
    """DINNER daypart base 20 rack 20 (target 12, reserved 0) plus a placed
    PORTAL_PREORDER of 3 units."""
    bundle = fixtures.planned_store_day(
        client,
        business_date,
        daypart_overrides={
            "label": "DINNER",
            "window_start_minute": 960,
            "window_end_minute": 1080,
            "rack_capacity": 20,
            "base_demand_units": 20,
        },
    )
    product = fixtures.create_product(client)
    order = validate_success(
        client.create_order(
            factories.order_payload(
                bundle.store_day["id"],
                bundle.daypart["id"],
                "cust-10",
                OrderKind.PORTAL_PREORDER,
                [factories.order_line(product["id"], quantity=3, customized=False)],
            ),
            make_customer_headers("cust-10"),
        ),
        201,
    )
    return bundle, order


def test_pay_cancel_round_trip_restores_preorder_reservation(client):
    """pay (+3) then cancel (-3) leaves reservation and target bit-identical.

    "When a `PORTAL_PREORDER` is paid while its promised daypart is still
    `PLANNED`, the payment additionally reserves capacity: the daypart's
    `preorder_reserved_units` increases by the order's total line quantity"
    "Cancellation refunds a `PAID` order to `REFUNDED`; returns any preorder
    reservation the order had consumed — the daypart's
    `preorder_reserved_units` decreases by the order's total line quantity and
    the `made_ahead_target` is recomputed"

    Design: Difficulty/compensating_invariant/pay_cancel_round_trip_restores_preorder_reservation
    """
    bundle, order = _preorder_round_trip_setup(client)
    assert bundle.daypart["preorder_reserved_units"] == 0
    assert bundle.daypart["made_ahead_target"] == 12

    fixtures.pay_order(client, order["id"], "cust-10")
    mid = fixtures.read_daypart(client, bundle.daypart["id"])
    assert mid["preorder_reserved_units"] == 3
    assert mid["made_ahead_target"] == 9

    cancelled = validate_success(
        client.cancel_order(order["id"], make_customer_headers("cust-10")), 200
    )
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"

    daypart = fixtures.read_daypart(client, bundle.daypart["id"])
    assert daypart["preorder_reserved_units"] == 0, "invariant restored"
    assert daypart["made_ahead_target"] == 12, "derived target restored"


def test_unpaid_preorder_cancel_consumes_no_reservation(client):
    """An UNPAID preorder never reserved, so its cancel leaves the target at 12.

    "When a `PORTAL_PREORDER` is paid while its promised daypart is still
    `PLANNED`, the payment additionally reserves capacity"
    "Cancellation refunds a `PAID` order to `REFUNDED`; returns any preorder
    reservation the order had consumed"

    Design: Difficulty/compensating_invariant/pay_cancel_round_trip_restores_preorder_reservation
    """
    bundle, order = _preorder_round_trip_setup(client)

    cancelled = validate_success(
        client.cancel_order(order["id"], make_customer_headers("cust-10")), 200
    )
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "UNPAID"

    daypart = fixtures.read_daypart(client, bundle.daypart["id"])
    assert daypart["preorder_reserved_units"] == 0
    assert daypart["made_ahead_target"] == 12


def test_discard_compensation_preserves_rack_accounting(client):
    """Rack 3 then discard all 3: run closes at zero, production is conserved.

    "On the parent store day, `produced_units` increases by the run's
    `quantity`"
    "A run whose `units_available` reaches zero — every unit allocated, sold, or
    discarded — closes automatically to the terminal `CLOSED` state."
    "The store day's `discarded_units` increases by one"

    Design: Difficulty/compensating_invariant/discard_compensation_preserves_rack_accounting
    """
    bundle = fixtures.open_day_with_stock(
        client, "2026-09-27", active_at="10:35:00Z", run_quantity=3, batch_size=10
    )
    units = fixtures.holding_units(client, bundle.run["id"])
    assert len(units) == 3

    for unit in units:
        fixtures.get_success_data(
            client.discard_hold_unit(
                unit["id"],
                {"reason": "DAMAGED" if unit is not units[1] else "QUALITY"},
                make_shift_lead_headers(),
            )
        )

    run = fixtures.read_run(client, bundle.run["id"])
    assert run["units_available"] == 0
    assert run["status"] == "CLOSED", "auto-close at zero units_available"

    day = fixtures.read_store_day(client, bundle.store_day["id"])
    assert day["produced_units"] == 3, "production conserved — discard does not un-produce"
    assert day["discarded_units"] == 3
    # units_available(0) + discarded(3) + allocated(0) + sold(0) == quantity(3)
    assert run["units_available"] + day["discarded_units"] == 3


def test_partial_discard_keeps_run_holding_and_counters_aligned(client):
    """Discarding one of three leaves the run HOLDING with two units; produced
    stays 3.

    "A run whose `units_available` reaches zero — every unit allocated, sold, or
    discarded — closes automatically to the terminal `CLOSED` state."
    "On the parent store day, `produced_units` increases by the run's
    `quantity`"

    Design: Difficulty/compensating_invariant/discard_compensation_preserves_rack_accounting
    """
    bundle = fixtures.open_day_with_stock(
        client, "2026-09-27", active_at="10:35:00Z", run_quantity=3, batch_size=10
    )
    units = fixtures.holding_units(client, bundle.run["id"])

    fixtures.get_success_data(
        client.discard_hold_unit(
            units[0]["id"], {"reason": "DAMAGED"}, make_shift_lead_headers()
        )
    )

    run = fixtures.read_run(client, bundle.run["id"])
    assert run["units_available"] == 2
    assert run["status"] == "HOLDING"

    day = fixtures.read_store_day(client, bundle.store_day["id"])
    assert day["produced_units"] == 3
    assert day["discarded_units"] == 1
