"""Slot bookings, wave formation, retrieval discovery and reverse reachability.

These checks follow a shopper's basket from the moment it reserves capacity on a
delivery slot — where the frozen surge multiplier and the quoted delivery fee are
struck — through the opening of the delivery wave that one van will drive for
that slot, the conversion of that paper wave into physical work when picking
starts and retrieval tasks are minted for the robotic grid, and the opening of
the first tote at a pick station. Alongside the happy paths they hold the site's
foreign keys to account: a wave built on one delivery slot must refuse an order
whose confirmed booking sits on another, every unused identifier answers with its
own resource family's not-found code rather than a generic one, and every parent
is navigable back to its children through the filtered collections — order to
lines, order to bookings, slot to waves, zone to SKUs, route to accounts and
route to slots — so that no row in the building is reachable only by guessing its
identifier.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_delivery_wave_shape,
    assert_field_absent_or_null,
    assert_instant_equals,
    assert_int_field,
    assert_money,
    assert_order_money,
    assert_order_statuses,
    assert_pick_task_shape,
    assert_ratio,
    assert_slot_booking_shape,
    assert_slot_ledger,
    assert_sku_ledger,
    assert_station_status_matches_count,
    assert_status,
    assert_surge_multiplier,
    assert_tote_shape,
    assert_version_is,
    assert_wave_posture,
    list_items_and_meta,
    only_item,
    read_object,
)
from test_helpers.types import (
    BillingStatus,
    BookingStatus,
    FulfillmentStatus,
    LineStatus,
    LoyaltyTier,
    PickStationStatus,
    PickTaskStatus,
    SubstitutionResolution,
    TemperatureZone,
    ToteStatus,
    WavePosture,
    WaveStatus,
)


def _ambient_site(api, base_delivery_fee_cents=599, total_capacity_units=10):
    """A route, an ambient grid zone, one ambient SKU and one far-future slot."""
    route = fixtures.create_delivery_route(
        api, base_delivery_fee_cents=base_delivery_fee_cents, per_km_cost_cents=150
    )
    zone = fixtures.create_grid_zone(
        api, temperature_zone=TemperatureZone.AMBIENT.value
    )
    sku = fixtures.create_inventory_sku(
        api,
        zone["id"],
        temperature_zone=TemperatureZone.AMBIENT.value,
        unit_price_cents=700,
        physical_units=100,
    )
    slot = fixtures.create_delivery_slot(
        api,
        route["id"],
        total_capacity_units=total_capacity_units,
        withheld_units=0,
    )
    return {"route": route, "zone": zone, "sku": sku, "slot": slot}


def test_first_booking_on_an_empty_far_future_slot_freezes_surge_and_quotes_the_fee(
    api, make_customer_headers
):
    """The first reservation on an empty slot months out freezes surge at 1.00, quotes the route's plain fee and makes the basket's totals non-null while the groceries stay in DRAFT.

    Cites the requirement it rests on: "Both branches capture the price context
    identically: `surge_multiplier_at_booking` is set to the slot's
    `surge_multiplier` as it stands at that instant and is frozen thereafter, and
    `quoted_fee_cents` is the route's `base_delivery_fee_cents` multiplied by that
    frozen multiplier, rounded half up to whole cents."

    Design: Corner/entities/create_slot_booking_computes_quoted_fee_and_freezes_surge
    """
    site = _ambient_site(api)
    basket = fixtures.build_shopper_with_basket(
        api,
        site["route"]["id"],
        [site["sku"]["id"]],
        ordered_qty=2,
        loyalty_tier=LoyaltyTier.BASIC.value,
    )
    shopper = basket["account"]["id"]
    order = fixtures.read_order(api, shopper, basket["order"]["id"])
    assert_money(order, "merchandise_subtotal_cents", 1400)

    booking = read_object(
        api.create_slot_booking(
            factories.slot_booking_payload(
                site["slot"]["id"], order["id"], order["version"], units=2
            ),
            make_customer_headers(shopper),
        ),
        expected_status=201,
    )

    assert_slot_booking_shape(booking)
    assert_status(booking, BookingStatus.HELD.value)
    assert_int_field(booking, "units", 2)
    assert_ratio(booking, "surge_multiplier_at_booking", 1.00, places=2)
    assert_money(booking, "quoted_fee_cents", 599)

    slot = fixtures.read_delivery_slot(api, site["slot"]["id"])
    assert_slot_ledger(
        slot,
        total_capacity_units=10,
        withheld_units=0,
        held_units=2,
        confirmed_units=0,
        available_units=8,
    )
    assert_surge_multiplier(slot, 1.00)

    booked_order = fixtures.read_order(api, shopper, order["id"])
    assert_order_money(
        booked_order,
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=599,
        loyalty_discount_cents=0,
        order_total_cents=1999,
    )
    assert_order_statuses(
        booked_order,
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )
    assert_field_absent_or_null(booked_order, "authorized_amount_cents")


def test_reading_an_unused_booking_identifier_reports_the_booking_family(
    api, admin_headers
):
    """A read on a reservation identifier that was never minted answers with the booking family's own not-found code, never a generic one.

    Cites the requirement it rests on: "Each resource family has its own
    not-found code, listed in §5; the resolution is never a generic 404 body."

    Design: Corner/entities/get_slot_booking_unknown_id_returns_booking_not_found
    """
    site = _ambient_site(api)
    basket = fixtures.build_shopper_with_basket(
        api, site["route"]["id"], [site["sku"]["id"]], ordered_qty=2
    )
    shopper = basket["account"]["id"]
    booking = fixtures.create_slot_booking(
        api, shopper, site["slot"]["id"], basket["order"]["id"], units=2
    )
    assert_status(booking, BookingStatus.HELD.value)

    validate_error(
        api.get_slot_booking(NON_EXISTENT_UUID, admin_headers),
        ApiError.BOOKING_NOT_FOUND.value,
    )

    still_held = fixtures.read_slot_booking(api, booking["id"])
    assert_status(still_held, BookingStatus.HELD.value)


def test_a_newly_opened_wave_starts_forming_open_and_completely_unloaded(
    api, wave_planner_headers
):
    """A wave opened for one route and one delivery slot starts FORMING with an OPEN posture, no orders, no totes, an empty load sequence and every dock and cost field still null.

    Cites the requirement it rests on: "A newly opened wave has `status`
    `FORMING` and `posture` `OPEN`, an `order_count` and a `tote_count` of 0, an
    empty `load_sequence` array, a null `transport_cost_cents`, a null
    `consolidated_by_user_id`, and a null `dock_bay_id` with null `load_start` and
    `load_end`."

    Design: Corner/entities/create_delivery_wave_defaults_forming_open_and_empty_load_sequence
    """
    route = fixtures.create_delivery_route(api)
    slot = fixtures.create_delivery_slot(api, route["id"], total_capacity_units=10)

    wave = read_object(
        api.create_delivery_wave(
            factories.delivery_wave_payload(
                route["id"], slot["id"], cutoff_at="2026-08-05T08:00:00.000Z"
            ),
            wave_planner_headers,
        ),
        expected_status=201,
    )

    assert_delivery_wave_shape(wave)
    assert_status(wave, WaveStatus.FORMING.value)
    assert_wave_posture(wave, WavePosture.OPEN.value)
    assert_int_field(wave, "order_count", 0)
    assert_int_field(wave, "tote_count", 0)
    assert wave["load_sequence"] == [], (
        f"a wave with nothing loaded should carry an empty load_sequence, "
        f"got {wave['load_sequence']!r}"
    )
    assert_instant_equals(wave["cutoff_at"], "2026-08-05T08:00:00.000Z", label="cutoff_at")
    for empty_field in (
        "dock_bay_id",
        "load_start",
        "load_end",
        "transport_cost_cents",
        "consolidated_by_user_id",
    ):
        assert_field_absent_or_null(wave, empty_field)
    assert_version_is(wave, 1)


def test_opening_a_wave_on_a_delivery_slot_that_does_not_exist_is_refused(
    api, wave_planner_headers
):
    """A wave naming a delivery slot that was never opened is refused with the slot family's not-found code even though the route it names resolves perfectly.

    Cites the requirement it rests on: "Every foreign-key identifier supplied in
    the request body exists, validated in the order in which the fields are listed
    for that endpoint. Violation yields the same resource-specific not-found code
    as check 5, with HTTP 404."

    Design: Corner/entities/create_delivery_wave_unknown_slot_returns_slot_not_found
    """
    route = fixtures.create_delivery_route(api)

    validate_error(
        api.create_delivery_wave(
            factories.delivery_wave_payload(
                route["id"], NON_EXISTENT_UUID, cutoff_at="2026-08-05T08:00:00.000Z"
            ),
            wave_planner_headers,
        ),
        ApiError.SLOT_NOT_FOUND.value,
    )

    waves, meta = list_items_and_meta(
        api.list_delivery_waves(wave_planner_headers, params={"route_id": route["id"]})
    )
    assert meta["total_count"] == 0, (
        f"a refused wave must leave the route with no waves, got {meta['total_count']}"
    )
    assert waves == []


def test_reading_an_unused_wave_identifier_reports_the_wave_family(
    api, pick_operator_headers
):
    """A read on a wave identifier that was never opened answers with the wave family's own not-found code and leaves the wave that does exist untouched.

    Cites the requirement it rests on: "Each resource family has its own
    not-found code, listed in §5; the resolution is never a generic 404 body."

    Design: Corner/entities/get_delivery_wave_unknown_id_returns_wave_not_found
    """
    route = fixtures.create_delivery_route(api)
    slot = fixtures.create_delivery_slot(api, route["id"], total_capacity_units=10)
    wave = fixtures.create_delivery_wave(
        api, route["id"], slot["id"], cutoff_at="2026-08-05T08:00:00.000Z"
    )

    validate_error(
        api.get_delivery_wave(NON_EXISTENT_UUID, pick_operator_headers),
        ApiError.WAVE_NOT_FOUND.value,
    )

    still_forming = fixtures.read_wave(api, wave["id"])
    assert_status(still_forming, WaveStatus.FORMING.value)


def test_starting_picking_mints_the_retrieval_task_for_a_pending_line(
    api, pick_operator_headers
):
    """Retrieval work is never posted by hand: starting the picking phase mints exactly one QUEUED task for the wave's pending line with its sequence index, its station and its allocation all computed, and moves the ordered units out of the SKU's on-hand figure.

    Cites the requirement it rests on: "Each new task records the `order_line_id`
    it serves, a `sku_id` copied from the line's own `sku_id`, a `grid_zone_id`
    copied from that SKU's `grid_zone_id`, a `pick_station_id` chosen by the
    station selector below, a `sequence_index` from the retrieval sequence below,
    and an `allocated_units` equal to the line's `ordered_qty`."

    Design: Corner/entities/start_picking_creates_pick_task_with_computed_sequence_and_station
    """
    site = _ambient_site(api)
    station = fixtures.create_pick_station(
        api,
        temperature_zone_capability=[TemperatureZone.AMBIENT.value],
        max_concurrent_totes=3,
    )
    confirmed = fixtures.build_confirmed_order(
        api,
        site["route"]["id"],
        site["slot"]["id"],
        [site["sku"]["id"]],
        ordered_qty=2,
        units=2,
    )
    line = confirmed["lines"][0]
    wave = fixtures.create_delivery_wave(
        api,
        site["route"]["id"],
        site["slot"]["id"],
        cutoff_at="2026-08-05T08:00:00.000Z",
    )
    fixtures.slot_order_into_wave(api, wave["id"], confirmed["order"]["id"])

    fixtures.start_picking(api, wave["id"])

    tasks, meta = list_items_and_meta(
        api.list_pick_tasks(pick_operator_headers, params={"order_line_id": line["id"]})
    )
    assert meta["total_count"] == 1, (
        f"one pending line should yield exactly one retrieval task, "
        f"got {meta['total_count']}"
    )
    task = only_item(tasks)
    assert_pick_task_shape(task)
    assert_status(task, PickTaskStatus.QUEUED.value)
    assert task["order_line_id"] == line["id"]
    assert task["sku_id"] == site["sku"]["id"]
    assert task["grid_zone_id"] == site["zone"]["id"]
    assert task["pick_station_id"] == station["id"]
    assert_int_field(task, "sequence_index", 1)
    assert_int_field(task, "allocated_units", 2)
    for empty_field in ("tote_id", "picked_units", "actual_weight_grams"):
        assert_field_absent_or_null(task, empty_field)

    allocated_sku = fixtures.read_inventory_sku(api, site["sku"]["id"])
    assert_sku_ledger(
        allocated_sku, physical_units=100, allocated_units=2, on_hand_units=98
    )

    assert_status(fixtures.read_wave(api, wave["id"]), WaveStatus.PICKING.value)
    assert_order_statuses(
        fixtures.read_order(
            api, confirmed["account"]["id"], confirmed["order"]["id"]
        ),
        fulfillment_status=FulfillmentStatus.PICKING.value,
    )


def test_reading_an_unused_retrieval_task_identifier_reports_the_task_family(
    api, pick_operator_headers
):
    """A read on a retrieval-task identifier the grid never issued answers with the pick-task family's own not-found code.

    Cites the requirement it rests on: "Each resource family has its own
    not-found code, listed in §5; the resolution is never a generic 404 body."

    Design: Corner/entities/get_pick_task_unknown_id_returns_pick_task_not_found
    """
    station = fixtures.create_pick_station(
        api,
        temperature_zone_capability=[TemperatureZone.AMBIENT.value],
        max_concurrent_totes=3,
    )

    validate_error(
        api.get_pick_task(NON_EXISTENT_UUID, pick_operator_headers),
        ApiError.PICK_TASK_NOT_FOUND.value,
    )

    idle_station = fixtures.read_pick_station(api, station["id"])
    assert_int_field(idle_station, "current_tote_count", 0)
    assert_station_status_matches_count(idle_station)


def test_opening_a_tote_starts_it_empty_and_lifts_its_station_out_of_idle(
    api, pick_operator_headers
):
    """A tote opened at a pick station starts OPEN with nothing assigned to it, and the same request raises the station's open-tote count to one, flips the station from IDLE to ACTIVE and raises the wave's tote count.

    Cites the requirement it rests on: "Opening it recomputes the station's
    `current_tote_count` and flips the station's `status` from `IDLE` to `ACTIVE`,
    and it recomputes the wave's `tote_count`."

    Design: Corner/entities/create_tote_defaults_open_and_activates_the_station
    """
    route = fixtures.create_delivery_route(api)
    station = fixtures.create_pick_station(
        api,
        temperature_zone_capability=[TemperatureZone.AMBIENT.value],
        max_concurrent_totes=3,
    )
    slot = fixtures.create_delivery_slot(api, route["id"], total_capacity_units=10)
    wave = fixtures.create_delivery_wave(
        api, route["id"], slot["id"], cutoff_at="2026-08-05T08:00:00.000Z"
    )

    tote = read_object(
        api.create_tote(
            factories.tote_payload(
                wave["id"],
                station["id"],
                temperature_zone=TemperatureZone.AMBIENT.value,
            ),
            pick_operator_headers,
        ),
        expected_status=201,
    )

    assert_tote_shape(tote)
    assert_status(tote, ToteStatus.OPEN.value)
    assert_int_field(tote, "assigned_line_count", 0)
    assert tote["temperature_zone"] == TemperatureZone.AMBIENT.value
    assert_version_is(tote, 1)

    active_station = fixtures.read_pick_station(api, station["id"])
    assert_int_field(active_station, "current_tote_count", 1)
    assert_status(active_station, PickStationStatus.ACTIVE.value)
    assert_station_status_matches_count(active_station)

    assert_int_field(fixtures.read_wave(api, wave["id"]), "tote_count", 1)


def test_reading_an_unused_tote_identifier_reports_the_tote_family(
    api, pick_operator_headers
):
    """A read on a tote identifier no operator ever opened answers with the tote family's own not-found code and leaves the station idle.

    Cites the requirement it rests on: "Each resource family has its own
    not-found code, listed in §5; the resolution is never a generic 404 body."

    Design: Corner/entities/get_tote_unknown_id_returns_tote_not_found
    """
    station = fixtures.create_pick_station(
        api,
        temperature_zone_capability=[TemperatureZone.AMBIENT.value],
        max_concurrent_totes=3,
    )

    validate_error(
        api.get_tote(NON_EXISTENT_UUID, pick_operator_headers),
        ApiError.TOTE_NOT_FOUND.value,
    )

    idle_station = fixtures.read_pick_station(api, station["id"])
    assert_status(idle_station, PickStationStatus.IDLE.value)
    assert_station_status_matches_count(idle_station)


def test_reading_an_unused_substitution_proposal_identifier_reports_the_proposal_family(
    api, pick_operator_headers
):
    """A read on a substitution-offer identifier that no shortage ever produced answers with the proposal family's own not-found code.

    Cites the requirement it rests on: "Each resource family has its own
    not-found code, listed in §5; the resolution is never a generic 404 body."

    Design: Corner/entities/get_substitution_proposal_unknown_id_returns_proposal_not_found
    """
    station = fixtures.create_pick_station(
        api,
        temperature_zone_capability=[TemperatureZone.AMBIENT.value],
        max_concurrent_totes=3,
    )

    validate_error(
        api.get_substitution_proposal(NON_EXISTENT_UUID, pick_operator_headers),
        ApiError.PROPOSAL_NOT_FOUND.value,
    )

    untouched_station = fixtures.read_pick_station(api, station["id"])
    assert_int_field(untouched_station, "current_tote_count", 0)


def test_an_order_confirmed_on_one_slot_cannot_be_slotted_into_a_wave_built_on_another(
    api, wave_planner_headers
):
    """Resolvable identifiers are not enough: an order whose confirmed reservation sits on the ten o'clock slot is refused by the van formed for the two o'clock slot, even though both slots serve the same route.

    Cites the requirement it rests on: "The order must be at `fulfillment_status`
    `SLOTTED`, and it must hold a slot booking in status `CONFIRMED` whose
    `delivery_slot_id` equals the wave's `delivery_slot_id`; if it does not, the
    request is refused with `ERR_WAVE_SLOT_MISMATCH`."

    Design: Corner/entities/flat_topology_wave_slot_cross_reference_integrity_rejected
    """
    site = _ambient_site(api)
    morning_slot = site["slot"]
    afternoon_slot = fixtures.create_delivery_slot(
        api,
        site["route"]["id"],
        window_start="2026-08-05T14:00:00.000Z",
        window_end="2026-08-05T16:00:00.000Z",
        total_capacity_units=10,
        withheld_units=0,
    )
    confirmed = fixtures.build_confirmed_order(
        api,
        site["route"]["id"],
        morning_slot["id"],
        [site["sku"]["id"]],
        ordered_qty=2,
        units=2,
    )
    wave = fixtures.create_delivery_wave(
        api,
        site["route"]["id"],
        afternoon_slot["id"],
        cutoff_at="2026-08-05T08:00:00.000Z",
    )

    validate_error(
        api.slot_orders(
            wave["id"],
            factories.slot_orders_payload(confirmed["order"]["id"]),
            wave_planner_headers,
        ),
        ApiError.WAVE_SLOT_MISMATCH.value,
    )

    unmoved_order = fixtures.read_order(
        api, confirmed["account"]["id"], confirmed["order"]["id"]
    )
    assert_order_statuses(
        unmoved_order, fulfillment_status=FulfillmentStatus.SLOTTED.value
    )
    assert_field_absent_or_null(unmoved_order, "wave_id")
    assert_int_field(fixtures.read_wave(api, wave["id"]), "order_count", 0)
    assert_status(
        fixtures.read_slot_booking(api, confirmed["booking"]["id"]),
        BookingStatus.CONFIRMED.value,
    )


def test_every_foreign_key_of_a_booked_basket_is_navigable_backwards(
    api, wave_planner_headers
):
    """Each parent in the site is reachable back to its children through the filtered collections — order to its lines and bookings, slot to its wave, zone to its SKUs, route to its shoppers and its slots — so no row is discoverable only by guessing an identifier.

    Cites the requirement it rests on: "Filtered list endpoints double as the
    reverse-reachability channel for every foreign key in the model."

    Design: Corner/entities/flat_topology_foreign_keys_are_reverse_reachable_by_filtered_lists
    """
    site = _ambient_site(api)
    basket = fixtures.build_shopper_with_basket(
        api, site["route"]["id"], [site["sku"]["id"]], ordered_qty=2
    )
    line = basket["lines"][0]
    booking = fixtures.create_slot_booking(
        api, basket["account"]["id"], site["slot"]["id"], basket["order"]["id"], units=2
    )
    wave = fixtures.create_delivery_wave(
        api,
        site["route"]["id"],
        site["slot"]["id"],
        cutoff_at="2026-08-05T08:00:00.000Z",
    )

    reverse_lookups = (
        (
            "order to its lines",
            api.list_order_lines(
                wave_planner_headers, params={"order_id": basket["order"]["id"]}
            ),
            line["id"],
        ),
        (
            "order to its bookings",
            api.list_slot_bookings(
                wave_planner_headers,
                params={"customer_order_id": basket["order"]["id"]},
            ),
            booking["id"],
        ),
        (
            "slot to its wave",
            api.list_delivery_waves(
                wave_planner_headers, params={"delivery_slot_id": site["slot"]["id"]}
            ),
            wave["id"],
        ),
        (
            "grid zone to its SKUs",
            api.list_inventory_skus(
                wave_planner_headers, params={"grid_zone_id": site["zone"]["id"]}
            ),
            site["sku"]["id"],
        ),
        (
            "route to its shoppers",
            api.list_customer_accounts(
                wave_planner_headers, params={"home_route_id": site["route"]["id"]}
            ),
            basket["account"]["id"],
        ),
        (
            "route to its slots",
            api.list_delivery_slots(
                wave_planner_headers, params={"route_id": site["route"]["id"]}
            ),
            site["slot"]["id"],
        ),
    )

    for label, response, expected_child_id in reverse_lookups:
        items, meta = list_items_and_meta(response)
        assert meta["total_count"] == 1, (
            f"{label}: expected exactly one child row, got {meta['total_count']}"
        )
        assert only_item(items)["id"] == expected_child_id, (
            f"{label}: the filtered collection returned the wrong child row"
        )


def test_reading_a_basket_line_back_returns_its_creation_body_unchanged(
    api, make_customer_headers, wave_planner_headers
):
    """Reading a basket line back returns the creation body field for field — the same provisional price, the same null pick outcome and the same version — and repeating the read, even from a different desk, moves neither the version nor the updated timestamp.

    Cites the requirement it rests on: "`version` is an integer that starts at 1
    when the resource is created and is incremented by exactly 1 on every mutation
    of that resource."

    Design: Corner/entities/read_back_of_an_order_line_is_field_for_field_identical_to_its_creation_response
    """
    site = _ambient_site(api)
    account = fixtures.create_customer_account(api, site["route"]["id"])
    shopper_headers = make_customer_headers(account["id"])
    order = fixtures.create_customer_order(api, account["id"])

    created = read_object(
        api.add_order_line(
            order["id"],
            factories.order_line_payload(site["sku"]["id"], ordered_qty=2),
            shopper_headers,
        ),
        expected_status=201,
    )
    assert created["order_id"] == order["id"]
    assert created["sku_id"] == site["sku"]["id"]
    assert_int_field(created, "ordered_qty", 2)
    assert_money(created, "provisional_line_price_cents", 1400)
    assert_status(created, LineStatus.PENDING.value, field="line_status")
    assert_status(
        created,
        SubstitutionResolution.NOT_REQUIRED.value,
        field="substitution_resolution",
    )
    for empty_field in (
        "final_line_price_cents",
        "picked_units",
        "picked_weight_grams",
    ):
        assert_field_absent_or_null(created, empty_field)
    assert_version_is(created, 1)
    assert_instant_equals(
        created["updated_at"], created["created_at"], label="line updated_at at creation"
    )

    shopper_read = read_object(api.get_order_line(created["id"], shopper_headers))
    planner_read = read_object(api.get_order_line(created["id"], wave_planner_headers))
    for label, fetched in (("shopper", shopper_read), ("planner", planner_read)):
        assert set(fetched) == set(created), (
            f"the {label} read returned a different set of fields than the creation body"
        )
        for field, expected in created.items():
            if field in ("created_at", "updated_at"):
                assert_instant_equals(
                    fetched[field], expected, label=f"{label} read {field}"
                )
            else:
                assert fetched[field] == expected, (
                    f"{label} read {field}: expected {expected!r}, "
                    f"got {fetched[field]!r}"
                )

    after_reads = read_object(api.get_order_line(created["id"], shopper_headers))
    assert_version_is(after_reads, created["version"])
    assert_instant_equals(
        after_reads["updated_at"], created["updated_at"], label="line updated_at"
    )

    priced_order = fixtures.read_order(api, account["id"], order["id"])
    assert_money(priced_order, "merchandise_subtotal_cents", 1400)
