"""The picking floor, from the moment a planner turns a paper wave into physical work.

Starting a wave picking is the request that reserves stock and puts retrieval tasks in
front of the bots, and everything downstream of it is guarded: a wave with nobody in it
cannot be started, a wave whose only station cannot handle the cold class of the goods
cannot be started, a wave asking for more units than the grid physically holds cannot be
started, and a wave that is already on the floor refuses a second start rather than
allocating the same stock twice. Around those guards the totes come and go at a station —
opened for exactly one temperature class, bound to the retrievals they will carry, sealed
once every retrieval on them is finished and reopened only when a late substitute still
has to be dropped in — and each hand-off has its own refusal: an empty tote may not be
sealed, an already-open tote may not be reopened, a tote of the wrong class may not be
opened at a station that is not equipped for it nor bound to a retrieval of a different
class, and a sealed tote may not reclaim a station slot that a fresher tote has taken.
Only when every retrieval has come to rest and a sealed tote exists does the wave close
its picking phase, and only with a dock bay reserved may its van's load be sequenced.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_field_absent_or_null,
    assert_int_field,
    assert_order_statuses,
    assert_sku_ledger,
    assert_station_status_matches_count,
    assert_status,
    assert_wave_posture,
    list_items,
    only_item,
)
from test_helpers.types import (
    FulfillmentStatus,
    LineStatus,
    PickTaskStatus,
    TemperatureZone,
    ToteStatus,
    WavePosture,
    WaveStatus,
)

AMBIENT = TemperatureZone.AMBIENT.value
CHILLED = TemperatureZone.CHILLED.value
FROZEN = TemperatureZone.FROZEN.value


def test_consolidating_while_a_retrieval_is_still_running_is_refused(
    api, wave_planner_headers
):
    """A wave may not close its picking phase while a bot is still in the grid.

    Cites the requirement it rests on: "Every retrieval task belonging to the wave
    must already be in a terminal status, meaning `COMPLETED`, `SHORT` or
    `CANCELLED`; and at least one tote of the wave must be in status `SEALED`, or the
    request is refused with `ERR_NO_TOTES_TO_CONSOLIDATE`." and "The target resource
    is in a state from which the requested transition exists, and every precondition
    of that transition that concerns the target resource itself holds — for instance
    a tote must be `OPEN` to be sealed, a retrieval task must be `RETRIEVING` to be
    completed, a wave must be `CONSOLIDATED` to be sequenced for loading, and a
    booking must be `HELD` to be confirmed. Violation: `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/consolidate_with_a_retrieving_task_returns_invalid_state
    """
    plant = fixtures.build_plant(
        api,
        temperature_zone=AMBIENT,
        station={"temperature_zone_capability": [AMBIENT], "max_concurrent_totes": 3},
    )
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    picking = fixtures.build_picking_wave(
        api,
        plant["route"]["id"],
        slot["id"],
        [sku["id"]],
        ordered_qty=2,
        units=2,
    )
    task = picking["tasks"][0]
    driven = fixtures.drive_task_to_retrieving(
        api, task["id"], picking["wave"]["id"], task["pick_station_id"], AMBIENT
    )

    response = api.consolidate_wave(picking["wave"]["id"], wave_planner_headers)
    validate_error(response, ApiError.INVALID_STATE.value)

    wave = fixtures.read_wave(api, picking["wave"]["id"])
    assert_status(wave, WaveStatus.PICKING.value)
    assert_field_absent_or_null(wave, "consolidated_by_user_id")
    assert_status(
        fixtures.read_pick_task(api, task["id"]), PickTaskStatus.RETRIEVING.value
    )
    assert_status(
        fixtures.read_tote(api, driven["tote"]["id"]), ToteStatus.OPEN.value
    )
    assert_order_statuses(
        fixtures.read_order(api, picking["account"]["id"], picking["order"]["id"]),
        fulfillment_status=FulfillmentStatus.PICKING.value,
    )


def test_sequencing_the_load_without_a_dock_bay_is_refused(api, wave_planner_headers):
    """A consolidated wave whose van has no bay reserved cannot have its load sequenced.

    Cites the requirement it rests on: "The wave must be `CONSOLIDATED`; it must have
    a `dock_bay_id`, or the request is refused with `ERR_DOCK_NOT_ASSIGNED`; and its
    `posture` must be exactly `OPEN`."

    Design: Corner/state_machines/loading_sequence_without_a_dock_returns_dock_not_assigned
    """
    plant = fixtures.build_plant(
        api,
        temperature_zone=AMBIENT,
        station={"temperature_zone_capability": [AMBIENT], "max_concurrent_totes": 3},
    )
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    picking = fixtures.build_picking_wave(
        api,
        plant["route"]["id"],
        slot["id"],
        [sku["id"]],
        ordered_qty=2,
        units=2,
    )
    task = picking["tasks"][0]
    driven = fixtures.drive_task_to_retrieving(
        api, task["id"], picking["wave"]["id"], task["pick_station_id"], AMBIENT
    )
    fixtures.complete_pick_task(api, task["id"], 2)
    fixtures.seal_tote(api, driven["tote"]["id"])
    fixtures.consolidate_wave(api, picking["wave"]["id"])

    response = api.compute_loading_sequence(
        picking["wave"]["id"], wave_planner_headers
    )
    validate_error(response, ApiError.DOCK_NOT_ASSIGNED.value)

    wave = fixtures.read_wave(api, picking["wave"]["id"])
    assert_status(wave, WaveStatus.CONSOLIDATED.value)
    assert_field_absent_or_null(wave, "dock_bay_id")
    assert wave["load_sequence"] == [], (
        f"load_sequence should stay empty, got {wave['load_sequence']}"
    )
    assert_field_absent_or_null(wave, "transport_cost_cents")
    assert_status(
        fixtures.read_tote(api, driven["tote"]["id"]),
        ToteStatus.CONSOLIDATED.value,
    )
    assert_order_statuses(
        fixtures.read_order(api, picking["account"]["id"], picking["order"]["id"]),
        fulfillment_status=FulfillmentStatus.CONSOLIDATED.value,
    )


def test_starting_the_same_wave_picking_twice_does_not_reserve_the_stock_again(
    api, wave_planner_headers
):
    """A wave already on the picking floor refuses a second start and re-reserves nothing.

    Cites the requirement it rests on: "A `WavePlanner` starts a wave that is
    `FORMING`, has at least one member order, and whose posture is not `FROZEN`." and
    "The target resource is in a state from which the requested transition exists, and
    every precondition of that transition that concerns the target resource itself
    holds — for instance a tote must be `OPEN` to be sealed, a retrieval task must be
    `RETRIEVING` to be completed, a wave must be `CONSOLIDATED` to be sequenced for
    loading, and a booking must be `HELD` to be confirmed. Violation:
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/start_picking_twice_returns_invalid_state
    """
    plant = fixtures.build_plant(
        api,
        temperature_zone=AMBIENT,
        station={"temperature_zone_capability": [AMBIENT], "max_concurrent_totes": 3},
    )
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    picking = fixtures.build_picking_wave(
        api,
        plant["route"]["id"],
        slot["id"],
        [sku["id"]],
        ordered_qty=2,
        units=2,
    )
    line = picking["lines"][0]

    response = api.start_picking(picking["wave"]["id"], wave_planner_headers)
    validate_error(response, ApiError.INVALID_STATE.value)

    assert_status(
        fixtures.read_wave(api, picking["wave"]["id"]), WaveStatus.PICKING.value
    )
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, sku["id"]),
        physical_units=100,
        allocated_units=2,
        on_hand_units=98,
    )
    tasks = fixtures.list_pick_tasks(api, order_line_id=line["id"])
    assert len(tasks) == 1, (
        f"the second start must not create a duplicate retrieval task, "
        f"found {len(tasks)} tasks for the line"
    )
    assert_status(only_item(tasks), PickTaskStatus.QUEUED.value)


def test_starting_a_wave_that_carries_no_orders_is_refused(api, wave_planner_headers):
    """An empty wave has no work to release into the grid, so its start is refused.

    Cites the requirement it rests on: "A wave with no member order at all cannot be
    started; that refusal is `ERR_WAVE_HAS_NO_ORDERS`."

    Design: Corner/state_machines/start_picking_an_empty_wave_returns_wave_has_no_orders
    """
    route = fixtures.create_delivery_route(api)
    slot = fixtures.create_delivery_slot(api, route["id"])
    wave = fixtures.create_delivery_wave(api, route["id"], slot["id"])

    response = api.start_picking(wave["id"], wave_planner_headers)
    validate_error(response, ApiError.WAVE_HAS_NO_ORDERS.value)

    wave = fixtures.read_wave(api, wave["id"])
    assert_status(wave, WaveStatus.FORMING.value)
    assert_int_field(wave, "order_count", 0)
    assert_wave_posture(wave, WavePosture.OPEN.value)


def test_starting_picking_with_no_station_equipped_for_the_class_is_refused(
    api, wave_planner_headers
):
    """An ambient line cannot be released when the only station handles frozen goods.

    Cites the requirement it rests on: "If the pool is empty for any task being
    created, the whole request is refused with `ERR_NO_ELIGIBLE_PICK_STATION` and
    nothing is created."

    Design: Corner/state_machines/start_picking_with_no_capable_station_returns_no_eligible_pick_station
    """
    plant = fixtures.build_plant(
        api,
        temperature_zone=AMBIENT,
        station={"temperature_zone_capability": [FROZEN], "max_concurrent_totes": 3},
    )
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    waved = fixtures.build_waved_order(
        api,
        plant["route"]["id"],
        slot["id"],
        [sku["id"]],
        ordered_qty=2,
        units=2,
    )

    response = api.start_picking(waved["wave"]["id"], wave_planner_headers)
    validate_error(response, ApiError.NO_ELIGIBLE_PICK_STATION.value)

    assert_status(
        fixtures.read_wave(api, waved["wave"]["id"]), WaveStatus.FORMING.value
    )
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, sku["id"]),
        physical_units=100,
        allocated_units=0,
        on_hand_units=100,
    )
    assert fixtures.list_pick_tasks(api, order_line_id=waved["lines"][0]["id"]) == [], (
        "a refused start must leave no retrieval task behind"
    )
    assert_order_statuses(
        fixtures.read_order(api, waved["account"]["id"], waved["order"]["id"]),
        fulfillment_status=FulfillmentStatus.WAVED.value,
    )


def test_starting_picking_beyond_what_the_grid_holds_is_refused(
    api, wave_planner_headers
):
    """Stock is tested when the wave starts, not when the shopper adds the line.

    Cites the requirement it rests on: "Before anything is created, three feasibility
    checks run over every order line of every `WAVED` member order whose `line_status`
    is `PENDING`: the line's SKU must have an `on_hand_units` of at least the line's
    `ordered_qty`, or the request is refused with `ERR_INSUFFICIENT_INVENTORY`; the
    grid zone holding that SKU must be `OPERATIONAL`, or the request is refused with
    `ERR_ZONE_NOT_OPERATIONAL`; and the station-selection pool for that line must be
    non-empty, or the request is refused with `ERR_NO_ELIGIBLE_PICK_STATION`."

    Design: Corner/state_machines/start_picking_beyond_on_hand_returns_insufficient_inventory
    """
    plant = fixtures.build_plant(
        api,
        temperature_zone=AMBIENT,
        station={"temperature_zone_capability": [AMBIENT], "max_concurrent_totes": 3},
    )
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=1
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    waved = fixtures.build_waved_order(
        api,
        plant["route"]["id"],
        slot["id"],
        [sku["id"]],
        ordered_qty=2,
        units=2,
    )

    response = api.start_picking(waved["wave"]["id"], wave_planner_headers)
    validate_error(response, ApiError.INSUFFICIENT_INVENTORY.value)

    assert_status(
        fixtures.read_wave(api, waved["wave"]["id"]), WaveStatus.FORMING.value
    )
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, sku["id"]),
        physical_units=1,
        allocated_units=0,
        on_hand_units=1,
    )
    line = fixtures.read_order_line(
        api, waved["account"]["id"], waved["lines"][0]["id"]
    )
    assert_status(line, LineStatus.PENDING.value, field="line_status")
    assert_order_statuses(
        fixtures.read_order(api, waved["account"]["id"], waved["order"]["id"]),
        fulfillment_status=FulfillmentStatus.WAVED.value,
    )


def test_sealing_an_empty_tote_and_reopening_an_open_tote_fail_for_different_reasons(
    api, pick_operator_headers
):
    """An empty tote cannot be sealed and an open tote cannot be reopened, each its own way.

    Cites the requirement it rests on: "Every retrieval task bound to the tote must
    already be in a terminal status — `COMPLETED`, `SHORT` or `CANCELLED` — and the
    tote must have at least one task bound to it at all, since sealing an empty tote is
    refused with `ERR_TOTE_NOT_ASSIGNED`." and "**Unsealing a tote** advances it
    `SEALED → OPEN` and closes the cycle."

    Design: Corner/state_machines/seal_guards_reject_an_empty_tote_and_an_unseal_of_an_open_tote
    """
    plant = fixtures.build_plant(
        api,
        temperature_zone=AMBIENT,
        station={"temperature_zone_capability": [AMBIENT], "max_concurrent_totes": 3},
    )
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    picking = fixtures.build_picking_wave(
        api,
        plant["route"]["id"],
        slot["id"],
        [sku["id"]],
        ordered_qty=2,
        units=2,
    )
    task = picking["tasks"][0]
    station_id = task["pick_station_id"]
    carrying_tote = fixtures.create_tote(
        api, picking["wave"]["id"], station_id, temperature_zone=AMBIENT
    )
    fixtures.assign_tote(api, task["id"], carrying_tote["id"])
    empty_tote = fixtures.create_tote(
        api, picking["wave"]["id"], station_id, temperature_zone=AMBIENT
    )

    seal_response = api.seal_tote(empty_tote["id"], pick_operator_headers)
    validate_error(seal_response, ApiError.TOTE_NOT_ASSIGNED.value)

    unseal_response = api.unseal_tote(carrying_tote["id"], pick_operator_headers)
    validate_error(unseal_response, ApiError.INVALID_STATE.value)

    empty_tote = fixtures.read_tote(api, empty_tote["id"])
    assert_status(empty_tote, ToteStatus.OPEN.value)
    assert_int_field(empty_tote, "assigned_line_count", 0)
    carrying_tote = fixtures.read_tote(api, carrying_tote["id"])
    assert_status(carrying_tote, ToteStatus.OPEN.value)
    assert_int_field(carrying_tote, "assigned_line_count", 1)
    station = fixtures.read_pick_station(api, station_id)
    assert_int_field(station, "current_tote_count", 2)
    assert_station_status_matches_count(station)


def test_station_capability_and_tote_class_are_two_separate_cold_chain_guards(
    api, pick_operator_headers
):
    """Opening a tote checks the station's equipment; binding a retrieval checks the goods.

    Cites the requirement it rests on: "A tote may only be opened at a station whose
    capability set contains that tote's class, and an attempt to open one elsewhere is
    rejected with `ERR_STATION_ZONE_UNSUPPORTED`. A retrieval task may only be bound to
    a tote whose class equals the class of the SKU actually being retrieved, and a
    mismatch is rejected with `ERR_TEMPERATURE_ZONE_MISMATCH`."

    Design: Corner/state_machines/tote_zone_guards_separate_station_capability_from_task_zone
    """
    plant = fixtures.build_plant(
        api,
        temperature_zone=AMBIENT,
        station={
            "temperature_zone_capability": [AMBIENT, CHILLED],
            "max_concurrent_totes": 3,
        },
    )
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    picking = fixtures.build_picking_wave(
        api,
        plant["route"]["id"],
        slot["id"],
        [sku["id"]],
        ordered_qty=2,
        units=2,
    )
    task = picking["tasks"][0]
    station_id = task["pick_station_id"]
    chilled_tote = fixtures.create_tote(
        api, picking["wave"]["id"], station_id, temperature_zone=CHILLED
    )

    frozen_response = api.create_tote(
        factories.tote_payload(
            picking["wave"]["id"], station_id, temperature_zone=FROZEN
        ),
        pick_operator_headers,
    )
    validate_error(frozen_response, ApiError.STATION_ZONE_UNSUPPORTED.value)

    bind_response = api.assign_tote(
        task["id"],
        factories.assign_tote_payload(chilled_tote["id"]),
        pick_operator_headers,
    )
    validate_error(bind_response, ApiError.TEMPERATURE_ZONE_MISMATCH.value)

    totes = list_items(
        api.list_totes(pick_operator_headers, params={"wave_id": picking["wave"]["id"]})
    )
    assert len(totes) == 1, (
        f"only the chilled tote should exist on the wave, found {len(totes)}"
    )
    station = fixtures.read_pick_station(api, station_id)
    assert_int_field(station, "current_tote_count", 1)
    task = fixtures.read_pick_task(api, task["id"])
    assert_field_absent_or_null(task, "tote_id")
    assert_status(task, PickTaskStatus.QUEUED.value)
    assert_int_field(
        fixtures.read_tote(api, chilled_tote["id"]), "assigned_line_count", 0
    )


def test_reopening_a_sealed_tote_at_a_full_station_is_refused(
    api, pick_operator_headers
):
    """A sealed tote gave its station slot back, and a fresher tote may already hold it.

    Cites the requirement it rests on: "The tote's wave must still be `PICKING` and its
    posture must not be `FROZEN`, again with `ERR_WAVE_FROZEN`; and the station must
    have room, since a station whose `current_tote_count` has reached its
    `max_concurrent_totes` refuses the reopening with
    `ERR_STATION_TOTE_CAPACITY_EXCEEDED`."

    Design: Corner/state_machines/unseal_at_station_tote_capacity_returns_station_tote_capacity_exceeded
    """
    plant = fixtures.build_plant(
        api,
        temperature_zone=AMBIENT,
        station={"temperature_zone_capability": [AMBIENT], "max_concurrent_totes": 1},
    )
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    picking = fixtures.build_picking_wave(
        api,
        plant["route"]["id"],
        slot["id"],
        [sku["id"]],
        ordered_qty=2,
        units=2,
    )
    task = picking["tasks"][0]
    station_id = task["pick_station_id"]
    first_tote = fixtures.create_tote(
        api, picking["wave"]["id"], station_id, temperature_zone=AMBIENT
    )
    fixtures.assign_tote(api, task["id"], first_tote["id"])
    fixtures.start_retrieval(api, task["id"])
    fixtures.complete_pick_task(api, task["id"], 2)
    fixtures.seal_tote(api, first_tote["id"])
    second_tote = fixtures.create_tote(
        api, picking["wave"]["id"], station_id, temperature_zone=AMBIENT
    )

    response = api.unseal_tote(first_tote["id"], pick_operator_headers)
    validate_error(response, ApiError.STATION_TOTE_CAPACITY_EXCEEDED.value)

    assert_status(fixtures.read_tote(api, first_tote["id"]), ToteStatus.SEALED.value)
    assert_status(fixtures.read_tote(api, second_tote["id"]), ToteStatus.OPEN.value)
    station = fixtures.read_pick_station(api, station_id)
    assert_int_field(station, "current_tote_count", 1)
    assert_station_status_matches_count(station)
    assert_status(
        fixtures.read_pick_task(api, task["id"]), PickTaskStatus.COMPLETED.value
    )
