"""Derived figures and deterministic orderings computed inside the request.

Nothing in this file waits for a nightly job. When a shopper reserves capacity on
a delivery slot the service re-prices that slot's surge premium from how full it
already is, how little notice the shopper is giving and how many vans are already
forming on the route — and freezes the multiplier the shopper actually saw onto
the booking, so two baskets reserved seconds apart can legitimately quote
different delivery fees. When a planner starts picking, the same request lays out
a total retrieval order that sends the bots after frozen goods first and then
places every retrieval at the emptiest, roomiest pick station that can handle its
temperature class. When the van is sequenced, the totes come off the loading list
last-stop-first with the freezer compartment loaded first inside each stop, and
the transport cost is added up one rounded stop at a time. Alongside those
orderings sit the figures the commercial side reads: the charge waterfall's
inclusive free-delivery and loyalty thresholds, the slot capacity ledger that
holds a waitlisted booking at exactly zero units, and the two inventory-accuracy
scores a grid zone earns from an audit — one pooled before dividing, one divided
before averaging — of which only the unit-weighted figure can put the zone on
hold.
"""

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_delivery_slot_shape,
    assert_field_absent_or_null,
    assert_instant_equals,
    assert_int_field,
    assert_load_sequence,
    assert_money,
    assert_order_money,
    assert_order_statuses,
    assert_pick_task_shape,
    assert_ratio,
    assert_sequence_indexes,
    assert_sku_ledger,
    assert_slot_booking_shape,
    assert_slot_ledger,
    assert_station_status_matches_count,
    assert_status,
    assert_surge_multiplier,
    assert_wave_posture,
    list_items_and_meta,
    read_object,
)
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.test_users import make_customer_headers
from test_helpers.types import (
    BillingStatus,
    BookingStatus,
    FulfillmentStatus,
    GridZoneStatus,
    LoyaltyTier,
    PickStationStatus,
    PickTaskStatus,
    TemperatureZone,
    ToteStatus,
    WavePosture,
    WaveStatus,
)


# ─── Surge premiums on a delivery slot ───────────────────────────────────────


def test_surge_utilisation_premium_lifts_at_exactly_060_and_085(api):
    """Both utilisation tiers admit their boundary, and each booking keeps the
    multiplier the shopper was quoted at the moment the reservation was made.

    Cites the requirement it rests on: "When utilisation is at least 0.85 the
    premium is 0.35; otherwise, when it is at least 0.60 the premium is 0.15;
    otherwise it is 0.00. Both boundaries are inclusive: utilisation of exactly
    0.85 earns 0.35, and exactly 0.60 earns 0.15."

    Design: Corner/calculations/surge_utilization_tiers_are_inclusive_at_060_and_085
    """
    fixtures.set_clock(api, DEFAULT_CLOCK_UTC)
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(
        api, temperature_zone=TemperatureZone.AMBIENT.value
    )
    sku = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(
        api, route["id"], total_capacity_units=20, withheld_units=0
    )
    account = fixtures.create_customer_account(
        api, route["id"], loyalty_tier=LoyaltyTier.BASIC.value
    )

    baskets = []
    for distance in (5.00, 6.00, 7.00):
        order = fixtures.create_customer_order(
            api, account["id"], stop_distance_km=distance
        )
        fixtures.add_order_line(
            api, account["id"], order["id"], sku["id"], ordered_qty=2
        )
        baskets.append(order)

    # Eleven of twenty units is 0.55 utilisation — below the first tier.
    first = fixtures.create_slot_booking(
        api, account["id"], slot["id"], baskets[0]["id"], units=11
    )
    after_first = fixtures.read_delivery_slot(api, slot["id"])
    assert_delivery_slot_shape(after_first)
    assert_slot_ledger(
        after_first,
        total_capacity_units=20,
        withheld_units=0,
        held_units=11,
        confirmed_units=0,
        available_units=9,
    )
    assert_surge_multiplier(after_first, 1.00)
    assert_slot_booking_shape(first)
    assert_ratio(first, "surge_multiplier_at_booking", 1.00, places=2)
    assert_money(first, "quoted_fee_cents", 599)

    # One more unit lands utilisation on exactly 0.60, which earns 0.15.
    second = fixtures.create_slot_booking(
        api, account["id"], slot["id"], baskets[1]["id"], units=1
    )
    after_second = fixtures.read_delivery_slot(api, slot["id"])
    assert_slot_ledger(
        after_second, held_units=12, confirmed_units=0, available_units=8
    )
    assert_surge_multiplier(after_second, 1.15)
    assert_ratio(second, "surge_multiplier_at_booking", 1.00, places=2)
    assert_money(second, "quoted_fee_cents", 599)

    # Five more units land utilisation on exactly 0.85, which earns 0.35.
    third = fixtures.create_slot_booking(
        api, account["id"], slot["id"], baskets[2]["id"], units=5
    )
    after_third = fixtures.read_delivery_slot(api, slot["id"])
    assert_slot_ledger(
        after_third,
        total_capacity_units=20,
        withheld_units=0,
        held_units=17,
        confirmed_units=0,
        available_units=3,
    )
    assert_surge_multiplier(after_third, 1.35)
    assert_ratio(third, "surge_multiplier_at_booking", 1.15, places=2)
    assert_money(third, "quoted_fee_cents", 689)

    for booking in (first, second, third):
        assert_status(booking, BookingStatus.HELD.value)

    assert_order_money(
        fixtures.read_order(api, account["id"], baskets[0]["id"]),
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=599,
        order_total_cents=1999,
    )
    assert_order_money(
        fixtures.read_order(api, account["id"], baskets[1]["id"]),
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=599,
        order_total_cents=1999,
    )
    assert_order_money(
        fixtures.read_order(api, account["id"], baskets[2]["id"]),
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=689,
        order_total_cents=2089,
    )


