"""Cycles, cascades and the order in which two broken rules report themselves.

The pick floor does not run in one direction only. A tote is closed once its
retrievals are done, reopened so a late substitute can still be dropped in, and
closed a second time, and the station it sits at counts one open tote, then
none, then one, then none again, flipping between ACTIVE and IDLE each way; a
shopper who has been slotted and authorized is pushed all the way back to a
draft basket with no money figures at all when the site administrator withholds
the capacity that booking was standing on, both status dimensions rewinding in
the same request; a single retrieval that comes back one unit light travels four
hops outwards, from the retrieval task to the order line, on to a freshly
synthesised substitution offer, into the shopper's charge waterfall and finally
out to the posture of the whole delivery wave; and when one request breaks two
rules at once — a finished retrieval bound to a tote of the wrong temperature
class, or a slot on the wrong route booked against a basket below the ten-dollar
minimum — only the earlier gate is allowed to speak.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_field_absent_or_null,
    assert_int_field,
    assert_money,
    assert_order_money,
    assert_order_statuses,
    assert_ratio,
    assert_sku_ledger,
    assert_slot_ledger,
    assert_status,
    assert_surge_multiplier,
    assert_wave_posture,
    only_item,
)
from test_helpers.types import (
    BillingStatus,
    BookingStatus,
    FulfillmentStatus,
    LineStatus,
    PickStationStatus,
    PickTaskStatus,
    ProposalStatus,
    SubstitutionResolution,
    TemperatureZone,
    ToteStatus,
    WavePosture,
    WaveStatus,
)


# ─── The tote's seal / unseal / reseal cycle ──────────────────────────────────


def test_a_tote_closes_reopens_and_closes_again_at_the_same_station(api):
    """The same tote runs OPEN -> SEALED -> OPEN -> SEALED while its station's open-tote count oscillates 1 -> 0 -> 1 -> 0.

    Cites the requirement it rests on: "Sealing releases the tote's slot at the
    station: the station's `current_tote_count` is decremented and its `status`
    is recomputed, becoming `IDLE` when the count reaches zero."

    Design: Difficulty/non_linear_state_machine/tote_reseal_after_unseal_repeats_the_cycle
    """
    plant = fixtures.build_plant(api, station={"max_concurrent_totes": 4})
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=20
    )
    picking = fixtures.build_picking_wave(
        api, plant["route"]["id"], slot["id"], [sku["id"]], ordered_qty=2, units=1
    )
    task = picking["tasks"][0]
    station_id = task["pick_station_id"]
    driven = fixtures.drive_task_to_retrieving(
        api,
        task["id"],
        picking["wave"]["id"],
        station_id,
        TemperatureZone.AMBIENT.value,
    )
    tote_id = driven["tote"]["id"]
    fixtures.complete_pick_task(api, task["id"], 2)

    station = fixtures.read_pick_station(api, station_id)
    assert_int_field(station, "current_tote_count", 1)
    assert_status(station, PickStationStatus.ACTIVE.value)

    first_seal = fixtures.seal_tote(api, tote_id)
    assert_status(first_seal, ToteStatus.SEALED.value)
    station = fixtures.read_pick_station(api, station_id)
    assert_int_field(station, "current_tote_count", 0)
    assert_status(station, PickStationStatus.IDLE.value)

    reopened = fixtures.unseal_tote(api, tote_id)
    assert_status(reopened, ToteStatus.OPEN.value)
    station = fixtures.read_pick_station(api, station_id)
    assert_int_field(station, "current_tote_count", 1)
    assert_status(station, PickStationStatus.ACTIVE.value)

    second_seal = fixtures.seal_tote(api, tote_id)
    assert_status(second_seal, ToteStatus.SEALED.value)
    assert_int_field(second_seal, "assigned_line_count", 1)
    station = fixtures.read_pick_station(api, station_id)
    assert_int_field(station, "current_tote_count", 0)
    assert_status(station, PickStationStatus.IDLE.value)

    wave = fixtures.read_wave(api, picking["wave"]["id"])
    assert_status(wave, WaveStatus.PICKING.value)
    assert_int_field(wave, "tote_count", 1)

    retrieval = fixtures.read_pick_task(api, task["id"])
    assert_status(retrieval, PickTaskStatus.COMPLETED.value)
    assert retrieval["tote_id"] == tote_id, "the reopened tote keeps its retrieval"

    line = fixtures.read_order_line(
        api, picking["account"]["id"], picking["lines"][0]["id"]
    )
    assert_status(line, LineStatus.PICKED.value, field="line_status")
    assert_money(line, "final_line_price_cents", 1400)


def test_sealing_a_tote_that_is_already_closed_is_rejected(api, pick_operator_headers):
    """The reseal must travel back through a reopening, so a tote already SEALED has no sealing transition left.

    Cites the requirement it rests on: "The target resource is in a state from
    which the requested transition exists, and every precondition of that
    transition that concerns the target resource itself holds — for instance a
    tote must be `OPEN` to be sealed, a retrieval task must be `RETRIEVING` to be
    completed, a wave must be `CONSOLIDATED` to be sequenced for loading, and a
    booking must be `HELD` to be confirmed."

    Design: Difficulty/non_linear_state_machine/tote_reseal_after_unseal_repeats_the_cycle
    """
    plant = fixtures.build_plant(api, station={"max_concurrent_totes": 4})
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=20
    )
    picking = fixtures.build_picking_wave(
        api, plant["route"]["id"], slot["id"], [sku["id"]], ordered_qty=2, units=1
    )
    task = picking["tasks"][0]
    station_id = task["pick_station_id"]
    driven = fixtures.drive_task_to_retrieving(
        api,
        task["id"],
        picking["wave"]["id"],
        station_id,
        TemperatureZone.AMBIENT.value,
    )
    tote_id = driven["tote"]["id"]
    fixtures.complete_pick_task(api, task["id"], 2)
    fixtures.seal_tote(api, tote_id)

    response = api.seal_tote(tote_id, pick_operator_headers)
    validate_error(response, ApiError.INVALID_STATE.value)

    tote = fixtures.read_tote(api, tote_id)
    assert_status(tote, ToteStatus.SEALED.value)
    station = fixtures.read_pick_station(api, station_id)
    assert_int_field(station, "current_tote_count", 0)
    assert_status(station, PickStationStatus.IDLE.value)


def test_reopening_a_tote_that_is_still_open_is_rejected(api, pick_operator_headers):
    """The back edge runs only from SEALED, so a tote that has never been closed cannot be reopened.

    Cites the requirement it rests on: "Unsealing increments the station's
    `current_tote_count` and recomputes the station's `status`, moving it from
    `IDLE` back to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/tote_reseal_after_unseal_repeats_the_cycle
    """
    plant = fixtures.build_plant(api, station={"max_concurrent_totes": 4})
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=20
    )
    picking = fixtures.build_picking_wave(
        api, plant["route"]["id"], slot["id"], [sku["id"]], ordered_qty=2, units=1
    )
    task = picking["tasks"][0]
    station_id = task["pick_station_id"]
    driven = fixtures.drive_task_to_retrieving(
        api,
        task["id"],
        picking["wave"]["id"],
        station_id,
        TemperatureZone.AMBIENT.value,
    )
    tote_id = driven["tote"]["id"]

    response = api.unseal_tote(tote_id, pick_operator_headers)
    validate_error(response, ApiError.INVALID_STATE.value)

    tote = fixtures.read_tote(api, tote_id)
    assert_status(tote, ToteStatus.OPEN.value)
    station = fixtures.read_pick_station(api, station_id)
    assert_int_field(station, "current_tote_count", 1)
    assert_status(station, PickStationStatus.ACTIVE.value)


def test_reopening_a_tote_at_a_full_station_is_rejected(api, pick_operator_headers):
    """A sealed tote may only come back open while its station still has a free slot for it.

    Cites the requirement it rests on: "and the station must have room, since a
    station whose `current_tote_count` has reached its `max_concurrent_totes`
    refuses the reopening with `ERR_STATION_TOTE_CAPACITY_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/tote_reseal_after_unseal_repeats_the_cycle
    """
    plant = fixtures.build_plant(api, station={"max_concurrent_totes": 1})
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=20
    )
    picking = fixtures.build_picking_wave(
        api, plant["route"]["id"], slot["id"], [sku["id"]], ordered_qty=2, units=1
    )
    task = picking["tasks"][0]
    station_id = task["pick_station_id"]
    driven = fixtures.drive_task_to_retrieving(
        api,
        task["id"],
        picking["wave"]["id"],
        station_id,
        TemperatureZone.AMBIENT.value,
    )
    first_tote_id = driven["tote"]["id"]
    fixtures.complete_pick_task(api, task["id"], 2)
    fixtures.seal_tote(api, first_tote_id)

    fixtures.create_tote(
        api,
        picking["wave"]["id"],
        station_id,
        temperature_zone=TemperatureZone.AMBIENT.value,
    )
    station = fixtures.read_pick_station(api, station_id)
    assert_int_field(station, "current_tote_count", 1)

    response = api.unseal_tote(first_tote_id, pick_operator_headers)
    validate_error(response, ApiError.STATION_TOTE_CAPACITY_EXCEEDED.value)

    tote = fixtures.read_tote(api, first_tote_id)
    assert_status(tote, ToteStatus.SEALED.value)
    station = fixtures.read_pick_station(api, station_id)
    assert_int_field(station, "current_tote_count", 1)
    assert_status(station, PickStationStatus.ACTIVE.value)


# ─── Both order dimensions rewind when capacity is withheld ───────────────────


def test_withholding_capacity_rewinds_both_order_dimensions_to_their_start(api):
    """A bumped booking drags its order backwards on both dimensions at once and empties every money figure.

    Cites the requirement it rests on: "Each bumped booking advances
    `CONFIRMED → BUMPED`, and its order falls back on both dimensions:
    `fulfillment_status` goes `SLOTTED → DRAFT`, `billing_status` goes
    `AUTHORIZED → PENDING_AUTH`, `authorized_amount_cents` reverts to null, and
    because the order no longer holds a booking in `HELD` or `CONFIRMED`, the
    waterfall's step 2 now stops early, so `delivery_fee_cents`,
    `loyalty_discount_cents` and `order_total_cents` all revert to null as well."

    Design: Difficulty/non_linear_state_machine/order_status_dimensions_rewind_on_capacity_bump
    """
    plant = fixtures.build_plant(api, route={"base_delivery_fee_cents": 599})
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=10
    )
    confirmed = fixtures.build_confirmed_order(
        api, plant["route"]["id"], slot["id"], [sku["id"]], ordered_qty=2, units=5
    )
    booking = confirmed["booking"]
    assert_ratio(booking, "surge_multiplier_at_booking", 1.00, places=2)
    assert_money(booking, "quoted_fee_cents", 599)
    assert_order_statuses(
        confirmed["order"],
        fulfillment_status=FulfillmentStatus.SLOTTED.value,
        billing_status=BillingStatus.AUTHORIZED.value,
    )
    assert_order_money(
        confirmed["order"],
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=599,
        loyalty_discount_cents=0,
        order_total_cents=1999,
        authorized_amount_cents=1999,
    )
    assert_slot_ledger(
        fixtures.read_delivery_slot(api, slot["id"]),
        total_capacity_units=10,
        withheld_units=0,
        held_units=0,
        confirmed_units=5,
        available_units=5,
    )

    fixtures.withhold_capacity(api, slot["id"], 8)

    assert_status(
        fixtures.read_slot_booking(api, booking["id"]), BookingStatus.BUMPED.value
    )
    rewound = fixtures.read_order(api, confirmed["account"]["id"],
                                 confirmed["order"]["id"])
    assert_order_statuses(
        rewound,
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )
    assert_money(rewound, "merchandise_subtotal_cents", 1400)
    assert_field_absent_or_null(rewound, "delivery_fee_cents")
    assert_field_absent_or_null(rewound, "loyalty_discount_cents")
    assert_field_absent_or_null(rewound, "order_total_cents")
    assert_field_absent_or_null(rewound, "authorized_amount_cents")
    assert_field_absent_or_null(rewound, "captured_amount_cents")

    reduced = fixtures.read_delivery_slot(api, slot["id"])
    assert_slot_ledger(
        reduced,
        total_capacity_units=10,
        withheld_units=8,
        held_units=0,
        confirmed_units=0,
        available_units=2,
    )
    assert_surge_multiplier(reduced, 1.00)


def test_withholding_that_fits_inside_the_available_capacity_bumps_nobody(api):
    """A withholding the slot can absorb leaves the shopper slotted and authorized with every money figure intact.

    Cites the requirement it rests on: "Zero bookings may be bumped, if the
    withholding fits inside what was available."

    Design: Difficulty/non_linear_state_machine/order_status_dimensions_rewind_on_capacity_bump
    """
    plant = fixtures.build_plant(api, route={"base_delivery_fee_cents": 599})
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=10
    )
    confirmed = fixtures.build_confirmed_order(
        api, plant["route"]["id"], slot["id"], [sku["id"]], ordered_qty=2, units=5
    )

    fixtures.withhold_capacity(api, slot["id"], 5)

    assert_status(
        fixtures.read_slot_booking(api, confirmed["booking"]["id"]),
        BookingStatus.CONFIRMED.value,
    )
    untouched = fixtures.read_order(
        api, confirmed["account"]["id"], confirmed["order"]["id"]
    )
    assert_order_statuses(
        untouched,
        fulfillment_status=FulfillmentStatus.SLOTTED.value,
        billing_status=BillingStatus.AUTHORIZED.value,
    )
    assert_order_money(
        untouched,
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=599,
        loyalty_discount_cents=0,
        order_total_cents=1999,
        authorized_amount_cents=1999,
    )

    tightened = fixtures.read_delivery_slot(api, slot["id"])
    assert_slot_ledger(
        tightened,
        total_capacity_units=10,
        withheld_units=5,
        held_units=0,
        confirmed_units=5,
        available_units=0,
    )
    assert_surge_multiplier(tightened, 1.35)


def test_a_waved_shopper_is_never_bumped_even_when_capacity_goes_negative(api):
    """An order already attached to a wave keeps its confirmed booking and both statuses while the slot goes overcommitted.

    Cites the requirement it rests on: "A booking whose order has already been
    waved is never bumped: a waved order is past the point of no return."

    Design: Difficulty/non_linear_state_machine/order_status_dimensions_rewind_on_capacity_bump
    """
    plant = fixtures.build_plant(api, route={"base_delivery_fee_cents": 599})
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=10
    )
    waved = fixtures.build_waved_order(
        api, plant["route"]["id"], slot["id"], [sku["id"]], ordered_qty=2, units=5
    )
    assert_order_statuses(
        waved["order"], fulfillment_status=FulfillmentStatus.WAVED.value
    )

    fixtures.withhold_capacity(api, slot["id"], 8)

    assert_status(
        fixtures.read_slot_booking(api, waved["booking"]["id"]),
        BookingStatus.CONFIRMED.value,
    )
    protected = fixtures.read_order(api, waved["account"]["id"], waved["order"]["id"])
    assert_order_statuses(
        protected,
        fulfillment_status=FulfillmentStatus.WAVED.value,
        billing_status=BillingStatus.AUTHORIZED.value,
    )
    assert_order_money(
        protected,
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=599,
        order_total_cents=1999,
        authorized_amount_cents=1999,
    )
    assert protected["wave_id"] == waved["wave"]["id"], "the order stays in its wave"

    overcommitted = fixtures.read_delivery_slot(api, slot["id"])
    assert_slot_ledger(
        overcommitted,
        total_capacity_units=10,
        withheld_units=8,
        held_units=0,
        confirmed_units=5,
        available_units=-3,
    )


# ─── One short pick travelling four hops out to the wave's posture ────────────


def test_a_short_pick_travels_out_to_the_wave_posture_in_one_request(api):
    """One retrieval coming back light moves the task, the line, a freshly offered substitute, the order's money and the wave's posture together.

    Cites the requirement it rests on: "Because a member order has become
    dispatch-blocked, the wave's posture is recomputed and moves
    `OPEN → RESTRICTED`, which is what will later stop the loading sequence."

    Design: Difficulty/transitive_cascade/short_pick_cascade_to_wave_posture
    """
    plant = fixtures.build_plant(api, route={"base_delivery_fee_cents": 599})
    ordered_sku = fixtures.create_inventory_sku(
        api,
        plant["zone"]["id"],
        substitution_group_code="MINCE",
        unit_price_cents=700,
        physical_units=5,
    )
    nearest_substitute = fixtures.create_inventory_sku(
        api,
        plant["zone"]["id"],
        substitution_group_code="MINCE",
        unit_price_cents=900,
        physical_units=50,
    )
    fixtures.create_inventory_sku(
        api,
        plant["zone"]["id"],
        substitution_group_code="MINCE",
        unit_price_cents=1000,
        physical_units=50,
    )
    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=10
    )
    picking = fixtures.build_picking_wave(
        api,
        plant["route"]["id"],
        slot["id"],
        [ordered_sku["id"]],
        ordered_qty=2,
        units=1,
    )
    task = picking["tasks"][0]
    fixtures.drive_task_to_retrieving(
        api,
        task["id"],
        picking["wave"]["id"],
        task["pick_station_id"],
        TemperatureZone.AMBIENT.value,
    )

    short_task = fixtures.complete_pick_task(api, task["id"], 1)

    assert_status(short_task, PickTaskStatus.SHORT.value)
    assert_int_field(short_task, "picked_units", 1)

    line = fixtures.read_order_line(
        api, picking["account"]["id"], picking["lines"][0]["id"]
    )
    assert_status(line, LineStatus.SHORT.value, field="line_status")
    assert_status(
        line,
        SubstitutionResolution.PENDING.value,
        field="substitution_resolution",
    )
    assert_field_absent_or_null(line, "final_line_price_cents")

    offer = only_item(
        fixtures.list_substitution_proposals(api, order_line_id=line["id"])
    )
    assert_status(offer, ProposalStatus.DRAFT.value)
    assert offer["substitute_sku_id"] == nearest_substitute["id"], (
        "the substitute closest in price to the ordered item must be offered"
    )
    assert_int_field(offer, "round_no", 1)
    assert_money(offer, "proposed_price_delta_cents", 400)
    assert_field_absent_or_null(offer, "expires_at")
    assert_field_absent_or_null(offer, "supersedes_proposal_id")

    order = fixtures.read_order(api, picking["account"]["id"], picking["order"]["id"])
    assert order["dispatch_blocked"] is True, "the shortage blocks the order"
    assert_int_field(order, "open_substitution_count", 1)
    assert_order_money(
        order,
        merchandise_subtotal_cents=0,
        delivery_fee_cents=599,
        loyalty_discount_cents=0,
        order_total_cents=599,
        authorized_amount_cents=1999,
    )
    assert_order_statuses(order, billing_status=BillingStatus.ADJUSTED.value)

    wave = fixtures.read_wave(api, picking["wave"]["id"])
    assert_wave_posture(wave, WavePosture.RESTRICTED.value)
    assert_status(wave, WaveStatus.PICKING.value)

    assert_sku_ledger(
        fixtures.read_inventory_sku(api, ordered_sku["id"]),
        physical_units=4,
        allocated_units=0,
        on_hand_units=4,
    )


def test_a_shortage_with_no_comparable_substitute_still_restricts_the_wave(api):
    """When the catalogue offers nothing interchangeable, no offer is synthesised yet the order stays blocked and the wave restricted.

    Cites the requirement it rests on: "If no candidate qualifies at all, no
    proposal is created: the line keeps `substitution_resolution` `PENDING`, so
    the order stays dispatch-blocked, and the shopper's only way forward is to
    accept the shortage."

    Design: Difficulty/transitive_cascade/short_pick_cascade_to_wave_posture
    """
    plant = fixtures.build_plant(api, route={"base_delivery_fee_cents": 599})
    lonely_sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=10
    )
    short = fixtures.build_short_line(
        api,
        plant["route"]["id"],
        slot["id"],
        [lonely_sku["id"]],
        ordered_qty=2,
        picked_units=1,
    )

    assert fixtures.list_substitution_proposals(
        api, order_line_id=short["line"]["id"]
    ) == [], "no substitute exists, so no offer may be created"

    line = fixtures.read_order_line(api, short["account"]["id"], short["line"]["id"])
    assert_status(line, LineStatus.SHORT.value, field="line_status")
    assert_status(
        line,
        SubstitutionResolution.PENDING.value,
        field="substitution_resolution",
    )

    order = fixtures.read_order(api, short["account"]["id"], short["order"]["id"])
    assert order["dispatch_blocked"] is True, "the unresolved shortage still blocks"
    assert_int_field(order, "open_substitution_count", 0)
    assert_order_money(
        order,
        merchandise_subtotal_cents=0,
        order_total_cents=599,
        authorized_amount_cents=1999,
    )
    assert_order_statuses(order, billing_status=BillingStatus.ADJUSTED.value)

    assert_wave_posture(
        fixtures.read_wave(api, short["wave"]["id"]), WavePosture.RESTRICTED.value
    )


def test_a_retrieval_picked_in_full_sets_off_no_cascade_at_all(api):
    """A retrieval that brings back every allocated unit prices the line, offers no substitute and leaves the wave open.

    Cites the requirement it rests on: "When `picked_units` equals the task's
    `allocated_units`, the task advances `RETRIEVING → COMPLETED` and the line
    advances `PENDING → PICKED`"

    Design: Difficulty/transitive_cascade/short_pick_cascade_to_wave_posture
    """
    plant = fixtures.build_plant(api, route={"base_delivery_fee_cents": 599})
    ordered_sku = fixtures.create_inventory_sku(
        api,
        plant["zone"]["id"],
        substitution_group_code="MINCE",
        unit_price_cents=700,
        physical_units=100,
    )
    fixtures.create_inventory_sku(
        api,
        plant["zone"]["id"],
        substitution_group_code="MINCE",
        unit_price_cents=900,
        physical_units=50,
    )
    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=10
    )
    picking = fixtures.build_picking_wave(
        api,
        plant["route"]["id"],
        slot["id"],
        [ordered_sku["id"]],
        ordered_qty=2,
        units=1,
    )
    task = picking["tasks"][0]
    fixtures.drive_task_to_retrieving(
        api,
        task["id"],
        picking["wave"]["id"],
        task["pick_station_id"],
        TemperatureZone.AMBIENT.value,
    )

    completed = fixtures.complete_pick_task(api, task["id"], 2)

    assert_status(completed, PickTaskStatus.COMPLETED.value)
    line = fixtures.read_order_line(
        api, picking["account"]["id"], picking["lines"][0]["id"]
    )
    assert_status(line, LineStatus.PICKED.value, field="line_status")
    assert_status(
        line,
        SubstitutionResolution.NOT_REQUIRED.value,
        field="substitution_resolution",
    )
    assert_money(line, "final_line_price_cents", 1400)
    assert_int_field(line, "picked_units", 2)

    assert fixtures.list_substitution_proposals(
        api, order_line_id=line["id"]
    ) == [], "a full pick needs no substitute"

    order = fixtures.read_order(api, picking["account"]["id"], picking["order"]["id"])
    assert order["dispatch_blocked"] is False, "a full pick blocks nothing"
    assert_int_field(order, "open_substitution_count", 0)
    assert_order_money(
        order,
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=599,
        order_total_cents=1999,
        authorized_amount_cents=1999,
    )
    assert_order_statuses(order, billing_status=BillingStatus.AUTHORIZED.value)

    assert_wave_posture(
        fixtures.read_wave(api, picking["wave"]["id"]), WavePosture.OPEN.value
    )
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, ordered_sku["id"]),
        physical_units=98,
        allocated_units=0,
        on_hand_units=98,
    )


# ─── One shopper walking away slots a different shopper's groceries ───────────


def test_one_shopper_cancelling_slots_the_shopper_waiting_behind_them(api):
    """A cancellation releases the booking, frees the capacity, drains the waitlist and authorizes a completely different shopper's money.

    Cites the requirement it rests on: "The winning booking advances
    `WAITLISTED → CONFIRMED`, and because that booking is now confirmed its own
    customer order advances `fulfillment_status` `DRAFT → SLOTTED` and
    `billing_status` `PENDING_AUTH → AUTHORIZED`, with
    `authorized_amount_cents` snapshotted from *that* order's
    `order_total_cents`."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_to_waitlist_promotion
    """
    plant = fixtures.build_plant(api, route={"base_delivery_fee_cents": 599})
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700
    )
    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=20
    )
    leaving = fixtures.build_confirmed_order(
        api,
        plant["route"]["id"],
        slot["id"],
        [sku["id"]],
        ordered_qty=2,
        units=10,
    )
    waiting = fixtures.build_shopper_with_basket(
        api, plant["route"]["id"], [sku["id"]], ordered_qty=2
    )
    waiting_booking = fixtures.create_slot_booking(
        api,
        waiting["account"]["id"],
        slot["id"],
        waiting["order"]["id"],
        units=11,
    )
    assert_status(waiting_booking, BookingStatus.WAITLISTED.value)
    assert_order_statuses(
        fixtures.read_order(api, waiting["account"]["id"], waiting["order"]["id"]),
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )

    fixtures.cancel_customer_order(
        api, leaving["account"]["id"], leaving["order"]["id"]
    )

    cancelled = fixtures.read_order(
        api, leaving["account"]["id"], leaving["order"]["id"]
    )
    assert_order_statuses(
        cancelled,
        fulfillment_status=FulfillmentStatus.CANCELLED.value,
        billing_status=BillingStatus.REVERSED.value,
    )
    assert_money(cancelled, "authorized_amount_cents", 1999)
    assert_field_absent_or_null(cancelled, "captured_amount_cents")
    assert_status(
        fixtures.read_order_line(
            api, leaving["account"]["id"], leaving["lines"][0]["id"]
        ),
        LineStatus.CANCELLED.value,
        field="line_status",
    )
    assert_status(
        fixtures.read_slot_booking(api, leaving["booking"]["id"]),
        BookingStatus.RELEASED.value,
    )

    promoted = fixtures.read_slot_booking(api, waiting_booking["id"])
    assert_status(promoted, BookingStatus.CONFIRMED.value)
    assert_int_field(promoted, "units", 11)
    assert_ratio(promoted, "surge_multiplier_at_booking", 1.00, places=2)
    assert_money(promoted, "quoted_fee_cents", 599)

    slotted = fixtures.read_order(
        api, waiting["account"]["id"], waiting["order"]["id"]
    )
    assert_order_statuses(
        slotted,
        fulfillment_status=FulfillmentStatus.SLOTTED.value,
        billing_status=BillingStatus.AUTHORIZED.value,
    )
    assert_order_money(
        slotted,
        merchandise_subtotal_cents=1400,
        delivery_fee_cents=599,
        loyalty_discount_cents=0,
        order_total_cents=1999,
        authorized_amount_cents=1999,
    )

    after = fixtures.read_delivery_slot(api, slot["id"])
    assert_slot_ledger(
        after,
        total_capacity_units=20,
        withheld_units=0,
        held_units=0,
        confirmed_units=11,
        available_units=9,
    )
    assert_surge_multiplier(after, 1.00)


def test_a_basket_too_big_for_the_freed_capacity_is_passed_over(api):
    """A shopper waiting for more units than the cancellation frees keeps waiting rather than being partially admitted.

    Cites the requirement it rests on: "The eligible candidates are that slot's
    bookings whose status is `WAITLISTED` and whose `units` are less than or
    equal to the slot's freshly recomputed `available_units`; a waitlisted
    booking larger than the freed capacity is passed over rather than partially
    filled."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_to_waitlist_promotion
    """
    plant = fixtures.build_plant(api, route={"base_delivery_fee_cents": 599})
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700
    )
    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=20
    )
    leaving = fixtures.build_confirmed_order(
        api,
        plant["route"]["id"],
        slot["id"],
        [sku["id"]],
        ordered_qty=2,
        units=10,
    )
    hopeful = fixtures.build_shopper_with_basket(
        api, plant["route"]["id"], [sku["id"]], ordered_qty=2
    )
    hopeful_booking = fixtures.create_slot_booking(
        api,
        hopeful["account"]["id"],
        slot["id"],
        hopeful["order"]["id"],
        units=18,
    )
    assert_status(hopeful_booking, BookingStatus.WAITLISTED.value)
    fixtures.build_confirmed_order(
        api,
        plant["route"]["id"],
        slot["id"],
        [sku["id"]],
        ordered_qty=2,
        units=5,
    )

    fixtures.cancel_customer_order(
        api, leaving["account"]["id"], leaving["order"]["id"]
    )

    still_waiting = fixtures.read_slot_booking(api, hopeful_booking["id"])
    assert_status(still_waiting, BookingStatus.WAITLISTED.value)
    assert_int_field(still_waiting, "units", 18)

    assert_order_statuses(
        fixtures.read_order(api, hopeful["account"]["id"], hopeful["order"]["id"]),
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )

    after = fixtures.read_delivery_slot(api, slot["id"])
    assert_slot_ledger(
        after,
        total_capacity_units=20,
        withheld_units=0,
        held_units=0,
        confirmed_units=5,
        available_units=15,
    )
    assert_surge_multiplier(after, 1.00)


def test_only_the_first_waiting_shopper_is_admitted_even_when_two_would_fit(api):
    """Freed capacity roomy enough for both waiting baskets still admits exactly one of them.

    Cites the requirement it rests on: "Exactly one booking is promoted per
    request — at most one, never two, even when the freed capacity would
    comfortably admit a second — and the promotion then stops."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_to_waitlist_promotion
    """
    plant = fixtures.build_plant(api, route={"base_delivery_fee_cents": 599})
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700
    )
    slot = fixtures.create_delivery_slot(
        api, plant["route"]["id"], total_capacity_units=20
    )
    leaving = fixtures.build_confirmed_order(
        api,
        plant["route"]["id"],
        slot["id"],
        [sku["id"]],
        ordered_qty=2,
        units=18,
    )
    first_in_line = fixtures.build_shopper_with_basket(
        api, plant["route"]["id"], [sku["id"]], ordered_qty=2
    )
    first_booking = fixtures.create_slot_booking(
        api,
        first_in_line["account"]["id"],
        slot["id"],
        first_in_line["order"]["id"],
        units=6,
    )
    second_in_line = fixtures.build_shopper_with_basket(
        api, plant["route"]["id"], [sku["id"]], ordered_qty=2
    )
    second_booking = fixtures.create_slot_booking(
        api,
        second_in_line["account"]["id"],
        slot["id"],
        second_in_line["order"]["id"],
        units=5,
    )
    assert_status(first_booking, BookingStatus.WAITLISTED.value)
    assert_status(second_booking, BookingStatus.WAITLISTED.value)

    fixtures.cancel_customer_order(
        api, leaving["account"]["id"], leaving["order"]["id"]
    )

    assert_order_statuses(
        fixtures.read_order(api, leaving["account"]["id"], leaving["order"]["id"]),
        fulfillment_status=FulfillmentStatus.CANCELLED.value,
        billing_status=BillingStatus.REVERSED.value,
    )

    assert_status(
        fixtures.read_slot_booking(api, first_booking["id"]),
        BookingStatus.CONFIRMED.value,
    )
    promoted_order = fixtures.read_order(
        api, first_in_line["account"]["id"], first_in_line["order"]["id"]
    )
    assert_order_statuses(
        promoted_order,
        fulfillment_status=FulfillmentStatus.SLOTTED.value,
        billing_status=BillingStatus.AUTHORIZED.value,
    )
    assert promoted_order["authorized_amount_cents"] == promoted_order[
        "order_total_cents"
    ], "the promoted shopper is authorized for their own order total"

    assert_status(
        fixtures.read_slot_booking(api, second_booking["id"]),
        BookingStatus.WAITLISTED.value,
    )
    assert_order_statuses(
        fixtures.read_order(
            api, second_in_line["account"]["id"], second_in_line["order"]["id"]
        ),
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )

    after = fixtures.read_delivery_slot(api, slot["id"])
    assert_slot_ledger(
        after,
        total_capacity_units=20,
        withheld_units=0,
        held_units=0,
        confirmed_units=6,
        available_units=14,
    )
    assert_surge_multiplier(after, 1.00)


# ─── Which of two broken guards speaks first when a tote is bound ─────────────


def test_binding_a_finished_task_to_a_cold_tote_reports_the_state_fault(
    api, pick_operator_headers
):
    """A retrieval that is no longer waiting to be picked and a tote of the wrong temperature class are both wrong, and the operator hears about the retrieval.

    Cites the requirement it rests on: "First, the state check at position 11
    outranks the cold-chain check at position 14: binding a retrieval task that
    is not `QUEUED` to a tote of the wrong temperature class reports
    `ERR_INVALID_STATE`, not `ERR_TEMPERATURE_ZONE_MISMATCH`, because the state
    violation is found first."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_assign_tote
    """
    plant = fixtures.build_plant(api)
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    picking = fixtures.build_picking_wave(
        api, plant["route"]["id"], slot["id"], [sku["id"]], ordered_qty=2, units=1
    )
    task = picking["tasks"][0]
    cancelled = fixtures.cancel_pick_task(api, task["id"])
    assert_status(cancelled, PickTaskStatus.CANCELLED.value)
    assert_field_absent_or_null(cancelled, "tote_id")
    frozen_tote = fixtures.create_tote(
        api,
        picking["wave"]["id"],
        task["pick_station_id"],
        temperature_zone=TemperatureZone.FROZEN.value,
    )

    validate_error(
        api.assign_tote(
            task["id"],
            factories.assign_tote_payload(frozen_tote["id"]),
            pick_operator_headers,
        ),
        ApiError.INVALID_STATE.value,
    )


def test_binding_a_queued_task_to_a_cold_tote_reports_the_cold_chain_fault(
    api, pick_operator_headers
):
    """With the retrieval still waiting to be picked, the only broken guard is cold-chain segregation and it is the one reported.

    Cites the requirement it rests on: "And cold-chain segregation applies: the
    tote's `temperature_zone` must equal the `temperature_zone` of the SKU
    actually being retrieved, or the request is refused with
    `ERR_TEMPERATURE_ZONE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_assign_tote
    """
    plant = fixtures.build_plant(api)
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    picking = fixtures.build_picking_wave(
        api, plant["route"]["id"], slot["id"], [sku["id"]], ordered_qty=2, units=1
    )
    task = picking["tasks"][0]
    assert_status(task, PickTaskStatus.QUEUED.value)
    frozen_tote = fixtures.create_tote(
        api,
        picking["wave"]["id"],
        task["pick_station_id"],
        temperature_zone=TemperatureZone.FROZEN.value,
    )

    validate_error(
        api.assign_tote(
            task["id"],
            factories.assign_tote_payload(frozen_tote["id"]),
            pick_operator_headers,
        ),
        ApiError.TEMPERATURE_ZONE_MISMATCH.value,
    )

    assert_field_absent_or_null(
        fixtures.read_pick_task(api, task["id"]), "tote_id"
    )


def test_binding_a_finished_task_to_a_matching_tote_still_reports_the_state_fault(
    api, pick_operator_headers
):
    """A retrieval that is no longer waiting to be picked cannot be bound even to a tote of exactly the right temperature class.

    Cites the requirement it rests on: "The task must be `QUEUED` and must not
    already hold a tote, since binding a task that already has one is refused
    with `ERR_TOTE_NOT_ASSIGNED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_assign_tote
    """
    plant = fixtures.build_plant(api)
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    picking = fixtures.build_picking_wave(
        api, plant["route"]["id"], slot["id"], [sku["id"]], ordered_qty=2, units=1
    )
    task = picking["tasks"][0]
    fixtures.cancel_pick_task(api, task["id"])
    matching_tote = fixtures.create_tote(
        api,
        picking["wave"]["id"],
        task["pick_station_id"],
        temperature_zone=TemperatureZone.AMBIENT.value,
    )

    validate_error(
        api.assign_tote(
            task["id"],
            factories.assign_tote_payload(matching_tote["id"]),
            pick_operator_headers,
        ),
        ApiError.INVALID_STATE.value,
    )

    assert_int_field(
        fixtures.read_tote(api, matching_tote["id"]), "assigned_line_count", 0
    )


def test_binding_a_queued_task_to_a_matching_tote_is_accepted(api):
    """With both guards satisfied the retrieval takes the tote and stays waiting to be picked.

    Cites the requirement it rests on: "On success the task's `tote_id` is set
    and the tote's `assigned_line_count` is recomputed."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_assign_tote
    """
    plant = fixtures.build_plant(api)
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    picking = fixtures.build_picking_wave(
        api, plant["route"]["id"], slot["id"], [sku["id"]], ordered_qty=2, units=1
    )
    task = picking["tasks"][0]
    matching_tote = fixtures.create_tote(
        api,
        picking["wave"]["id"],
        task["pick_station_id"],
        temperature_zone=TemperatureZone.AMBIENT.value,
    )

    bound = fixtures.assign_tote(api, task["id"], matching_tote["id"])

    assert_status(bound, PickTaskStatus.QUEUED.value)
    assert bound["tote_id"] == matching_tote["id"], (
        "the bound tote is recorded on the retrieval"
    )
    assert_int_field(
        fixtures.read_tote(api, matching_tote["id"]), "assigned_line_count", 1
    )
    assert_status(
        fixtures.read_tote(api, matching_tote["id"]), ToteStatus.OPEN.value
    )


# ─── Which of two broken guards speaks first when a slot is booked ────────────


def test_a_thin_basket_on_a_foreign_route_reports_the_route_fault(
    api, make_customer_headers
):
    """A shopper reaching for a slot on somebody else's route with too little in the trolley hears about the route, never about the trolley.

    Cites the requirement it rests on: "Second, the route check at position 18
    outranks the minimum-basket check at position 33: a shopper booking a slot
    on a route that is not their home route, with a basket below the minimum,
    receives `ERR_ROUTE_MISMATCH` and never sees `ERR_MINIMUM_ORDER_NOT_MET`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_slot_booking
    """
    plant = fixtures.build_plant(api)
    neighbouring_route = fixtures.create_delivery_route(api)
    foreign_slot = fixtures.create_delivery_slot(api, neighbouring_route["id"])
    cheap_sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=250
    )
    shopper = fixtures.build_shopper_with_basket(
        api, plant["route"]["id"], [cheap_sku["id"]], ordered_qty=1
    )
    basket = fixtures.read_order(
        api, shopper["account"]["id"], shopper["order"]["id"]
    )
    assert_money(basket, "merchandise_subtotal_cents", 250)

    validate_error(
        api.create_slot_booking(
            factories.slot_booking_payload(
                foreign_slot["id"], basket["id"], basket["version"]
            ),
            make_customer_headers(shopper["account"]["id"]),
        ),
        ApiError.ROUTE_MISMATCH.value,
    )

    assert_slot_ledger(
        fixtures.read_delivery_slot(api, foreign_slot["id"]),
        held_units=0,
        confirmed_units=0,
    )


def test_a_full_basket_on_a_foreign_route_still_reports_the_route_fault(
    api, make_customer_headers
):
    """A trolley well over the minimum does not buy a shopper a slot on a route that is not theirs.

    Cites the requirement it rests on: "The slot's route must be the shopper's
    home route, or the request is refused with `ERR_ROUTE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_slot_booking
    """
    plant = fixtures.build_plant(api)
    neighbouring_route = fixtures.create_delivery_route(api)
    foreign_slot = fixtures.create_delivery_slot(api, neighbouring_route["id"])
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700
    )
    shopper = fixtures.build_shopper_with_basket(
        api, plant["route"]["id"], [sku["id"]], ordered_qty=2
    )
    basket = fixtures.read_order(
        api, shopper["account"]["id"], shopper["order"]["id"]
    )
    assert_money(basket, "merchandise_subtotal_cents", 1400)

    validate_error(
        api.create_slot_booking(
            factories.slot_booking_payload(
                foreign_slot["id"], basket["id"], basket["version"]
            ),
            make_customer_headers(shopper["account"]["id"]),
        ),
        ApiError.ROUTE_MISMATCH.value,
    )

    assert_order_statuses(
        fixtures.read_order(api, shopper["account"]["id"], basket["id"]),
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )


def test_a_thin_basket_on_the_home_route_reports_the_minimum_basket_fault(
    api, make_customer_headers
):
    """With the route correct, the minimum-basket guard is the one left to fail and it is the one reported.

    Cites the requirement it rests on: "The basket must be worth at least ten
    dollars — 1,000 cents of `merchandise_subtotal_cents` — or the request is
    refused with `ERR_MINIMUM_ORDER_NOT_MET`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_slot_booking
    """
    plant = fixtures.build_plant(api)
    home_slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    cheap_sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=250
    )
    shopper = fixtures.build_shopper_with_basket(
        api, plant["route"]["id"], [cheap_sku["id"]], ordered_qty=1
    )
    basket = fixtures.read_order(
        api, shopper["account"]["id"], shopper["order"]["id"]
    )
    assert_money(basket, "merchandise_subtotal_cents", 250)

    validate_error(
        api.create_slot_booking(
            factories.slot_booking_payload(
                home_slot["id"], basket["id"], basket["version"]
            ),
            make_customer_headers(shopper["account"]["id"]),
        ),
        ApiError.MINIMUM_ORDER_NOT_MET.value,
    )

    assert_slot_ledger(
        fixtures.read_delivery_slot(api, home_slot["id"]),
        held_units=0,
        confirmed_units=0,
    )
    assert_order_statuses(
        fixtures.read_order(api, shopper["account"]["id"], basket["id"]),
        fulfillment_status=FulfillmentStatus.DRAFT.value,
        billing_status=BillingStatus.PENDING_AUTH.value,
    )
