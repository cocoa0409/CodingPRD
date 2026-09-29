"""Boundaries, cross-entity dependencies, temporal overlap and conservation.

This file probes the fulfillment centre where a single unit decides the answer
and where the answer is decided somewhere other than the resource being asked:
a weighed joint whose measured deviation sits exactly on the SKU's tolerance is
accepted while the same joint one gram heavier is turned away; a wave whose
every retrieval is finished but whose van holds not one sealed tote refuses to
consolidate rather than close an empty load; a retrieval task that is itself
perfectly queued with a tote on its arm is refused because the grid zone two
hops away has been taken down by a maintenance window, and is admitted again the
moment that window is completed; two maintenance jobs on the same zone must
leave the engineers fifteen minutes of turnaround, so a job beginning exactly at
the buffer is scheduled and one beginning a second inside it is not; a dock bay
of two parallel van slots refuses a third van only at the one instant where
three loading intervals genuinely coexist, while intervals that merely touch
never collide; and both conserved ledgers — the delivery slot's capacity units
and the SKU's physical units — are shown to balance at every checkpoint of a
book, confirm and cancel round trip and of an allocation and its cancellation,
returning to their pre-action figures with zero drift and never absorbing the
capacity that was withheld from sale.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_field_absent_or_null,
    assert_instant_equals,
    assert_int_field,
    assert_load_sequence,
    assert_money,
    assert_order_money,
    assert_order_statuses,
    assert_sku_ledger,
    assert_slot_ledger,
    assert_status,
    assert_surge_multiplier,
    assert_wave_posture,
    list_items_and_meta,
)
from test_helpers.types import (
    BillingStatus,
    BookingStatus,
    FulfillmentStatus,
    GridZoneStatus,
    LineStatus,
    MaintenanceWindowStatus,
    PickTaskStatus,
    SubstitutionResolution,
    TemperatureZone,
    ToteStatus,
    WavePosture,
    WaveStatus,
)


def _weighed_pick_in_progress(api):
    """A weighed line whose retrieval is under way against a 1000 g nominal total.

    The SKU is priced at 1250 cents per kilogramme, declares 500 g per unit and
    accepts a five per cent deviation; the line orders two units, so the nominal
    total weight is exactly 1000 g and the tolerance band closes at 1050 g.
    """
    plant = fixtures.build_plant(api)
    sku = fixtures.create_catchweight_sku(
        api,
        plant["zone"]["id"],
        unit_price_cents=625,
        price_per_kg_cents=1250,
        nominal_weight_grams=500,
        weight_tolerance_pct=0.05,
        physical_units=100,
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    situation = fixtures.build_picking_wave(
        api, plant["route"]["id"], slot["id"], [sku["id"]], ordered_qty=2
    )
    task = situation["tasks"][0]
    driven = fixtures.drive_task_to_retrieving(
        api,
        task["id"],
        situation["wave"]["id"],
        task["pick_station_id"],
        TemperatureZone.AMBIENT.value,
    )
    situation["plant"] = plant
    situation["sku"] = sku
    situation["slot"] = slot
    situation["tote"] = driven["tote"]
    situation["task"] = driven["task"]
    return situation


def _picking_wave_with_one_line(api, ordered_qty=3):
    """A wave in PICKING whose single member order carries one ambient line."""
    plant = fixtures.build_plant(api)
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    situation = fixtures.build_picking_wave(
        api, plant["route"]["id"], slot["id"], [sku["id"]], ordered_qty=ordered_qty
    )
    situation["plant"] = plant
    situation["sku"] = sku
    situation["slot"] = slot
    return situation


def _queued_task_with_zone_in_maintenance(api):
    """A queued retrieval bound to a tote whose grid zone has been taken down."""
    situation = _picking_wave_with_one_line(api)
    task = situation["tasks"][0]
    tote = fixtures.create_tote(
        api,
        situation["wave"]["id"],
        task["pick_station_id"],
        temperature_zone=TemperatureZone.AMBIENT.value,
    )
    fixtures.assign_tote(api, task["id"], tote["id"])
    window = fixtures.create_maintenance_window(
        api,
        situation["plant"]["zone"]["id"],
        window_start="2026-08-01T00:00:00.000Z",
        window_end="2026-08-01T04:00:00.000Z",
    )
    fixtures.activate_maintenance_window(api, window["id"])
    situation["task"] = task
    situation["tote"] = tote
    situation["window"] = window
    return situation


def _short_line_wave_with_dock_reserved(api):
    """A wave carrying one short line, a reserved bay and one sealed tote.

    The line's SKU stands alone in its substitution group, so the substitute
    selector finds no candidate and no proposal is ever offered; the line simply
    stays awaiting a decision.
    """
    plant = fixtures.build_plant(api)
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    situation = fixtures.build_waved_order(
        api, plant["route"]["id"], slot["id"], [sku["id"]], ordered_qty=2
    )
    fixtures.assign_dock(
        api,
        situation["wave"]["id"],
        plant["bay"]["id"],
        "2026-08-05T08:00:00.000Z",
        "2026-08-05T09:00:00.000Z",
    )
    fixtures.start_picking(api, situation["wave"]["id"])
    task = fixtures.pick_task_for_line(api, situation["lines"][0]["id"])
    driven = fixtures.drive_task_to_retrieving(
        api,
        task["id"],
        situation["wave"]["id"],
        task["pick_station_id"],
        TemperatureZone.AMBIENT.value,
    )
    fixtures.complete_pick_task(api, task["id"], 1)
    fixtures.seal_tote(api, driven["tote"]["id"])
    situation["plant"] = plant
    situation["sku"] = sku
    situation["slot"] = slot
    situation["task"] = task
    situation["tote"] = driven["tote"]
    return situation


def _bay_with_forming_waves(api, wave_count):
    """One dock bay of two parallel van slots and several waves wanting it.

    Every wave needs its own delivery slot, because at most one wave may exist
    for a given delivery slot.
    """
    route = fixtures.create_delivery_route(api)
    bay = fixtures.create_dock_bay(api, parallel_van_capacity=2)
    waves = []
    for index in range(wave_count):
        opens_at = 10 + 2 * index
        slot = fixtures.create_delivery_slot(
            api,
            route["id"],
            window_start=f"2026-08-05T{opens_at:02d}:00:00.000Z",
            window_end=f"2026-08-05T{opens_at + 2:02d}:00:00.000Z",
        )
        waves.append(fixtures.create_delivery_wave(api, route["id"], slot["id"]))
    return route, bay, waves


def _slot_with_capacity_withheld(api):
    """A slot of 100 units with 20 withheld, plus a shopper holding a 1500 basket."""
    route = fixtures.create_delivery_route(api)
    zone = fixtures.create_grid_zone(api)
    sku = fixtures.create_inventory_sku(api, zone["id"])
    slot = fixtures.create_delivery_slot(
        api, route["id"], total_capacity_units=100, withheld_units=20
    )
    basket = fixtures.build_shopper_with_basket(
        api, route["id"], [sku["id"]], ordered_qty=6
    )
    return slot, basket


def test_weighed_pick_exactly_on_the_weight_tolerance_is_accepted_and_priced(api):
    """A measured deviation exactly equal to the SKU's tolerance passes the gate.

    Cites the requirement it rests on: "If the ratio is strictly greater than the
    SKU's `weight_tolerance_pct`, the request is refused with
    `ERR_WEIGHT_OUT_OF_TOLERANCE`; a ratio exactly equal to the tolerance is
    accepted."  The price then follows: "For a catchweight item it is the SKU's
    `price_per_kg_cents` multiplied by the measured total weight in grams,
    divided by 1,000, rounded half up to whole cents".

    Design: Difficulty/boundary_precision_check/catchweight_tolerance_upper_bound_inclusive
    """
    situation = _weighed_pick_in_progress(api)

    task = fixtures.complete_pick_task(
        api, situation["task"]["id"], 2, actual_weight_grams=1050
    )

    assert_status(task, PickTaskStatus.COMPLETED.value)
    assert_int_field(task, "picked_units", 2)
    assert_int_field(task, "actual_weight_grams", 1050)
    line = fixtures.read_order_line(
        api, situation["account"]["id"], situation["lines"][0]["id"]
    )
    assert_status(line, LineStatus.PICKED.value, field="line_status")
    assert_int_field(line, "picked_weight_grams", 1050)
    assert_money(line, "provisional_line_price_cents", 1250)
    assert_money(line, "final_line_price_cents", 1313)
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, situation["sku"]["id"]),
        physical_units=98,
        allocated_units=0,
        on_hand_units=98,
    )
    order = fixtures.read_order(
        api, situation["account"]["id"], situation["order"]["id"]
    )
    assert_order_money(
        order,
        merchandise_subtotal_cents=1313,
        delivery_fee_cents=500,
        loyalty_discount_cents=0,
        order_total_cents=1813,
        authorized_amount_cents=1750,
    )
    assert_order_statuses(order, billing_status=BillingStatus.ADJUSTED.value)


def test_weighed_pick_one_gram_past_the_weight_tolerance_is_refused(
    api, pick_operator_headers
):
    """One gram beyond the tolerance band sends the joint back to the grid.

    Cites the requirement it rests on: "For a catchweight SKU, the deviation
    ratio between the measured and the nominal total weight does not exceed the
    SKU's `weight_tolerance_pct`; a ratio exactly equal to the tolerance is
    accepted and only a strictly greater ratio is rejected."

    Design: Difficulty/boundary_precision_check/catchweight_tolerance_upper_bound_inclusive
    """
    situation = _weighed_pick_in_progress(api)

    response = api.complete_pick_task(
        situation["task"]["id"],
        factories.complete_pick_task_payload(2, actual_weight_grams=1051),
        pick_operator_headers,
    )

    validate_error(response, ApiError.WEIGHT_OUT_OF_TOLERANCE.value)
    task = fixtures.read_pick_task(api, situation["task"]["id"])
    assert_status(task, PickTaskStatus.RETRIEVING.value)
    assert_field_absent_or_null(task, "picked_units")
    assert_field_absent_or_null(task, "actual_weight_grams")
    line = fixtures.read_order_line(
        api, situation["account"]["id"], situation["lines"][0]["id"]
    )
    assert_status(line, LineStatus.PENDING.value, field="line_status")
    assert_money(line, "provisional_line_price_cents", 1250)
    assert_field_absent_or_null(line, "final_line_price_cents")
    assert_field_absent_or_null(line, "picked_weight_grams")
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, situation["sku"]["id"]),
        physical_units=100,
        allocated_units=2,
        on_hand_units=98,
    )


def test_consolidating_a_wave_holding_no_sealed_tote_is_refused(
    api, wave_planner_headers
):
    """A van with nothing sealed into it cannot close the picking floor.

    Cites the requirement it rests on: "Every retrieval task belonging to the
    wave must already be in a terminal status, meaning `COMPLETED`, `SHORT` or
    `CANCELLED`; and at least one tote of the wave must be in status `SEALED`, or
    the request is refused with `ERR_NO_TOTES_TO_CONSOLIDATE`."

    Design: Difficulty/boundary_precision_check/consolidate_wave_with_zero_sealed_totes_rejected
    """
    situation = _picking_wave_with_one_line(api)
    task = situation["tasks"][0]
    fixtures.cancel_pick_task(api, task["id"])

    response = api.consolidate_wave(situation["wave"]["id"], wave_planner_headers)

    validate_error(response, ApiError.NO_TOTES_TO_CONSOLIDATE.value)
    wave = fixtures.read_wave(api, situation["wave"]["id"])
    assert_status(wave, WaveStatus.PICKING.value)
    assert_int_field(wave, "tote_count", 0)
    assert_field_absent_or_null(wave, "consolidated_by_user_id")
    assert_status(
        fixtures.read_pick_task(api, task["id"]), PickTaskStatus.CANCELLED.value
    )
    order = fixtures.read_order(
        api, situation["account"]["id"], situation["order"]["id"]
    )
    assert_order_statuses(order, fulfillment_status=FulfillmentStatus.PICKING.value)
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, situation["sku"]["id"]),
        physical_units=100,
        allocated_units=0,
        on_hand_units=100,
    )


def test_consolidating_a_wave_holding_exactly_one_sealed_tote_succeeds(
    api, wave_planner_headers
):
    """One sealed tote is enough for the picking phase to close.

    Cites the requirement it rests on: "On success every tote of the wave whose
    status is `SEALED` advances `SEALED → CONSOLIDATED` and the wave's
    `tote_count` is recomputed; the wave advances `PICKING → CONSOLIDATED`; the
    acting operator's `X-User-ID` is recorded on the wave as
    `consolidated_by_user_id`".

    Design: Difficulty/boundary_precision_check/consolidate_wave_with_zero_sealed_totes_rejected
    """
    situation = _picking_wave_with_one_line(api)
    task = situation["tasks"][0]
    driven = fixtures.drive_task_to_retrieving(
        api,
        task["id"],
        situation["wave"]["id"],
        task["pick_station_id"],
        TemperatureZone.AMBIENT.value,
    )
    fixtures.complete_pick_task(api, task["id"], 3)
    fixtures.seal_tote(api, driven["tote"]["id"])

    wave = fixtures.consolidate_wave(
        api, situation["wave"]["id"], wave_planner_headers
    )

    assert_status(wave, WaveStatus.CONSOLIDATED.value)
    assert_wave_posture(wave, WavePosture.OPEN.value)
    assert wave["consolidated_by_user_id"] == wave_planner_headers["X-User-ID"], (
        "the consolidating operator's identifier must be recorded on the wave"
    )
    assert_int_field(wave, "tote_count", 1)
    assert_status(
        fixtures.read_tote(api, driven["tote"]["id"]), ToteStatus.CONSOLIDATED.value
    )
    order = fixtures.read_order(
        api, situation["account"]["id"], situation["order"]["id"]
    )
    assert_order_statuses(
        order, fulfillment_status=FulfillmentStatus.CONSOLIDATED.value
    )


def test_sending_the_bots_into_a_zone_under_maintenance_is_refused(
    api, pick_operator_headers, grid_engineer_headers
):
    """A queued retrieval with its tote already bound still cannot enter a downed zone.

    Cites the requirement it rests on: "While the zone is in `MAINTENANCE` no
    retrieval may be started into it — the attempt is refused with
    `ERR_ZONE_NOT_OPERATIONAL`."

    Design: Difficulty/cross_entity_state_dependency/pick_task_retrieval_blocked_by_zone_maintenance
    """
    situation = _queued_task_with_zone_in_maintenance(api)

    response = api.start_retrieval(situation["task"]["id"], pick_operator_headers)

    validate_error(response, ApiError.ZONE_NOT_OPERATIONAL.value)
    task = fixtures.read_pick_task(api, situation["task"]["id"])
    assert_status(task, PickTaskStatus.QUEUED.value)
    assert task["tote_id"] == situation["tote"]["id"], (
        "the refused task keeps the tote it was already bound to"
    )
    assert_status(
        fixtures.read_grid_zone(api, situation["plant"]["zone"]["id"]),
        GridZoneStatus.MAINTENANCE.value,
    )
    window = validate_success(
        api.get_maintenance_window(situation["window"]["id"], grid_engineer_headers)
    )
    assert_status(window, MaintenanceWindowStatus.ACTIVE.value)
    wave = fixtures.read_wave(api, situation["wave"]["id"])
    assert_status(wave, WaveStatus.PICKING.value)
    assert_wave_posture(wave, WavePosture.FROZEN.value)
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, situation["sku"]["id"]),
        physical_units=100,
        allocated_units=3,
        on_hand_units=97,
    )


def test_completing_the_maintenance_window_lets_the_bots_into_the_zone_again(
    api, grid_engineer_headers
):
    """Returning the zone to service unfreezes the wave and admits the retrieval.

    Cites the requirement it rests on: "Posture is recomputed for every affected
    wave, and a `FROZEN` wave clears — to `RESTRICTED` if some member order still
    has an unresolved shortage, otherwise to `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/pick_task_retrieval_blocked_by_zone_maintenance
    """
    situation = _queued_task_with_zone_in_maintenance(api)

    window = fixtures.complete_maintenance_window(api, situation["window"]["id"])
    task = fixtures.start_retrieval(api, situation["task"]["id"])

    assert_status(window, MaintenanceWindowStatus.COMPLETED.value)
    assert_status(
        fixtures.read_grid_zone(api, situation["plant"]["zone"]["id"]),
        GridZoneStatus.OPERATIONAL.value,
    )
    assert_status(task, PickTaskStatus.RETRIEVING.value)
    assert task["tote_id"] == situation["tote"]["id"]
    wave = fixtures.read_wave(api, situation["wave"]["id"])
    assert_status(wave, WaveStatus.PICKING.value)
    assert_wave_posture(wave, WavePosture.OPEN.value)
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, situation["sku"]["id"]),
        physical_units=100,
        allocated_units=3,
        on_hand_units=97,
    )


def test_sequencing_the_load_is_refused_while_a_member_order_awaits_a_substitution(
    api, wave_planner_headers, second_wave_planner_headers
):
    """A shortage decision pending on one line stops the whole van being sequenced.

    Cites the requirement it rests on: "A `FROZEN` posture is refused with
    `ERR_WAVE_FROZEN`, while a `RESTRICTED` posture — meaning some member order
    still has a line awaiting a substitution decision — is refused with
    `ERR_ORDER_DISPATCH_BLOCKED`."

    Design: Difficulty/cross_entity_state_dependency/wave_loading_blocked_by_dispatch_blocked_member_order
    """
    situation = _short_line_wave_with_dock_reserved(api)
    fixtures.consolidate_wave(api, situation["wave"]["id"], wave_planner_headers)

    response = api.compute_loading_sequence(
        situation["wave"]["id"], second_wave_planner_headers
    )

    validate_error(response, ApiError.ORDER_DISPATCH_BLOCKED.value)
    wave = fixtures.read_wave(api, situation["wave"]["id"])
    assert_status(wave, WaveStatus.CONSOLIDATED.value)
    assert_wave_posture(wave, WavePosture.RESTRICTED.value)
    assert_load_sequence(wave, [])
    assert_field_absent_or_null(wave, "transport_cost_cents")
    assert_status(
        fixtures.read_tote(api, situation["tote"]["id"]),
        ToteStatus.CONSOLIDATED.value,
    )
    order = fixtures.read_order(
        api, situation["account"]["id"], situation["order"]["id"]
    )
    assert_order_statuses(
        order, fulfillment_status=FulfillmentStatus.CONSOLIDATED.value
    )
    assert order["dispatch_blocked"] is True, (
        "an order with a line awaiting a substitution decision is dispatch-blocked"
    )
    line = fixtures.read_order_line(
        api, situation["account"]["id"], situation["lines"][0]["id"]
    )
    assert_status(line, LineStatus.SHORT.value, field="line_status")
    assert_status(
        line,
        SubstitutionResolution.PENDING.value,
        field="substitution_resolution",
    )
    assert (
        fixtures.list_substitution_proposals(api, order_line_id=line["id"]) == []
    ), "a SKU alone in its substitution group leaves the shopper no substitute"


def test_accepting_the_shortage_unblocks_the_wave_and_lets_the_load_be_sequenced(
    api, wave_planner_headers, second_wave_planner_headers
):
    """Once the shopper accepts the shortage the van may be sequenced for loading.

    Cites the requirement it rests on: "The order's `dispatch_blocked` is
    recomputed and clears once no line of the order is awaiting a decision, the
    wave's posture is recomputed — typically `RESTRICTED → OPEN` — and the order's
    `version` is incremented by 1."

    Design: Difficulty/cross_entity_state_dependency/wave_loading_blocked_by_dispatch_blocked_member_order
    """
    situation = _short_line_wave_with_dock_reserved(api)
    line = fixtures.accept_shortage(
        api, situation["account"]["id"], situation["lines"][0]["id"]
    )
    fixtures.consolidate_wave(api, situation["wave"]["id"], wave_planner_headers)

    wave = fixtures.compute_loading_sequence(
        api, situation["wave"]["id"], second_wave_planner_headers
    )

    assert_status(line, LineStatus.CANCELLED.value, field="line_status")
    assert_status(
        line,
        SubstitutionResolution.SHORTAGE_ACCEPTED.value,
        field="substitution_resolution",
    )
    assert_status(wave, WaveStatus.LOADING.value)
    assert_wave_posture(wave, WavePosture.OPEN.value)
    assert_load_sequence(wave, [situation["tote"]["id"]])
    assert_money(wave, "transport_cost_cents", 600)
    assert_status(
        fixtures.read_tote(api, situation["tote"]["id"]), ToteStatus.LOADED.value
    )
    order = fixtures.read_order(
        api, situation["account"]["id"], situation["order"]["id"]
    )
    assert_order_statuses(order, fulfillment_status=FulfillmentStatus.LOADED.value)
    assert order["dispatch_blocked"] is False, (
        "an order whose shortage has been resolved is no longer dispatch-blocked"
    )


def test_a_maintenance_job_starting_exactly_at_the_buffer_is_scheduled(
    api, grid_engineer_headers
):
    """Fifteen minutes of turnaround is enough room for the next job on the zone.

    Cites the requirement it rests on: "Both comparisons are strict, so a new
    window starting exactly fifteen minutes after an existing window ends is
    accepted, and one starting fourteen minutes and fifty-nine seconds after is
    rejected."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_buffer_overlap_on_same_grid_zone
    """
    zone = fixtures.create_grid_zone(api)
    fixtures.create_maintenance_window(
        api,
        zone["id"],
        window_start="2026-08-02T02:00:00.000Z",
        window_end="2026-08-02T04:00:00.000Z",
    )

    window = fixtures.create_maintenance_window(
        api,
        zone["id"],
        window_start="2026-08-02T04:15:00.000Z",
        window_end="2026-08-02T06:00:00.000Z",
    )

    assert_status(window, MaintenanceWindowStatus.SCHEDULED.value)
    assert_instant_equals(window["window_start"], "2026-08-02T04:15:00.000Z")
    assert_instant_equals(window["window_end"], "2026-08-02T06:00:00.000Z")
    assert_status(
        fixtures.read_grid_zone(api, zone["id"]), GridZoneStatus.OPERATIONAL.value
    )
    items, meta = list_items_and_meta(
        api.list_maintenance_windows(
            grid_engineer_headers, params={"grid_zone_id": zone["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        "both turnaround-separated jobs stand on the zone's schedule"
    )
    assert len(items) == 2


def test_a_maintenance_job_starting_a_second_inside_the_buffer_is_refused(
    api, grid_engineer_headers
):
    """A second short of the fifteen-minute turnaround collides with the first job.

    Cites the requirement it rests on: "Concretely, the proposal is rejected
    exactly when the new window's start is earlier than the existing window's end
    plus fifteen minutes **and** the existing window's start is earlier than the
    new window's end plus fifteen minutes; both halves of that conjunction must
    hold for a rejection."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_buffer_overlap_on_same_grid_zone
    """
    zone = fixtures.create_grid_zone(api)
    existing = fixtures.create_maintenance_window(
        api,
        zone["id"],
        window_start="2026-08-02T02:00:00.000Z",
        window_end="2026-08-02T04:00:00.000Z",
    )

    response = api.create_maintenance_window(
        factories.maintenance_window_payload(
            zone["id"],
            window_start="2026-08-02T04:14:59.000Z",
            window_end="2026-08-02T06:00:00.000Z",
        ),
        grid_engineer_headers,
    )

    validate_error(response, ApiError.MAINTENANCE_WINDOW_OVERLAP.value)
    items, meta = list_items_and_meta(
        api.list_maintenance_windows(
            grid_engineer_headers, params={"grid_zone_id": zone["id"]}
        )
    )
    assert meta["total_count"] == 1, "the refused job leaves no trace on the schedule"
    assert items[0]["id"] == existing["id"]
    assert_status(items[0], MaintenanceWindowStatus.SCHEDULED.value)
    assert_status(
        fixtures.read_grid_zone(api, zone["id"]), GridZoneStatus.OPERATIONAL.value
    )


def test_a_maintenance_job_wedged_into_the_turnaround_gap_is_refused(
    api, grid_engineer_headers
):
    """A short job sitting entirely inside the turnaround gap still collides.

    Cites the requirement it rests on: "The interesting rule is the **buffered
    non-overlap** rule: engineers need turnaround time between jobs on the same
    zone, so a proposed window is refused with `ERR_MAINTENANCE_WINDOW_OVERLAP`
    and HTTP 409 when it collides with any existing window on the *same* zone
    whose status is `SCHEDULED` or `ACTIVE`, after both intervals have been
    widened by `MAINTENANCE_BUFFER_MINUTES` — 15 minutes — on each side."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_buffer_overlap_on_same_grid_zone
    """
    zone = fixtures.create_grid_zone(api)
    fixtures.create_maintenance_window(
        api,
        zone["id"],
        window_start="2026-08-02T02:00:00.000Z",
        window_end="2026-08-02T04:00:00.000Z",
    )
    fixtures.create_maintenance_window(
        api,
        zone["id"],
        window_start="2026-08-02T04:15:00.000Z",
        window_end="2026-08-02T06:00:00.000Z",
    )

    response = api.create_maintenance_window(
        factories.maintenance_window_payload(
            zone["id"],
            window_start="2026-08-02T04:05:00.000Z",
            window_end="2026-08-02T04:12:00.000Z",
        ),
        grid_engineer_headers,
    )

    validate_error(response, ApiError.MAINTENANCE_WINDOW_OVERLAP.value)
    items, meta = list_items_and_meta(
        api.list_maintenance_windows(
            grid_engineer_headers, params={"grid_zone_id": zone["id"]}
        )
    )
    assert meta["total_count"] == 2, "the zone's schedule is left exactly as it was"
    for scheduled in items:
        assert_status(scheduled, MaintenanceWindowStatus.SCHEDULED.value)


def test_two_vans_may_share_a_bay_of_two_parallel_slots(api, wave_planner_headers):
    """Overlapping vans are welcome right up to the bay's parallel capacity.

    Cites the requirement it rests on: "The scheduling rule is an
    aggregate-capacity test rather than a simple exclusivity test: at every
    instant of the requested interval, the number of *other* waves already
    assigned to the same bay whose own occupation intervals cover that instant
    must be strictly less than the bay's `parallel_van_capacity`."

    Design: Difficulty/resource_temporal_overlap/dock_bay_aggregate_concurrency_overlap
    """
    route, bay, waves = _bay_with_forming_waves(api, 2)
    fixtures.assign_dock(
        api,
        waves[0]["id"],
        bay["id"],
        "2026-08-05T08:00:00.000Z",
        "2026-08-05T09:00:00.000Z",
    )

    second = fixtures.assign_dock(
        api,
        waves[1]["id"],
        bay["id"],
        "2026-08-05T08:30:00.000Z",
        "2026-08-05T09:30:00.000Z",
    )

    assert second["dock_bay_id"] == bay["id"]
    assert_instant_equals(second["load_start"], "2026-08-05T08:30:00.000Z")
    assert_instant_equals(second["load_end"], "2026-08-05T09:30:00.000Z")
    assert_status(second, WaveStatus.FORMING.value)
    items, meta = list_items_and_meta(
        api.list_delivery_waves(
            wave_planner_headers, params={"dock_bay_id": bay["id"]}
        )
    )
    assert meta["total_count"] == 2, "both vans hold a slot at the same bay"
    assert {item["id"] for item in items} == {waves[0]["id"], waves[1]["id"]}
    assert route["id"] == waves[0]["route_id"]


def test_a_third_van_overlapping_both_others_is_turned_away_from_the_bay(
    api, wave_planner_headers
):
    """The bay refuses the one van that would make three intervals coexist.

    Cites the requirement it rests on: "A request that would breach the bay's
    parallel capacity at any instant is refused with
    `ERR_DOCK_BAY_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/dock_bay_aggregate_concurrency_overlap
    """
    _route, bay, waves = _bay_with_forming_waves(api, 3)
    fixtures.assign_dock(
        api,
        waves[0]["id"],
        bay["id"],
        "2026-08-05T08:00:00.000Z",
        "2026-08-05T09:00:00.000Z",
    )
    fixtures.assign_dock(
        api,
        waves[1]["id"],
        bay["id"],
        "2026-08-05T08:30:00.000Z",
        "2026-08-05T09:30:00.000Z",
    )

    response = api.assign_dock(
        waves[2]["id"],
        factories.assign_dock_payload(
            bay["id"], "2026-08-05T08:45:00.000Z", "2026-08-05T09:15:00.000Z"
        ),
        wave_planner_headers,
    )

    validate_error(response, ApiError.DOCK_BAY_CAPACITY_EXCEEDED.value)
    refused = fixtures.read_wave(api, waves[2]["id"])
    assert_status(refused, WaveStatus.FORMING.value)
    assert_field_absent_or_null(refused, "dock_bay_id")
    assert_field_absent_or_null(refused, "load_start")
    assert_field_absent_or_null(refused, "load_end")
    _items, meta = list_items_and_meta(
        api.list_delivery_waves(
            wave_planner_headers, params={"dock_bay_id": bay["id"]}
        )
    )
    assert meta["total_count"] == 2, "the refused van never took a slot at the bay"


def test_a_van_arriving_exactly_as_another_leaves_shares_no_instant_with_it(
    api, wave_planner_headers
):
    """Touching occupation intervals never contribute to the bay's concurrency count.

    Cites the requirement it rests on: "Two intervals that merely touch — where
    the existing wave's `load_end` equals the new wave's `load_start`, or vice
    versa — do **not** overlap and never contribute to the count."

    Design: Difficulty/resource_temporal_overlap/dock_bay_aggregate_concurrency_overlap
    """
    _route, bay, waves = _bay_with_forming_waves(api, 3)
    fixtures.assign_dock(
        api,
        waves[0]["id"],
        bay["id"],
        "2026-08-05T08:00:00.000Z",
        "2026-08-05T09:00:00.000Z",
    )
    fixtures.assign_dock(
        api,
        waves[1]["id"],
        bay["id"],
        "2026-08-05T08:30:00.000Z",
        "2026-08-05T09:30:00.000Z",
    )

    third = fixtures.assign_dock(
        api,
        waves[2]["id"],
        bay["id"],
        "2026-08-05T09:30:00.000Z",
        "2026-08-05T10:00:00.000Z",
    )

    assert third["dock_bay_id"] == bay["id"]
    assert_instant_equals(third["load_start"], "2026-08-05T09:30:00.000Z")
    assert_instant_equals(third["load_end"], "2026-08-05T10:00:00.000Z")
    assert_status(third, WaveStatus.FORMING.value)
    _items, meta = list_items_and_meta(
        api.list_delivery_waves(
            wave_planner_headers, params={"dock_bay_id": bay["id"]}
        )
    )
    assert meta["total_count"] == 3, (
        "three vans hold slots at the bay because only two ever coexist"
    )


def test_the_slot_capacity_ledger_balances_as_a_booking_is_held_then_confirmed(api):
    """Units move between the ledger's terms without the withheld stock being touched.

    Cites the requirement it rests on: "The conserved identity is therefore that
    `total_capacity_units` always equals `withheld_units` plus `held_units` plus
    `confirmed_units` plus `available_units`."

    Design: Difficulty/compensating_invariant/slot_capacity_conserved_across_book_and_cancel
    """
    slot, basket = _slot_with_capacity_withheld(api)
    assert_slot_ledger(
        fixtures.read_delivery_slot(api, slot["id"]),
        total_capacity_units=100,
        withheld_units=20,
        held_units=0,
        confirmed_units=0,
        available_units=80,
    )

    booking = fixtures.create_slot_booking(
        api, basket["account"]["id"], slot["id"], basket["order"]["id"], units=5
    )
    assert_status(booking, BookingStatus.HELD.value)
    assert_slot_ledger(
        fixtures.read_delivery_slot(api, slot["id"]),
        total_capacity_units=100,
        withheld_units=20,
        held_units=5,
        confirmed_units=0,
        available_units=75,
    )

    fixtures.confirm_slot_booking(api, basket["account"]["id"], booking["id"])

    confirmed_slot = fixtures.read_delivery_slot(api, slot["id"])
    assert_slot_ledger(
        confirmed_slot,
        total_capacity_units=100,
        withheld_units=20,
        held_units=0,
        confirmed_units=5,
        available_units=75,
    )
    assert_surge_multiplier(confirmed_slot, 1.00)
    assert_status(
        fixtures.read_slot_booking(api, booking["id"]), BookingStatus.CONFIRMED.value
    )
    order = fixtures.read_order(
        api, basket["account"]["id"], basket["order"]["id"]
    )
    assert_order_statuses(
        order,
        fulfillment_status=FulfillmentStatus.SLOTTED.value,
        billing_status=BillingStatus.AUTHORIZED.value,
    )
    assert_order_money(
        order,
        merchandise_subtotal_cents=1500,
        delivery_fee_cents=500,
        loyalty_discount_cents=0,
        order_total_cents=2000,
        authorized_amount_cents=2000,
    )


def test_cancelling_the_slotted_order_returns_every_capacity_unit_it_reserved(api):
    """The compensating cancellation leaves no drift on the slot's capacity ledger.

    Cites the requirement it rests on: "Cancellation is the system's compensating
    action, and it is held to the conservation discipline of §2.9: after a
    cancellation both ledger identities must still balance exactly, with no drift
    left behind on any slot or any SKU."

    Design: Difficulty/compensating_invariant/slot_capacity_conserved_across_book_and_cancel
    """
    slot, basket = _slot_with_capacity_withheld(api)
    booking = fixtures.create_slot_booking(
        api, basket["account"]["id"], slot["id"], basket["order"]["id"], units=5
    )
    fixtures.confirm_slot_booking(api, basket["account"]["id"], booking["id"])

    fixtures.cancel_customer_order(
        api, basket["account"]["id"], basket["order"]["id"]
    )

    restored = fixtures.read_delivery_slot(api, slot["id"])
    assert_slot_ledger(
        restored,
        total_capacity_units=100,
        withheld_units=20,
        held_units=0,
        confirmed_units=0,
        available_units=80,
    )
    assert_surge_multiplier(restored, 1.00)
    released = fixtures.read_slot_booking(api, booking["id"])
    assert_status(released, BookingStatus.RELEASED.value)
    assert_int_field(released, "units", 5)
    order = fixtures.read_order(
        api, basket["account"]["id"], basket["order"]["id"]
    )
    assert_order_statuses(
        order,
        fulfillment_status=FulfillmentStatus.CANCELLED.value,
        billing_status=BillingStatus.REVERSED.value,
    )
    assert_money(order, "merchandise_subtotal_cents", 0)
    assert_money(order, "authorized_amount_cents", 2000)
    assert_field_absent_or_null(order, "captured_amount_cents")
    assert_field_absent_or_null(order, "order_total_cents")
    assert_field_absent_or_null(order, "delivery_fee_cents")
    assert_status(
        fixtures.read_order_line(
            api, basket["account"]["id"], basket["lines"][0]["id"]
        ),
        LineStatus.CANCELLED.value,
        field="line_status",
    )


def test_starting_the_pick_moves_units_from_on_hand_into_allocated(api):
    """Reserving stock shifts the ledger's terms while the physical count stands still.

    Cites the requirement it rests on: "Reserving stock when a wave starts picking
    moves units from the on-hand figure into the allocated figure while leaving
    `physical_units` untouched."

    Design: Difficulty/compensating_invariant/sku_on_hand_conserved_across_allocation_and_cancel
    """
    plant = fixtures.build_plant(api)
    sku = fixtures.create_inventory_sku(
        api, plant["zone"]["id"], unit_price_cents=700, physical_units=100
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    situation = fixtures.build_waved_order(
        api, plant["route"]["id"], slot["id"], [sku["id"]], ordered_qty=3
    )
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, sku["id"]),
        physical_units=100,
        allocated_units=0,
        on_hand_units=100,
    )

    fixtures.start_picking(api, situation["wave"]["id"])

    assert_sku_ledger(
        fixtures.read_inventory_sku(api, sku["id"]),
        physical_units=100,
        allocated_units=3,
        on_hand_units=97,
    )
    task = fixtures.pick_task_for_line(api, situation["lines"][0]["id"])
    assert_status(task, PickTaskStatus.QUEUED.value)
    assert_int_field(task, "allocated_units", 3)
    order = fixtures.read_order(
        api, situation["account"]["id"], situation["order"]["id"]
    )
    assert_order_statuses(order, fulfillment_status=FulfillmentStatus.PICKING.value)


def test_cancelling_a_queued_retrieval_returns_the_units_to_on_hand(api):
    """The compensating cancellation restores both ledger figures with zero drift.

    Cites the requirement it rests on: "From `QUEUED` the task advances `QUEUED →
    CANCELLED`: it leaves the SKU's allocated set, so the unit ledger restores
    both `allocated_units` and `on_hand_units` to exactly their pre-allocation
    values with zero drift, and the tote's `assigned_line_count` is recomputed."

    Design: Difficulty/compensating_invariant/sku_on_hand_conserved_across_allocation_and_cancel
    """
    situation = _picking_wave_with_one_line(api)

    task = fixtures.cancel_pick_task(api, situation["tasks"][0]["id"])

    assert_status(task, PickTaskStatus.CANCELLED.value)
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, situation["sku"]["id"]),
        physical_units=100,
        allocated_units=0,
        on_hand_units=100,
    )
    line = fixtures.read_order_line(
        api, situation["account"]["id"], situation["lines"][0]["id"]
    )
    assert_status(line, LineStatus.PENDING.value, field="line_status")
    assert_field_absent_or_null(line, "picked_units")
    wave = fixtures.read_wave(api, situation["wave"]["id"])
    assert_status(wave, WaveStatus.PICKING.value)
    assert_wave_posture(wave, WavePosture.OPEN.value)
    order = fixtures.read_order(
        api, situation["account"]["id"], situation["order"]["id"]
    )
    assert_order_money(
        order,
        merchandise_subtotal_cents=2100,
        delivery_fee_cents=500,
        loyalty_discount_cents=0,
        order_total_cents=2600,
    )


def test_cancelling_a_retrieval_already_under_way_leaves_the_grid_count_untouched(api):
    """Abandoning a retrieval in flight restores the allocation and removes nothing.

    Cites the requirement it rests on: "From `RETRIEVING` the task advances
    `RETRIEVING → CANCELLED` with the same ledger effect, and the SKU's
    `physical_units` is explicitly left unchanged, because nothing was ever
    removed from the grid."

    Design: Difficulty/compensating_invariant/sku_on_hand_conserved_across_allocation_and_cancel
    """
    situation = _picking_wave_with_one_line(api)
    original = situation["tasks"][0]
    driven = fixtures.drive_task_to_retrieving(
        api,
        original["id"],
        situation["wave"]["id"],
        original["pick_station_id"],
        TemperatureZone.AMBIENT.value,
    )
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, situation["sku"]["id"]),
        physical_units=100,
        allocated_units=3,
        on_hand_units=97,
    )

    task = fixtures.cancel_pick_task(api, original["id"])

    assert_status(task, PickTaskStatus.CANCELLED.value)
    assert_sku_ledger(
        fixtures.read_inventory_sku(api, situation["sku"]["id"]),
        physical_units=100,
        allocated_units=0,
        on_hand_units=100,
    )
    tote = fixtures.read_tote(api, driven["tote"]["id"])
    assert_int_field(tote, "assigned_line_count", 0)
    assert_status(tote, ToteStatus.OPEN.value)