def test_route_congestion_premium_stops_growing_at_three_active_waves(
    api, admin_headers, wave_planner_headers
):
    """A fourth van forming on the route adds nothing to the congestion premium,
    which is already capped at three active waves.

    Cites the requirement it rests on: "The service counts the delivery waves on
    the same `route_id` as the slot whose `status` is `FORMING` or `PICKING`, caps
    that count at 3, and multiplies the capped count by 0.05 — so the congestion
    premium is at most 0.15."

    Design: Corner/calculations/surge_congestion_add_caps_at_three_active_waves
    """
    fixtures.set_clock(api, DEFAULT_CLOCK_UTC)
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(
        api, temperature_zone=TemperatureZone.AMBIENT.value
    )
    sku = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=700, physical_units=100
    )
    # Six hours of lead time, so the notice premium is a fixed 0.20 throughout.
    slot = fixtures.create_delivery_slot(
        api,
        route["id"],
        window_start="2026-08-01T06:00:00.000Z",
        window_end="2026-08-01T08:00:00.000Z",
        total_capacity_units=10,
        withheld_units=0,
    )

    # At most one wave may serve a given slot, so each van needs a slot of its own.
    van_slots = [
        fixtures.create_delivery_slot(
            api,
            route["id"],
            window_start=f"2026-08-0{day}T06:00:00.000Z",
            window_end=f"2026-08-0{day}T08:00:00.000Z",
            total_capacity_units=10,
            withheld_units=0,
        )
        for day in (2, 3, 4, 6)
    ]
    for van_slot in van_slots[:3]:
        fixtures.create_delivery_wave(
            api, route["id"], van_slot["id"], cutoff_at="2026-08-01T05:00:00.000Z"
        )

    account = fixtures.create_customer_account(
        api, route["id"], loyalty_tier=LoyaltyTier.BASIC.value
    )
    order = fixtures.create_customer_order(api, account["id"], stop_distance_km=5.00)
    fixtures.add_order_line(api, account["id"], order["id"], sku["id"], ordered_qty=2)

    booking = fixtures.create_slot_booking(
        api, account["id"], slot["id"], order["id"], units=9
    )
    # Opening a van on the route is not one of the events that re-prices a slot,
    # so the shopper was quoted the figure standing since the slot was opened.
    assert_ratio(booking, "surge_multiplier_at_booking", 1.20, places=2)
    assert_money(booking, "quoted_fee_cents", 719)

    with_three_vans = fixtures.read_delivery_slot(api, slot["id"])
    assert_slot_ledger(
        with_three_vans,
        total_capacity_units=10,
        withheld_units=0,
        held_units=9,
        confirmed_units=0,
        available_units=1,
    )
    assert_surge_multiplier(with_three_vans, 1.70)

    fourth_van = fixtures.create_delivery_wave(
        api, route["id"], van_slots[3]["id"], cutoff_at="2026-08-01T05:00:00.000Z"
    )
    assert_status(fourth_van, WaveStatus.FORMING.value)
    assert_wave_posture(fourth_van, WavePosture.OPEN.value)

    with_four_vans = fixtures.read_delivery_slot(api, slot["id"])
    assert_surge_multiplier(with_four_vans, 1.70)

    _items, meta = list_items_and_meta(
        api.list_delivery_waves(
            wave_planner_headers,
            params={"route_id": route["id"], "status": WaveStatus.FORMING.value},
        )
    )
    assert meta["total_count"] == 4, (
        f"expected four forming vans on the route, got {meta['total_count']}"
    )

    assert_order_money(
        fixtures.read_order(api, account["id"], order["id"]),
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=719,
        order_total_cents=2119,
    )
    assert_delivery_slot_shape(
        read_object(api.get_delivery_slot(slot["id"], admin_headers))
    )


# ─── Station selection and retrieval order on the robotic grid ───────────────


