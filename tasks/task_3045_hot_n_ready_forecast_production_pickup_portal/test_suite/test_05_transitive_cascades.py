"""Transitive cascades: pay -> reservation -> target; discard -> waste -> posture."""

import pytest

from test_helpers import (
    OrderKind,
    fixtures,
    factories,
    make_customer_headers,
    make_manager_headers,
    make_shift_lead_headers,
    validate_paginated,
    validate_success,
)


def _planned_daypart_with_preorder(client, business_date):
    """DINNER daypart base 20 rack 20 (forecast 20 -> target 12) plus a placed
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
                "cust-3",
                OrderKind.PORTAL_PREORDER,
                [factories.order_line(product["id"], quantity=3, customized=False)],
            ),
            make_customer_headers("cust-3"),
        ),
        201,
    )
    return bundle, product, order


def test_preorder_pay_cascade_reservation_target_and_version(client):
    """Hop 1 pay -> PAID; hop 2 reservation +3; hop 3 target recomputed 12 -> 9.

    "Payment moves `payment_status` to `PAID`."
    "When a `PORTAL_PREORDER` is paid while its promised daypart is still
    `PLANNED`, the payment additionally reserves capacity: the daypart's
    `preorder_reserved_units` increases by the order's total line quantity, the
    `made_ahead_target` is recomputed per §3.1, and the daypart's `version`
    advances"
    "and finally the `preorder_reserved_units` (units already promised to paid
    preorders, initially 0) are subtracted — after the capacity clamp, not
    before"

    Design: Difficulty/transitive_cascade/preorder_pay_cascade_reservation_target_and_daypart_version
    """
    bundle, _product, order = _planned_daypart_with_preorder(client, "2026-09-16")
    assert bundle.daypart["made_ahead_target"] == 12
    assert bundle.daypart["preorder_reserved_units"] == 0

    paid = validate_success(
        client.pay_order(order["id"], make_customer_headers("cust-3")), 200
    )
    assert paid["payment_status"] == "PAID"

    daypart = fixtures.read_daypart(client, bundle.daypart["id"])
    assert daypart["preorder_reserved_units"] == 3, "hop 2: reservation consumed"
    assert daypart["made_ahead_target"] == 9, "hop 3: 12 - 3 recomputed"


def test_preorder_pay_advances_daypart_version(client):
    """The pay cascade bumps the daypart's version independently of the order.

    "the daypart's `version` advances — which is precisely why a stale daypart
    update is rejected under §2.9."
    "`version` (integer): starts at 1 and increments by one on every mutation,
    including mutations driven by system side effects such as counter
    recomputation on a parent."

    Design: Difficulty/transitive_cascade/preorder_pay_cascade_reservation_target_and_daypart_version
    """
    bundle, _product, order = _planned_daypart_with_preorder(client, "2026-09-16")
    version_before = bundle.daypart["version"]

    validate_success(client.pay_order(order["id"], make_customer_headers("cust-3")), 200)

    daypart = fixtures.read_daypart(client, bundle.daypart["id"])
    assert daypart["version"] > version_before, (
        "the reservation side effect must advance the daypart's version"
    )


def _stocked_day_at_waste_breach_edge(client, business_date):
    """20 units produced; one manual discard lands waste_pct_standard at exactly
    5.0 (1/20), the inclusive RESTRICTED boundary."""
    bundle = fixtures.open_day_with_stock(
        client,
        business_date,
        active_at="10:35:00Z",
        run_quantity=20,
        rack_capacity=30,
        base_demand_units=25,
        batch_size=25,
    )
    return bundle


def test_manual_discard_cascade_waste_breach_flips_posture(client):
    """Discard -> counters -> waste 5.0 -> posture RESTRICTED at the inclusive
    boundary.

    "Every discard, from any path, records the `discarded_reason` on the unit
    (`HOLD_EXPIRED`, `DAMAGED`, `QUALITY`, or `NO_SHOW` as applicable)"
    "The store day's `discarded_units` increases by one, `donated_units`
    increases by one only when the row was donated, and both waste percentages
    are recomputed per §2.8, advancing the parent day's `version`."
    "A daypart's derived `posture` is `RESTRICTED` exactly when its parent store
    day's `waste_pct_standard` is greater than or equal to that 5.0 target — the
    boundary is inclusive, so a day sitting at exactly 5.0 percent is already
    restricted"

    Design: Difficulty/transitive_cascade/manual_discard_cascade_waste_breach_and_posture_recompute
    """
    bundle = _stocked_day_at_waste_breach_edge(client, "2026-09-17")
    assert bundle.daypart["posture"] == "NORMAL"
    units = fixtures.holding_units(client, bundle.run["id"])

    discarded = validate_success(
        client.discard_hold_unit(
            units[0]["id"], {"reason": "DAMAGED"}, make_shift_lead_headers()
        ),
        200,
    )
    assert discarded["status"] == "DISCARDED"

    day = fixtures.read_store_day(client, bundle.store_day["id"])
    assert day["discarded_units"] == 1
    assert day["waste_pct_standard"] == pytest.approx(5.0, abs=0.005)

    daypart = fixtures.read_daypart(client, bundle.daypart["id"])
    assert daypart["posture"] == "RESTRICTED", (
        "posture is derived from the live parent counters; the inclusive boundary flips it"
    )


def test_manual_discard_advances_store_day_version_and_waste_log(client):
    """The discard writes exactly one waste-log row and advances the parent day.

    "appends exactly one `WasteLog` row per unit — the row's `quantity` is always
    1 — capturing the `store_day_id`, the `daypart_id` of the discarded unit's
    run, the `hold_unit_id`, the `reason`, the `donated` flag"
    "The store day's `discarded_units` increases by one, `donated_units`
    increases by one only when the row was donated, and both waste percentages
    are recomputed per §2.8, advancing the parent day's `version`."

    Design: Difficulty/transitive_cascade/manual_discard_cascade_waste_breach_and_posture_recompute
    """
    bundle = _stocked_day_at_waste_breach_edge(client, "2026-09-17")
    version_before = bundle.store_day["version"]
    units = fixtures.holding_units(client, bundle.run["id"])

    fixtures.get_success_data(
        client.discard_hold_unit(
            units[0]["id"], {"reason": "DAMAGED"}, make_shift_lead_headers()
        )
    )

    day = fixtures.read_store_day(client, bundle.store_day["id"])
    assert day["version"] > version_before
    assert day["discarded_units"] == 1

    logs, meta = validate_paginated(
        client.list_waste_logs_of(bundle.store_day["id"], make_manager_headers())
    )
    assert meta["total_count"] == 1
    assert logs[0]["quantity"] == 1
    assert logs[0]["reason"] == "DAMAGED"
    assert logs[0]["donated"] is False
    assert logs[0]["hold_unit_id"] == units[0]["id"]
