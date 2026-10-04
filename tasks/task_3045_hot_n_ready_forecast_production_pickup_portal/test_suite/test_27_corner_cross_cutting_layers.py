"""Corner coverage of cross-cutting layers: OCC, derived counters, thresholds."""

import pytest

from test_helpers import (
    ApiErrorId,
    OrderKind,
    fixtures,
    factories,
    make_manager_headers,
    make_shift_lead_headers,
    validate_error,
    validate_success,
)


def test_occ_stale_version_on_daypart_update(client):
    """A stale expected_daypart_version is rejected 412; the current one
    succeeds and bumps the version by one.

    "Updating a daypart's planning attributes requires the request to carry
    `expected_daypart_version` holding the `version` the client last observed on
    that daypart. If the daypart's current `version` no longer matches — for
    example because a preorder payment advanced the reservation counter and
    bumped the version after the client read it — the update is rejected with
    `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_layers/occ_stale_version_on_daypart_update
    """
    bundle = fixtures.planned_store_day(client, "2026-11-08")
    dp = bundle.daypart
    manager = make_manager_headers()
    version_1 = dp["version"]

    updated = validate_success(
        client.update_daypart(
            dp["id"],
            {"base_demand_units": 15, "expected_daypart_version": version_1},
            manager,
        ),
        200,
    )
    version_2 = updated["version"]
    assert version_2 == version_1 + 1

    resp = client.update_daypart(
        dp["id"],
        {"rack_capacity": 25, "expected_daypart_version": version_1},
        manager,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    fresh = validate_success(
        client.update_daypart(
            dp["id"],
            {"rack_capacity": 25, "expected_daypart_version": version_2},
            manager,
        ),
        200,
    )
    assert fresh["version"] == version_2 + 1
    assert fresh["rack_capacity"] == 25


def test_occ_stale_version_on_storeday_update(client):
    """The open transition advanced the day past the client's view: the stale
    PUT is rejected 412.

    "Updating a store day likewise requires `expected_store_day_version`
    matching the day row's current `version`. Any mutation that advanced the day
    since the client's last read — a racked production run incrementing
    `produced_units`, a discard recomputing the waste counters — causes the
    mismatch, and the update is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_storeday_update
    """
    bundle = fixtures.planned_store_day(client, "2026-11-09")
    sd = bundle.store_day
    manager = make_manager_headers()

    opened = validate_success(client.open_store_day(sd["id"], manager), 200)
    assert opened["version"] == sd["version"] + 1

    resp = client.update_store_day(
        sd["id"],
        {"business_date": "2026-11-09", "expected_store_day_version": sd["version"]},
        manager,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_derived_waste_counters_reconcile_after_sold_and_discard(client):
    """3 produced, 1 sold via pickup, 1 discarded: counters reconcile and sold
    units are not waste.

    "It is **sold** when the order it was allocated to reaches readiness, moving
    from `ALLOCATED` to the terminal `SOLD` state and adding one to the store
    day's `sold_units` per unit."
    "The store day's `discarded_units` increases by one"
    "it is the `discarded_units` divided by `produced_units`, multiplied by
    100, rounded half-up to 2 decimal places"

    Design: Corner/cross_cutting_layers/derived_waste_counters_reconcile_after_sold_and_discard
    """
    bundle = fixtures.open_day_with_stock(
        client, "2026-11-10", active_at="10:35:00Z", run_quantity=3, batch_size=5
    )
    fixtures.create_locker_slot(client, bundle.store_day["id"], slot_number=1)

    order = fixtures.picked_up_portal_order(
        client, bundle.store_day["id"], bundle.daypart["id"], "cust-e4",
        bundle.product["id"],
    )
    assert order["fulfillment_status"] == "PICKED_UP"

    units = fixtures.holding_units(client, bundle.run["id"])
    assert len(units) == 2
    fixtures.get_success_data(
        client.discard_hold_unit(
            units[0]["id"], {"reason": "DAMAGED"}, make_shift_lead_headers()
        )
    )

    day = fixtures.read_store_day(client, bundle.store_day["id"])
    assert day["produced_units"] == 3
    assert day["sold_units"] == 1
    assert day["discarded_units"] == 1
    assert day["waste_pct_standard"] == pytest.approx(33.33, abs=0.005)


def test_threshold_boundary_just_below_target_stays_normal(client):
    """Four discards of 100 produced sit at 4.0 (NORMAL); the fifth hits exactly
    5.0 and flips RESTRICTED.

    "A daypart's derived `posture` is `RESTRICTED` exactly when its parent store
    day's `waste_pct_standard` is greater than or equal to that 5.0 target — the
    boundary is inclusive, so a day sitting at exactly 5.0 percent is already
    restricted — and `NORMAL` otherwise."

    Design: Corner/cross_cutting_layers/threshold_boundary_just_below_target_stays_normal
    """
    bundle = fixtures.open_day_with_stock(
        client,
        "2026-11-11",
        active_at="10:35:00Z",
        run_quantity=100,
        rack_capacity=120,
        base_demand_units=100,
        batch_size=120,
    )
    units = fixtures.holding_units(client, bundle.run["id"], limit=5)
    assert len(units) == 5

    for unit in units[:4]:
        fixtures.get_success_data(
            client.discard_hold_unit(
                unit["id"], {"reason": "DAMAGED"}, make_shift_lead_headers()
            )
        )

    daypart_at4 = fixtures.read_daypart(client, bundle.daypart["id"])
    assert daypart_at4["posture"] == "NORMAL", "4.0 percent stays below the target"

    fixtures.get_success_data(
        client.discard_hold_unit(
            units[4]["id"], {"reason": "DAMAGED"}, make_shift_lead_headers()
        )
    )
    daypart_at5 = fixtures.read_daypart(client, bundle.daypart["id"])
    assert daypart_at5["posture"] == "RESTRICTED", "exactly 5.0 flips the posture"

    day = fixtures.read_store_day(client, bundle.store_day["id"])
    assert day["waste_pct_standard"] == pytest.approx(5.0, abs=0.005)