def test_station_selector_prefers_the_emptiest_then_the_roomiest_station(api):
    """The retrieval goes to the emptiest capable station, and once a tote is
    sitting at that station the next retrieval prefers the roomiest of the
    stations still empty.

    Cites the requirement it rests on: "Eligible stations are ranked by
    `current_tote_count` ascending, so the emptiest station wins; ties are broken
    by `max_concurrent_totes` descending, so the roomiest station wins; then by
    `station_code` ascending; and finally, when all three rank keys tie, by
    `created_at` ascending."

    Design: Corner/calculations/pick_station_assignment_prefers_the_emptiest_then_the_largest_station
    """
    fixtures.set_clock(api, DEFAULT_CLOCK_UTC)
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(
        api, temperature_zone=TemperatureZone.AMBIENT.value
    )
    narrow_station = fixtures.create_pick_station(
        api,
        station_code="ST-1",
        temperature_zone_capability=[TemperatureZone.AMBIENT.value],
        max_concurrent_totes=2,
    )
    first_roomy_station = fixtures.create_pick_station(
        api,
        station_code="ST-2",
        temperature_zone_capability=[TemperatureZone.AMBIENT.value],
        max_concurrent_totes=5,
    )
    second_roomy_station = fixtures.create_pick_station(
        api,
        station_code="ST-3",
        temperature_zone_capability=[TemperatureZone.AMBIENT.value],
        max_concurrent_totes=5,
    )
    sku = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=700, physical_units=100
    )
    morning_slot = fixtures.create_delivery_slot(
        api, route["id"], total_capacity_units=10, withheld_units=0
    )
    afternoon_slot = fixtures.create_delivery_slot(
        api,
        route["id"],
        window_start="2026-08-05T14:00:00.000Z",
        window_end="2026-08-05T16:00:00.000Z",
        total_capacity_units=10,
        withheld_units=0,
    )

    morning = fixtures.build_confirmed_order(
        api, route["id"], morning_slot["id"], [sku["id"]], ordered_qty=2, units=2
    )
    afternoon = fixtures.build_confirmed_order(
        api,
        route["id"],
        afternoon_slot["id"],
        [sku["id"]],
        ordered_qty=2,
        units=2,
        stop_distance_km=6.00,
    )
    morning_wave = fixtures.create_delivery_wave(api, route["id"], morning_slot["id"])
    fixtures.slot_order_into_wave(api, morning_wave["id"], morning["order"]["id"])
    afternoon_wave = fixtures.create_delivery_wave(
        api,
        route["id"],
        afternoon_slot["id"],
        cutoff_at="2026-08-05T12:00:00.000Z",
    )
    fixtures.slot_order_into_wave(api, afternoon_wave["id"], afternoon["order"]["id"])

    fixtures.start_picking(api, morning_wave["id"])
    morning_task = fixtures.pick_task_for_line(api, morning["lines"][0]["id"])
    assert_pick_task_shape(morning_task)
    # Every station is empty, so the capacity tie between ST-2 and ST-3 falls to
    # the lower station code.
    assert morning_task["pick_station_id"] == first_roomy_station["id"], (
        "with every station empty the retrieval belongs at ST-2, "
        f"got station {morning_task['pick_station_id']}"
    )
    assert_status(morning_task, PickTaskStatus.QUEUED.value)
    assert_int_field(morning_task, "sequence_index", 1)

    tote = fixtures.create_tote(
        api,
        morning_wave["id"],
        first_roomy_station["id"],
        temperature_zone=TemperatureZone.AMBIENT.value,
    )
    assert_status(tote, ToteStatus.OPEN.value)
    assert tote["pick_station_id"] == first_roomy_station["id"]

    occupied = fixtures.read_pick_station(api, first_roomy_station["id"])
    assert_int_field(occupied, "current_tote_count", 1)
    assert_status(occupied, PickStationStatus.ACTIVE.value)
    assert_station_status_matches_count(occupied)
    for station in (narrow_station, second_roomy_station):
        still_empty = fixtures.read_pick_station(api, station["id"])
        assert_int_field(still_empty, "current_tote_count", 0)
        assert_status(still_empty, PickStationStatus.IDLE.value)

    fixtures.start_picking(api, afternoon_wave["id"])
    afternoon_task = fixtures.pick_task_for_line(api, afternoon["lines"][0]["id"])
    assert afternoon_task["pick_station_id"] == second_roomy_station["id"], (
        "ST-2 is no longer emptiest, so the roomier of the two empty stations "
        f"should win; got station {afternoon_task['pick_station_id']}"
    )
    assert afternoon_task["pick_station_id"] != narrow_station["id"]
    assert_status(afternoon_task, PickTaskStatus.QUEUED.value)
    assert_int_field(afternoon_task, "sequence_index", 1)

    assert_sku_ledger(
        fixtures.read_inventory_sku(api, sku["id"]),
        physical_units=100,
        allocated_units=4,
        on_hand_units=96,
    )


def test_retrieval_order_puts_frozen_first_then_the_lower_zone_then_the_lower_sku(
    api, pick_operator_headers
):
    """The bots are sent after the freezer line first, and the two ambient lines
    are ordered by their zone code rather than by the order they were shopped.

    Cites the requirement it rests on: "Those lines are sorted by four keys in
    strict priority order: first by the temperature class of the line's SKU,
    ranking `FROZEN` ahead of `CHILLED` ahead of `AMBIENT`; then, among lines of
    the same class, by the `zone_code` of the grid zone holding the SKU, in
    ascending lexicographic order; then by the SKU's `sku_code`, in ascending
    lexicographic order; and finally, as the last tie-break, by the line's own
    `created_at` in ascending order."

    Design: Corner/calculations/retrieval_sequence_ranks_zone_temperature_above_zone_code_above_sku_code
    """
    fixtures.set_clock(api, DEFAULT_CLOCK_UTC)
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    # The higher ambient aisle is built first, so creation order cannot be
    # mistaken for the retrieval order.
    far_ambient_zone = fixtures.create_grid_zone(
        api, zone_code="A2", temperature_zone=TemperatureZone.AMBIENT.value
    )
    near_ambient_zone = fixtures.create_grid_zone(
        api, zone_code="A1", temperature_zone=TemperatureZone.AMBIENT.value
    )
    freezer_zone = fixtures.create_grid_zone(
        api, zone_code="F1", temperature_zone=TemperatureZone.FROZEN.value
    )
    station = fixtures.create_pick_station(
        api,
        station_code="S1",
        temperature_zone_capability=[
            TemperatureZone.AMBIENT.value,
            TemperatureZone.CHILLED.value,
            TemperatureZone.FROZEN.value,
        ],
        max_concurrent_totes=5,
    )
    far_ambient_sku = fixtures.create_inventory_sku(
        api,
        far_ambient_zone["id"],
        sku_code="AMB-1",
        unit_price_cents=700,
        physical_units=100,
    )
    near_ambient_sku = fixtures.create_inventory_sku(
        api,
        near_ambient_zone["id"],
        sku_code="AMB-9",
        unit_price_cents=700,
        physical_units=100,
    )
    frozen_sku = fixtures.create_inventory_sku(
        api,
        freezer_zone["id"],
        sku_code="FRZ-1",
        temperature_zone=TemperatureZone.FROZEN.value,
        unit_price_cents=900,
        physical_units=100,
    )
    slot = fixtures.create_delivery_slot(
        api, route["id"], total_capacity_units=10, withheld_units=0
    )

    # The basket is shopped ambient-first, which is the reverse of the retrieval
    # order the grid should produce.
    basket = fixtures.build_confirmed_order(
        api,
        route["id"],
        slot["id"],
        [far_ambient_sku["id"], near_ambient_sku["id"], frozen_sku["id"]],
        ordered_qty=1,
        units=3,
        loyalty_tier=LoyaltyTier.BASIC.value,
    )
    wave = fixtures.create_delivery_wave(api, route["id"], slot["id"])
    fixtures.slot_order_into_wave(api, wave["id"], basket["order"]["id"])
    fixtures.start_picking(api, wave["id"])

    frozen_task = fixtures.pick_task_for_line(api, basket["lines"][2]["id"])
    near_ambient_task = fixtures.pick_task_for_line(api, basket["lines"][1]["id"])
    far_ambient_task = fixtures.pick_task_for_line(api, basket["lines"][0]["id"])
    assert_sequence_indexes([frozen_task, near_ambient_task, far_ambient_task])

    assert_pick_task_shape(frozen_task)
    assert_int_field(frozen_task, "sequence_index", 1)
    assert_int_field(near_ambient_task, "sequence_index", 2)
    assert_int_field(far_ambient_task, "sequence_index", 3)
    assert frozen_task["grid_zone_id"] == freezer_zone["id"]
    assert near_ambient_task["grid_zone_id"] == near_ambient_zone["id"]
    assert far_ambient_task["grid_zone_id"] == far_ambient_zone["id"]

    for task in (frozen_task, near_ambient_task, far_ambient_task):
        assert_status(task, PickTaskStatus.QUEUED.value)
        assert_field_absent_or_null(task, "tote_id")
        assert_int_field(task, "allocated_units", 1)
        assert task["pick_station_id"] == station["id"]

    ordered_by_sequence = fixtures.pick_tasks_for_wave(api, wave["id"])
    assert [task["id"] for task in ordered_by_sequence] == [
        frozen_task["id"],
        near_ambient_task["id"],
        far_ambient_task["id"],
    ], "the wave's retrieval list is not in freezer-first order"

    _freezer_items, freezer_meta = list_items_and_meta(
        api.list_pick_tasks(
            pick_operator_headers, params={"grid_zone_id": freezer_zone["id"]}
        )
    )
    assert freezer_meta["total_count"] == 1, (
        f"expected one freezer retrieval, got {freezer_meta['total_count']}"
    )
    _station_items, station_meta = list_items_and_meta(
        api.list_pick_tasks(
            pick_operator_headers, params={"pick_station_id": station["id"]}
        )
    )
    assert station_meta["total_count"] == 3, (
        f"expected all three retrievals at S1, got {station_meta['total_count']}"
    )

    for sku in (far_ambient_sku, near_ambient_sku, frozen_sku):
        assert_sku_ledger(
            fixtures.read_inventory_sku(api, sku["id"]),
            physical_units=100,
            allocated_units=1,
            on_hand_units=99,
        )

    assert_status(fixtures.read_wave(api, wave["id"]), WaveStatus.PICKING.value)
    assert_wave_posture(fixtures.read_wave(api, wave["id"]), WavePosture.OPEN.value)
    assert_order_money(
        fixtures.read_order(api, basket["account"]["id"], basket["order"]["id"]),
        merchandise_subtotal_cents=2300,
        delivery_fee_cents=599,
        loyalty_discount_cents=0,
        order_total_cents=2899,
    )


# ─── Sequencing the van ──────────────────────────────────────────────────────


def test_van_is_loaded_last_stop_first_with_the_freezer_tote_ahead_of_ambient(
    api, wave_planner_headers
):
    """The tote for the furthest stop is loaded first, the freezer tote goes in
    ahead of the ambient tote sharing that stop, and the transport cost is the sum
    of the two separately rounded stops.

    Cites the requirement it rests on: "Totes are then sorted by attributed stop
    position **descending**, so the tote for the last stop is loaded first and
    comes out last; then by temperature class ascending in the ranking `FROZEN`
    before `CHILLED` before `AMBIENT`, so frozen totes go into the freezer
    compartment; then by `tote_code` ascending; and finally by `created_at`
    ascending."

    Design: Corner/calculations/loading_sequence_is_lifo_by_stop_then_cold_chain_first_within_a_stop
    """
    fixtures.set_clock(api, DEFAULT_CLOCK_UTC)
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    bay = fixtures.create_dock_bay(api, parallel_van_capacity=2)
    ambient_zone = fixtures.create_grid_zone(
        api, zone_code="A1", temperature_zone=TemperatureZone.AMBIENT.value
    )
    freezer_zone = fixtures.create_grid_zone(
        api, zone_code="F1", temperature_zone=TemperatureZone.FROZEN.value
    )
    station = fixtures.create_pick_station(
        api,
        station_code="S1",
        temperature_zone_capability=[
            TemperatureZone.AMBIENT.value,
            TemperatureZone.FROZEN.value,
        ],
        max_concurrent_totes=5,
    )
    ambient_sku = fixtures.create_inventory_sku(
        api,
        ambient_zone["id"],
        sku_code="AMB-1",
        unit_price_cents=700,
        physical_units=100,
    )
    frozen_sku = fixtures.create_inventory_sku(
        api,
        freezer_zone["id"],
        sku_code="FRZ-1",
        temperature_zone=TemperatureZone.FROZEN.value,
        unit_price_cents=900,
        physical_units=100,
    )
    slot = fixtures.create_delivery_slot(
        api, route["id"], total_capacity_units=10, withheld_units=0
    )

    near_stop = fixtures.build_confirmed_order(
        api,
        route["id"],
        slot["id"],
        [ambient_sku["id"]],
        ordered_qty=2,
        units=2,
        loyalty_tier=LoyaltyTier.BASIC.value,
        stop_distance_km=3.00,
    )
    far_stop = fixtures.build_confirmed_order(
        api,
        route["id"],
        slot["id"],
        [frozen_sku["id"], ambient_sku["id"]],
        ordered_qty=1,
        units=2,
        loyalty_tier=LoyaltyTier.BASIC.value,
        stop_distance_km=8.00,
    )

    wave = fixtures.create_delivery_wave(api, route["id"], slot["id"])
    fixtures.slot_order_into_wave(api, wave["id"], near_stop["order"]["id"])
    fixtures.slot_order_into_wave(api, wave["id"], far_stop["order"]["id"])
    fixtures.assign_dock(
        api,
        wave["id"],
        bay["id"],
        "2026-08-05T09:00:00.000Z",
        "2026-08-05T10:00:00.000Z",
    )
    fixtures.start_picking(api, wave["id"])

    near_task = fixtures.pick_task_for_line(api, near_stop["lines"][0]["id"])
    far_frozen_task = fixtures.pick_task_for_line(api, far_stop["lines"][0]["id"])
    far_ambient_task = fixtures.pick_task_for_line(api, far_stop["lines"][1]["id"])

    near_tote = fixtures.create_tote(
        api,
        wave["id"],
        station["id"],
        tote_code="T-1",
        temperature_zone=TemperatureZone.AMBIENT.value,
    )
    frozen_tote = fixtures.create_tote(
        api,
        wave["id"],
        station["id"],
        tote_code="T-2",
        temperature_zone=TemperatureZone.FROZEN.value,
    )
    far_ambient_tote = fixtures.create_tote(
        api,
        wave["id"],
        station["id"],
        tote_code="T-3",
        temperature_zone=TemperatureZone.AMBIENT.value,
    )

    for task, tote, picked in (
        (near_task, near_tote, 2),
        (far_frozen_task, frozen_tote, 1),
        (far_ambient_task, far_ambient_tote, 1),
    ):
        fixtures.assign_tote(api, task["id"], tote["id"])
        fixtures.start_retrieval(api, task["id"])
        completed = fixtures.complete_pick_task(api, task["id"], picked)
        assert_status(completed, PickTaskStatus.COMPLETED.value)

    for tote in (near_tote, frozen_tote, far_ambient_tote):
        sealed = fixtures.seal_tote(api, tote["id"])
        assert_status(sealed, ToteStatus.SEALED.value)

    fixtures.consolidate_wave(api, wave["id"], headers=wave_planner_headers)
    sequenced = read_object(
        api.compute_loading_sequence(wave["id"], wave_planner_headers)
    )

    assert_status(sequenced, WaveStatus.LOADING.value)
    assert_load_sequence(
        sequenced, [frozen_tote["id"], far_ambient_tote["id"], near_tote["id"]]
    )
    assert_money(sequenced, "transport_cost_cents", 1650)
    assert_int_field(sequenced, "tote_count", 3)
    assert_int_field(sequenced, "order_count", 2)
    assert sequenced["dock_bay_id"] == bay["id"]

    for basket, subtotal, total in (
        (near_stop, 1400, 1999),
        (far_stop, 1600, 2199),
    ):
        order = fixtures.read_order(
            api, basket["account"]["id"], basket["order"]["id"]
        )
        assert_order_statuses(order, fulfillment_status=FulfillmentStatus.LOADED.value)
        assert_order_money(
            order,
            merchandise_subtotal_cents=subtotal,
            delivery_fee_cents=599,
            loyalty_discount_cents=0,
            order_total_cents=total,
        )

    assert_money(
        fixtures.read_order_line(
            api, near_stop["account"]["id"], near_stop["lines"][0]["id"]
        ),
        "final_line_price_cents",
        1400,
    )
    assert_money(
        fixtures.read_order_line(
            api, far_stop["account"]["id"], far_stop["lines"][0]["id"]
        ),
        "final_line_price_cents",
        900,
    )
    assert_money(
        fixtures.read_order_line(
            api, far_stop["account"]["id"], far_stop["lines"][1]["id"]
        ),
        "final_line_price_cents",
        700,
    )

    for tote in (frozen_tote, far_ambient_tote, near_tote):
        assert_status(fixtures.read_tote(api, tote["id"]), ToteStatus.LOADED.value)

    assert_sku_ledger(
        fixtures.read_inventory_sku(api, ambient_sku["id"]),
        physical_units=97,
        allocated_units=0,
        on_hand_units=97,
    )
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, frozen_sku["id"]),
        physical_units=99,
        allocated_units=0,
        on_hand_units=99,
    )


# ─── The charge waterfall's thresholds ───────────────────────────────────────


def test_free_delivery_and_loyalty_thresholds_admit_their_own_boundary(api):
    """A basket landing exactly on one hundred dollars delivers free, a
    pre-discount total landing exactly on fifty dollars earns the Plus rate, and a
    cent short of it earns nothing — unless the shopper is Premier.

    Cites the requirement it rests on: "Then the waiver applies: if
    `merchandise_subtotal_cents` is at least one hundred dollars — 10,000 cents —
    the fee is overwritten with 0. A subtotal of exactly 10,000 cents earns the
    free delivery; 9,999 does not."

    Design: Corner/calculations/charge_waterfall_free_delivery_and_loyalty_thresholds_are_inclusive
    """
    fixtures.set_clock(api, DEFAULT_CLOCK_UTC)
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(
        api, temperature_zone=TemperatureZone.AMBIENT.value
    )
    fifty_dollar_sku = fixtures.create_inventory_sku(
        api, zone["id"], sku_code="AMB-A", unit_price_cents=5000, physical_units=100
    )
    on_threshold_sku = fixtures.create_inventory_sku(
        api, zone["id"], sku_code="AMB-B", unit_price_cents=4401, physical_units=100
    )
    under_threshold_sku = fixtures.create_inventory_sku(
        api, zone["id"], sku_code="AMB-C", unit_price_cents=4400, physical_units=100
    )
    slot = fixtures.create_delivery_slot(
        api, route["id"], total_capacity_units=30, withheld_units=0
    )

    plus_shopper = fixtures.create_customer_account(
        api, route["id"], loyalty_tier=LoyaltyTier.PLUS.value
    )
    premier_shopper = fixtures.create_customer_account(
        api, route["id"], loyalty_tier=LoyaltyTier.PREMIER.value
    )

    baskets = []
    for account_id, sku_id, ordered_qty, distance in (
        (plus_shopper["id"], fifty_dollar_sku["id"], 2, 5.00),
        (plus_shopper["id"], on_threshold_sku["id"], 1, 6.00),
        (plus_shopper["id"], under_threshold_sku["id"], 1, 7.00),
        (premier_shopper["id"], under_threshold_sku["id"], 1, 8.00),
    ):
        order = fixtures.create_customer_order(
            api, account_id, stop_distance_km=distance
        )
        fixtures.add_order_line(
            api, account_id, order["id"], sku_id, ordered_qty=ordered_qty
        )
        booking = fixtures.create_slot_booking(
            api, account_id, slot["id"], order["id"], units=1
        )
        assert_status(booking, BookingStatus.HELD.value)
        assert_ratio(booking, "surge_multiplier_at_booking", 1.00, places=2)
        assert_money(booking, "quoted_fee_cents", 599)
        baskets.append((account_id, order["id"]))

    # Exactly one hundred dollars of groceries: the fee is waived, and the whole
    # hundred dollars still keys the Plus discount.
    assert_order_money(
        fixtures.read_order(api, *baskets[0]),
        merchandise_subtotal_cents=10000,
        delivery_fee_cents=0,
        loyalty_discount_cents=500,
        order_total_cents=9500,
    )
    # A pre-discount total of exactly 5,000 cents earns the Plus five per cent.
    assert_order_money(
        fixtures.read_order(api, *baskets[1]),
        merchandise_subtotal_cents=4401,
        delivery_fee_cents=599,
        loyalty_discount_cents=250,
        order_total_cents=4750,
    )
    # One cent below the tier threshold, the Plus shopper gets nothing.
    assert_order_money(
        fixtures.read_order(api, *baskets[2]),
        merchandise_subtotal_cents=4400,
        delivery_fee_cents=599,
        loyalty_discount_cents=0,
        order_total_cents=4999,
    )
    # The same basket for a Premier shopper is never without a discount.
    assert_order_money(
        fixtures.read_order(api, *baskets[3]),
        merchandise_subtotal_cents=4400,
        delivery_fee_cents=599,
        loyalty_discount_cents=250,
        order_total_cents=4749,
    )

    assert_order_statuses(
        fixtures.read_order(api, *baskets[0]),
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )

    settled_slot = fixtures.read_delivery_slot(api, slot["id"])
    assert_slot_ledger(
        settled_slot,
        total_capacity_units=30,
        withheld_units=0,
        held_units=4,
        confirmed_units=0,
        available_units=26,
    )
    assert_surge_multiplier(settled_slot, 1.00)


# ─── The slot capacity ledger ────────────────────────────────────────────────


def test_a_waitlisted_reservation_occupies_no_capacity_on_the_slot(api):
    """A shopper who joins the waitlist on a full slot leaves every term of the
    capacity ledger exactly where it was, yet still gets quoted the surged fee.

    Cites the requirement it rests on: "Bookings in status `WAITLISTED`,
    `RELEASED` or `BUMPED` contribute zero to every term — a waitlisted booking
    occupies no capacity whatsoever, which is precisely what makes the waitlist
    safe."

    Design: Corner/calculations/slot_ledger_excludes_waitlisted_units_from_the_held_total
    """
    fixtures.set_clock(api, DEFAULT_CLOCK_UTC)
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=599, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(
        api, temperature_zone=TemperatureZone.AMBIENT.value
    )
    sku = fixtures.create_inventory_sku(
        api, zone["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(
        api, route["id"], total_capacity_units=2, withheld_units=0
    )
    account = fixtures.create_customer_account(
        api, route["id"], loyalty_tier=LoyaltyTier.BASIC.value
    )

    baskets = []
    for distance in (5.00, 6.00):
        order = fixtures.create_customer_order(
            api, account["id"], stop_distance_km=distance
        )
        fixtures.add_order_line(
            api, account["id"], order["id"], sku["id"], ordered_qty=2
        )
        baskets.append(order)

    first = fixtures.create_slot_booking(
        api, account["id"], slot["id"], baskets[0]["id"], units=2
    )
    assert_status(first, BookingStatus.HELD.value)
    assert_ratio(first, "surge_multiplier_at_booking", 1.00, places=2)
    assert_money(first, "quoted_fee_cents", 599)

    full_slot = fixtures.read_delivery_slot(api, slot["id"])
    assert_slot_ledger(
        full_slot,
        total_capacity_units=2,
        withheld_units=0,
        held_units=2,
        confirmed_units=0,
        available_units=0,
    )
    assert_surge_multiplier(full_slot, 1.35)

    # Nothing is available, so the second basket can only join the waitlist.
    waitlisted = fixtures.create_slot_booking(
        api, account["id"], slot["id"], baskets[1]["id"], units=2
    )
    assert_slot_booking_shape(waitlisted)
    assert_status(waitlisted, BookingStatus.WAITLISTED.value)
    assert_int_field(waitlisted, "units", 2)
    assert_ratio(waitlisted, "surge_multiplier_at_booking", 1.35, places=2)
    assert_money(waitlisted, "quoted_fee_cents", 809)

    unchanged_slot = fixtures.read_delivery_slot(api, slot["id"])
    assert_slot_ledger(
        unchanged_slot,
        total_capacity_units=2,
        withheld_units=0,
        held_units=2,
        confirmed_units=0,
        available_units=0,
    )
    assert_surge_multiplier(unchanged_slot, 1.35)

    assert_order_money(
        fixtures.read_order(api, account["id"], baskets[0]["id"]),
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=599,
        loyalty_discount_cents=0,
        order_total_cents=1999,
    )
    # The waitlisted booking still counts as the order's booking for the fee step.
    waitlisted_order = fixtures.read_order(api, account["id"], baskets[1]["id"])
    assert_order_statuses(
        waitlisted_order,
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )
    assert_order_money(
        waitlisted_order,
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=809,
        loyalty_discount_cents=0,
        order_total_cents=2209,
    )

    _items, meta = list_items_and_meta(
        api.list_slot_bookings(
            make_customer_headers(account["id"]),
            params={
                "delivery_slot_id": slot["id"],
                "status": BookingStatus.WAITLISTED.value,
            },
        )
    )
    assert meta["total_count"] == 1, (
        f"expected one waitlisted reservation on the slot, got {meta['total_count']}"
    )


# ─── The two inventory-accuracy scores ───────────────────────────────────────


def test_the_two_accuracy_scores_are_rounded_once_to_four_decimal_places(api):
    """One audit of a big accurate line and a tiny missing line produces two very
    different accuracy figures, each rounded once at the end, and only the pooled
    figure puts the aisle on hold.

    Cites the requirement it rests on: "Each score is rounded half up to four
    decimal places, once, at the very end; no intermediate quantity in either
    formula is pre-rounded."

    Design: Corner/calculations/zone_accuracy_scores_round_half_up_to_four_decimal_places
    """
    fixtures.set_clock(api, DEFAULT_CLOCK_UTC)
    zone = fixtures.create_grid_zone(
        api, temperature_zone=TemperatureZone.AMBIENT.value
    )
    big_sku = fixtures.create_inventory_sku(
        api, zone["id"], sku_code="AMB-BIG", unit_price_cents=700, physical_units=10
    )
    tiny_sku = fixtures.create_inventory_sku(
        api, zone["id"], sku_code="AMB-TINY", unit_price_cents=750, physical_units=1
    )

    # Ten units on the shelf count as nine, and the single unit of the other line
    # is missing altogether.
    audited = fixtures.record_audit_counts(
        api, zone["id"], [(big_sku["id"], 9), (tiny_sku["id"], 0)]
    )

    # Pooling first: 1 - (1 + 1) / (10 + 1) = 0.818181...
    assert_ratio(audited, "accuracy_score_unit_weighted", 0.8182, places=4)
    # Dividing first: ((1 - 1/10) + (1 - 1/1)) / 2 = 0.45
    assert_ratio(audited, "accuracy_score_sku_weighted", 0.4500, places=4)
    assert_status(audited, GridZoneStatus.AUDIT_HOLD.value)
    assert_instant_equals(
        audited["last_audited_at"], DEFAULT_CLOCK_UTC, label="last_audited_at"
    )

    stored_zone = fixtures.read_grid_zone(api, zone["id"])
    assert_ratio(stored_zone, "accuracy_score_unit_weighted", 0.8182, places=4)
    assert_ratio(stored_zone, "accuracy_score_sku_weighted", 0.4500, places=4)
    assert_status(stored_zone, GridZoneStatus.AUDIT_HOLD.value)

    counted_big = fixtures.read_inventory_sku(api, big_sku["id"])
    assert_int_field(counted_big, "last_count_system_units", 10)
    assert_int_field(counted_big, "last_count_counted_units", 9)
    # A shrink is negative: counted minus system.
    assert_int_field(counted_big, "last_count_variance_units", -1)
    assert_sku_ledger(
        counted_big, physical_units=9, allocated_units=0, on_hand_units=9
    )

    counted_tiny = fixtures.read_inventory_sku(api, tiny_sku["id"])
    assert_int_field(counted_tiny, "last_count_system_units", 1)
    assert_int_field(counted_tiny, "last_count_counted_units", 0)
    assert_int_field(counted_tiny, "last_count_variance_units", -1)
    assert_sku_ledger(
        counted_tiny, physical_units=0, allocated_units=0, on_hand_units=0
    )
