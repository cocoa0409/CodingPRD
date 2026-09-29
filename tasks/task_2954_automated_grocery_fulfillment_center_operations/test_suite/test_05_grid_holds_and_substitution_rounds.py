"""Grid holds and substitution rounds on the picking floor.

The engineering side of the fulfillment centre owns two levers that can stop the
bots — a scheduled maintenance window that may only be opened while the logical
clock stands inside it, and an inventory-accuracy audit whose unit-weighted score
decides whether the zone keeps trading or drops into an audit hold — and either
lever, once pulled on a zone that a live retrieval is reaching into, freezes the
delivery wave above it so hard that a pick operator cannot even open a fresh
tote until the window is completed and the grid is handed back. The commercial
side owns the other half of this file: a retrieval that comes back one unit
short turns the shopper's line into a shortage, the catalogue offers the closest
comparable item, and that offer then travels out to the shopper and back — sent
with a two-hour approval clock, approved to re-price the line from the
substitute's own shelf price and queue a second retrieval, left to lapse at the
expiry instant, or simply overtaken by a shopper who accepts the shortage and
lets the van leave without the item.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_field_absent_or_null,
    assert_instant_equals,
    assert_int_field,
    assert_money,
    assert_order_money,
    assert_order_statuses,
    assert_ratio,
    assert_sku_ledger,
    assert_station_status_matches_count,
    assert_status,
    assert_tote_shape,
    assert_wave_posture,
    list_items_and_meta,
    read_object,
)
from test_helpers.constants import ACCURACY_HOLD_THRESHOLD, DEFAULT_CLOCK_UTC
from test_helpers.test_users import make_customer_headers
from test_helpers.types import (
    BillingStatus,
    GridZoneStatus,
    LineStatus,
    MaintenanceWindowStatus,
    PickTaskStatus,
    ProposalStatus,
    SubstitutionResolution,
    TemperatureZone,
    ToteStatus,
    WavePosture,
    WaveStatus,
)

# The plant these situations are built on: a van route charging 599 cents before
# surge, one ambient grid zone stocked 100 units deep, and a shopper who orders
# two units of a 700-cent staple that the catalogue can replace with a 750-cent
# one from the same substitution group.
BASE_FEE_CENTS = 599
ORDERED_PRICE_CENTS = 700
SUBSTITUTE_PRICE_CENTS = 750
GRID_STOCK_UNITS = 100
LINE_QTY = 2
BOOKED_UNITS = 2
SUBSTITUTION_GROUP = "DRY-STAPLES"

# The basket the shopper confirms: two units at 700 cents is 1400 of merchandise,
# the delivery fee is 599 at a surge multiplier of 1.00, and a BASIC shopper
# earns no loyalty discount, so 1999 cents is authorized at confirmation time.
PROVISIONAL_LINE_CENTS = ORDERED_PRICE_CENTS * LINE_QTY
AUTHORIZED_CENTS = PROVISIONAL_LINE_CENTS + BASE_FEE_CENTS
SUBSTITUTED_LINE_CENTS = SUBSTITUTE_PRICE_CENTS * LINE_QTY
SUBSTITUTED_TOTAL_CENTS = SUBSTITUTED_LINE_CENTS + BASE_FEE_CENTS
SHORTAGE_TOTAL_CENTS = BASE_FEE_CENTS

# Two hours of approval clock measured from the boot instant of the logical clock.
PROPOSAL_EXPIRY_UTC = "2026-08-01T02:00:00.000Z"
MAINTENANCE_START_UTC = "2026-08-01T00:00:00.000Z"
MAINTENANCE_END_UTC = "2026-08-01T06:00:00.000Z"
TOMORROW_WINDOW_START_UTC = "2026-08-02T00:00:00.000Z"
TOMORROW_WINDOW_END_UTC = "2026-08-02T06:00:00.000Z"
INSIDE_TOMORROW_WINDOW_UTC = "2026-08-02T01:00:00.000Z"


def _plant(api):
    """A route, a bay, one ambient grid zone and a station that can serve it."""
    return fixtures.build_plant(
        api, route={"base_delivery_fee_cents": BASE_FEE_CENTS}
    )


def _picking_floor(api):
    """One shopper's two-unit line, waved and turned into a queued retrieval."""
    plant = _plant(api)
    sku = fixtures.create_inventory_sku(
        api,
        plant["zone"]["id"],
        unit_price_cents=ORDERED_PRICE_CENTS,
        physical_units=GRID_STOCK_UNITS,
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    picking = fixtures.build_picking_wave(
        api,
        plant["route"]["id"],
        slot["id"],
        [sku["id"]],
        ordered_qty=LINE_QTY,
        units=BOOKED_UNITS,
    )
    picking["plant"] = plant
    picking["sku"] = sku
    picking["slot"] = slot
    return picking


def _short_line_with_offer(api):
    """A one-unit-short retrieval and the substitution offer the grid raised."""
    plant = _plant(api)
    skus = fixtures.build_substitution_group(
        api,
        plant["zone"]["id"],
        SUBSTITUTION_GROUP,
        [ORDERED_PRICE_CENTS, SUBSTITUTE_PRICE_CENTS],
        physical_units=GRID_STOCK_UNITS,
    )
    slot = fixtures.create_delivery_slot(api, plant["route"]["id"])
    situation = fixtures.build_short_line(
        api,
        plant["route"]["id"],
        slot["id"],
        [skus[0]["id"]],
        ordered_qty=LINE_QTY,
        picked_units=1,
        units=BOOKED_UNITS,
    )
    situation["plant"] = plant
    situation["slot"] = slot
    situation["ordered_sku"] = skus[0]
    situation["substitute_sku"] = skus[1]
    situation["proposal"] = fixtures.proposal_for_line(api, situation["line"]["id"])
    return situation


def test_a_finished_retrieval_refuses_both_a_cancellation_and_a_second_completion(
    api, pick_operator_headers
):
    """A retrieval that came back complete is closed: neither the abandon lever nor a repeat completion reopens it.

    Cites the requirement it rests on: "A task's `status` is one of `QUEUED`, `RETRIEVING`, `COMPLETED`, `SHORT` and `CANCELLED`, of which the last three are terminal."

    Design: Corner/state_machines/completed_pick_task_rejects_cancel_and_a_second_complete
    """
    floor = _picking_floor(api)
    task = floor["tasks"][0]
    fixtures.drive_task_to_retrieving(
        api,
        task["id"],
        floor["wave"]["id"],
        task["pick_station_id"],
        TemperatureZone.AMBIENT.value,
    )
    fixtures.complete_pick_task(api, task["id"], LINE_QTY)

    abandon = api.cancel_pick_task(task["id"], pick_operator_headers)
    validate_error(abandon, ApiError.INVALID_STATE.value)

    repeat = api.complete_pick_task(
        task["id"], factories.complete_pick_task_payload(LINE_QTY), pick_operator_headers
    )
    validate_error(repeat, ApiError.INVALID_STATE.value)

    settled = fixtures.read_pick_task(api, task["id"])
    assert_status(settled, PickTaskStatus.COMPLETED.value)
    assert_int_field(settled, "picked_units", LINE_QTY)

    line = fixtures.read_order_line(
        api, floor["account"]["id"], floor["lines"][0]["id"]
    )
    assert_status(line, LineStatus.PICKED.value, field="line_status")


def test_a_full_quantity_pick_leaves_the_grid_ledger_untouched_by_the_two_refusals(
    api, pick_operator_headers
):
    """The two units taken off the shelf stay taken off it even after a rejected abandon and a rejected repeat.

    Cites the requirement it rests on: "The SKU's `physical_units` is reduced by the units picked and the task leaves the allocated set, which is precisely why the SKU's `on_hand_units` is unchanged across a full-quantity completion."

    Design: Corner/state_machines/completed_pick_task_rejects_cancel_and_a_second_complete
    """
    floor = _picking_floor(api)
    task = floor["tasks"][0]
    fixtures.drive_task_to_retrieving(
        api,
        task["id"],
        floor["wave"]["id"],
        task["pick_station_id"],
        TemperatureZone.AMBIENT.value,
    )
    fixtures.complete_pick_task(api, task["id"], LINE_QTY)

    validate_error(
        api.cancel_pick_task(task["id"], pick_operator_headers),
        ApiError.INVALID_STATE.value,
    )
    validate_error(
        api.complete_pick_task(
            task["id"], factories.complete_pick_task_payload(LINE_QTY), pick_operator_headers
        ),
        ApiError.INVALID_STATE.value,
    )

    sku = fixtures.read_inventory_sku(api, floor["sku"]["id"])
    assert_sku_ledger(
        sku,
        physical_units=GRID_STOCK_UNITS - LINE_QTY,
        allocated_units=0,
        on_hand_units=GRID_STOCK_UNITS - LINE_QTY,
    )


def test_taking_the_grid_zone_down_for_maintenance_freezes_the_wave_and_bars_a_new_tote(
    api, pick_operator_headers
):
    """While the only zone the wave retrieves from sits in maintenance, the pick operator cannot open a tote for it.

    Cites the requirement it rests on: "A `FROZEN` posture blocks consolidation, dock assignment, loading sequencing, dispatch, opening a tote, sealing a tote and unsealing a tote, all with `ERR_WAVE_FROZEN`."

    Design: Corner/state_machines/zone_maintenance_freezes_the_wave_then_completion_reopens_it
    """
    floor = _picking_floor(api)
    zone_id = floor["plant"]["zone"]["id"]
    window = fixtures.create_maintenance_window(
        api,
        zone_id,
        window_start=MAINTENANCE_START_UTC,
        window_end=MAINTENANCE_END_UTC,
    )
    window = fixtures.activate_maintenance_window(api, window["id"])

    assert_status(window, MaintenanceWindowStatus.ACTIVE.value)
    assert_status(
        fixtures.read_grid_zone(api, zone_id), GridZoneStatus.MAINTENANCE.value
    )
    frozen_wave = fixtures.read_wave(api, floor["wave"]["id"])
    assert_wave_posture(frozen_wave, WavePosture.FROZEN.value)
    assert_status(frozen_wave, WaveStatus.PICKING.value)

    refused = api.create_tote(
        factories.tote_payload(
            floor["wave"]["id"],
            floor["plant"]["station"]["id"],
            temperature_zone=TemperatureZone.AMBIENT.value,
        ),
        pick_operator_headers,
    )
    validate_error(refused, ApiError.WAVE_FROZEN.value)

    totes, meta = list_items_and_meta(
        api.list_totes(pick_operator_headers, params={"wave_id": floor["wave"]["id"]})
    )
    assert totes == [], "no tote may exist on a wave frozen by a maintenance window"
    assert meta["total_count"] == 0, (
        f"a frozen wave should hold no tote, meta reports {meta['total_count']}"
    )
    assert_int_field(
        fixtures.read_pick_station(api, floor["plant"]["station"]["id"]),
        "current_tote_count",
        0,
    )


def test_handing_the_grid_back_after_maintenance_reopens_the_wave_for_tote_work(
    api, pick_operator_headers
):
    """Completing the window returns the zone to service and the wave to an open posture, so the same tote may now be opened.

    Cites the requirement it rests on: "The window advances `ACTIVE → COMPLETED`, which is terminal, and the zone advances `MAINTENANCE → OPERATIONAL`, closing the first of the zone's two cycles: a zone travels `OPERATIONAL → MAINTENANCE → OPERATIONAL` and is then free to be taken down again by a later window."

    Design: Corner/state_machines/zone_maintenance_freezes_the_wave_then_completion_reopens_it
    """
    floor = _picking_floor(api)
    zone_id = floor["plant"]["zone"]["id"]
    station_id = floor["plant"]["station"]["id"]
    window = fixtures.create_maintenance_window(
        api,
        zone_id,
        window_start=MAINTENANCE_START_UTC,
        window_end=MAINTENANCE_END_UTC,
    )
    fixtures.activate_maintenance_window(api, window["id"])
    validate_error(
        api.create_tote(
            factories.tote_payload(
                floor["wave"]["id"],
                station_id,
                temperature_zone=TemperatureZone.AMBIENT.value,
            ),
            pick_operator_headers,
        ),
        ApiError.WAVE_FROZEN.value,
    )

    reopened_window = fixtures.complete_maintenance_window(api, window["id"])
    assert_status(reopened_window, MaintenanceWindowStatus.COMPLETED.value)
    assert_status(
        fixtures.read_grid_zone(api, zone_id), GridZoneStatus.OPERATIONAL.value
    )
    thawed_wave = fixtures.read_wave(api, floor["wave"]["id"])
    assert_wave_posture(thawed_wave, WavePosture.OPEN.value)
    assert_status(thawed_wave, WaveStatus.PICKING.value)

    accepted = api.create_tote(
        factories.tote_payload(
            floor["wave"]["id"],
            station_id,
            temperature_zone=TemperatureZone.AMBIENT.value,
        ),
        pick_operator_headers,
    )
    tote = read_object(accepted, expected_status=201)
    assert_tote_shape(tote)
    assert_status(tote, ToteStatus.OPEN.value)
    assert tote["temperature_zone"] == TemperatureZone.AMBIENT.value

    station = fixtures.read_pick_station(api, station_id)
    assert_int_field(station, "current_tote_count", 1)
    assert_station_status_matches_count(station)


def test_a_window_scheduled_for_tomorrow_can_be_neither_activated_nor_completed_today(
    api, grid_engineer_headers
):
    """The engineer cannot stop the bots before the declared window opens, nor close a window that never opened.

    Cites the requirement it rests on: "The window must be `SCHEDULED`; the logical clock must lie inside the declared interval, meaning `window_start` is at or before `clock_now` and `clock_now` is strictly before `window_end` — a window activated too early or after its end has passed is refused with `ERR_INVALID_STATE`; and the zone must currently be `OPERATIONAL`, or the request is refused with `ERR_ZONE_NOT_OPERATIONAL`."

    Design: Corner/state_machines/maintenance_window_activation_requires_the_clock_inside_the_window
    """
    zone = fixtures.create_grid_zone(api)
    window = fixtures.create_maintenance_window(
        api,
        zone["id"],
        window_start=TOMORROW_WINDOW_START_UTC,
        window_end=TOMORROW_WINDOW_END_UTC,
    )

    too_early = api.activate_maintenance_window(window["id"], grid_engineer_headers)
    validate_error(too_early, ApiError.INVALID_STATE.value)

    never_opened = api.complete_maintenance_window(window["id"], grid_engineer_headers)
    validate_error(never_opened, ApiError.INVALID_STATE.value)

    still_scheduled = read_object(
        api.get_maintenance_window(window["id"], grid_engineer_headers)
    )
    assert_status(still_scheduled, MaintenanceWindowStatus.SCHEDULED.value)
    assert_status(
        fixtures.read_grid_zone(api, zone["id"]), GridZoneStatus.OPERATIONAL.value
    )


def test_a_window_opens_once_the_clock_enters_it_and_refuses_a_second_activation(
    api, grid_engineer_headers
):
    """Advancing the clock into the declared interval is what makes activation legal, and once the bots are stopped they cannot be stopped again.

    Cites the requirement it rests on: "On success the window advances `SCHEDULED → ACTIVE` and the zone advances `OPERATIONAL → MAINTENANCE`."

    Design: Corner/state_machines/maintenance_window_activation_requires_the_clock_inside_the_window
    """
    zone = fixtures.create_grid_zone(api)
    window = fixtures.create_maintenance_window(
        api,
        zone["id"],
        window_start=TOMORROW_WINDOW_START_UTC,
        window_end=TOMORROW_WINDOW_END_UTC,
    )
    validate_error(
        api.activate_maintenance_window(window["id"], grid_engineer_headers),
        ApiError.INVALID_STATE.value,
    )

    fixtures.set_clock(api, INSIDE_TOMORROW_WINDOW_UTC)
    activated = read_object(
        api.activate_maintenance_window(window["id"], grid_engineer_headers)
    )
    assert_status(activated, MaintenanceWindowStatus.ACTIVE.value)
    assert_status(
        fixtures.read_grid_zone(api, zone["id"]), GridZoneStatus.MAINTENANCE.value
    )

    again = api.activate_maintenance_window(window["id"], grid_engineer_headers)
    validate_error(again, ApiError.INVALID_STATE.value)

    unchanged = read_object(
        api.get_maintenance_window(window["id"], grid_engineer_headers)
    )
    assert_status(unchanged, MaintenanceWindowStatus.ACTIVE.value)
    assert_status(
        fixtures.read_grid_zone(api, zone["id"]), GridZoneStatus.MAINTENANCE.value
    )


def test_counting_three_units_short_drops_the_zone_into_an_audit_hold(api):
    """A count of 97 against a system figure of 100 scores below the accuracy threshold and takes the zone out of service.

    Cites the requirement it rests on: "When `accuracy_score_unit_weighted` is **strictly less** than `ACCURACY_HOLD_THRESHOLD` — 0.9800 — the zone's status is set to `AUDIT_HOLD`; when it is greater than or equal to the threshold the zone's status is set to `OPERATIONAL`."

    Design: Corner/state_machines/audit_hold_clears_to_operational_only_on_a_second_clean_recount
    """
    zone = fixtures.create_grid_zone(api)
    sku = fixtures.create_inventory_sku(
        api,
        zone["id"],
        unit_price_cents=ORDERED_PRICE_CENTS,
        physical_units=GRID_STOCK_UNITS,
    )

    fixtures.record_audit_counts(api, zone["id"], [(sku["id"], 97)])

    held = fixtures.read_grid_zone(api, zone["id"])
    assert_status(held, GridZoneStatus.AUDIT_HOLD.value)
    assert_ratio(held, "accuracy_score_unit_weighted", 0.9700)
    assert_ratio(held, "accuracy_score_sku_weighted", 0.9700)
    assert float(held["accuracy_score_unit_weighted"]) < ACCURACY_HOLD_THRESHOLD, (
        "a zone is held only because its unit-weighted score fell under the threshold"
    )
    assert_instant_equals(held["last_audited_at"], DEFAULT_CLOCK_UTC, "last_audited_at")

    counted = fixtures.read_inventory_sku(api, sku["id"])
    assert_int_field(counted, "last_count_system_units", GRID_STOCK_UNITS)
    assert_int_field(counted, "last_count_counted_units", 97)
    assert_int_field(counted, "last_count_variance_units", -3)
    assert_sku_ledger(
        counted, physical_units=97, allocated_units=0, on_hand_units=97
    )


def test_an_identical_recount_against_the_rewritten_baseline_releases_the_audit_hold(
    api,
):
    """Because the first audit rewrote the shelf figure to 97, recounting 97 scores a clean 1.0000 and hands the zone back.

    Cites the requirement it rests on: "Only after those three fields are written is the SKU's `physical_units` overwritten with the counted figure, and its `allocated_units` and `on_hand_units` are recomputed by the SKU unit ledger of §2.9."

    Design: Corner/state_machines/audit_hold_clears_to_operational_only_on_a_second_clean_recount
    """
    zone = fixtures.create_grid_zone(api)
    sku = fixtures.create_inventory_sku(
        api,
        zone["id"],
        unit_price_cents=ORDERED_PRICE_CENTS,
        physical_units=GRID_STOCK_UNITS,
    )
    fixtures.record_audit_counts(api, zone["id"], [(sku["id"], 97)])
    assert_status(
        fixtures.read_grid_zone(api, zone["id"]), GridZoneStatus.AUDIT_HOLD.value
    )

    fixtures.record_audit_counts(api, zone["id"], [(sku["id"], 97)])

    released = fixtures.read_grid_zone(api, zone["id"])
    assert_status(released, GridZoneStatus.OPERATIONAL.value)
    assert_ratio(released, "accuracy_score_unit_weighted", 1.0000)
    assert_ratio(released, "accuracy_score_sku_weighted", 1.0000)

    recounted = fixtures.read_inventory_sku(api, sku["id"])
    assert_int_field(recounted, "last_count_system_units", 97)
    assert_int_field(recounted, "last_count_counted_units", 97)
    assert_int_field(recounted, "last_count_variance_units", 0)
    assert_sku_ledger(
        recounted, physical_units=97, allocated_units=0, on_hand_units=97
    )


def test_sending_the_grids_substitute_offer_to_the_shopper_starts_a_two_hour_clock(api):
    """The offer the grid raised for the short line goes out to the shopper priced at its exact delta and expires two hours later.

    Cites the requirement it rests on: "On success `expires_at` is set to the current instant plus two hours — that is, plus 120 minutes."

    Design: Corner/state_machines/propose_then_approve_returns_the_short_line_to_pending_and_reprices_it
    """
    situation = _short_line_with_offer(api)
    draft = situation["proposal"]

    assert_status(draft, ProposalStatus.DRAFT.value)
    assert_int_field(draft, "round_no", 1)
    assert draft["substitute_sku_id"] == situation["substitute_sku"]["id"], (
        "the closest comparable item in the substitution group should be offered"
    )
    assert_money(
        draft,
        "proposed_price_delta_cents",
        SUBSTITUTED_LINE_CENTS - PROVISIONAL_LINE_CENTS,
    )
    assert_field_absent_or_null(draft, "expires_at")

    offered = fixtures.propose_substitution(api, draft["id"])
    assert_status(offered, ProposalStatus.PROPOSED.value)
    assert_instant_equals(offered["expires_at"], PROPOSAL_EXPIRY_UTC, "expires_at")


def test_the_shoppers_approval_returns_the_short_line_to_pending_and_reprices_it(api):
    """Approving the substitute re-prices the line from the substitute's own shelf price and queues a fresh retrieval for it.

    Cites the requirement it rests on: "The line's `final_line_price_cents` is rewritten as the substitute SKU's `unit_price_cents` multiplied by the line's `ordered_qty`."

    Design: Corner/state_machines/propose_then_approve_returns_the_short_line_to_pending_and_reprices_it
    """
    situation = _short_line_with_offer(api)
    account_id = situation["account"]["id"]
    line_id = situation["line"]["id"]
    fixtures.propose_substitution(api, situation["proposal"]["id"])

    approved = fixtures.approve_substitution(
        api, account_id, situation["proposal"]["id"]
    )
    assert_status(approved, ProposalStatus.APPROVED.value)

    line = fixtures.read_order_line(api, account_id, line_id)
    assert_status(line, LineStatus.PENDING.value, field="line_status")
    assert_status(
        line,
        SubstitutionResolution.SUBSTITUTED.value,
        field="substitution_resolution",
    )
    assert_money(line, "final_line_price_cents", SUBSTITUTED_LINE_CENTS)
    assert_money(line, "provisional_line_price_cents", PROVISIONAL_LINE_CENTS)
    assert_field_absent_or_null(line, "picked_units")

    tasks = fixtures.list_pick_tasks(api, order_line_id=line_id)
    assert len(tasks) == 2, (
        f"the short retrieval and its replacement should both exist, got {len(tasks)}"
    )
    replacement = [t for t in tasks if t["status"] == PickTaskStatus.QUEUED.value]
    assert len(replacement) == 1, "exactly one fresh retrieval should be queued"
    replacement = replacement[0]
    assert replacement["sku_id"] == situation["substitute_sku"]["id"]
    assert_int_field(replacement, "allocated_units", LINE_QTY)
    assert replacement["pick_station_id"] == situation["plant"]["station"]["id"]


def test_approving_the_substitute_moves_the_allocation_and_readjusts_the_charge(api):
    """The substitute's units are reserved, the shortfall leaves the ordered item's shelf, and the order total is re-struck above what was authorized.

    Cites the requirement it rests on: "the charge waterfall re-runs with the money dimension advancing `AUTHORIZED → ADJUSTED` when the total changed, the wave's posture is recomputed, and the order's `version` is incremented by 1."

    Design: Corner/state_machines/propose_then_approve_returns_the_short_line_to_pending_and_reprices_it
    """
    situation = _short_line_with_offer(api)
    account_id = situation["account"]["id"]
    fixtures.propose_substitution(api, situation["proposal"]["id"])
    fixtures.approve_substitution(api, account_id, situation["proposal"]["id"])

    substitute = fixtures.read_inventory_sku(api, situation["substitute_sku"]["id"])
    assert_sku_ledger(
        substitute,
        physical_units=GRID_STOCK_UNITS,
        allocated_units=LINE_QTY,
        on_hand_units=GRID_STOCK_UNITS - LINE_QTY,
    )
    ordered = fixtures.read_inventory_sku(api, situation["ordered_sku"]["id"])
    assert_sku_ledger(
        ordered,
        physical_units=GRID_STOCK_UNITS - 1,
        allocated_units=0,
        on_hand_units=GRID_STOCK_UNITS - 1,
    )

    order = fixtures.read_order(api, account_id, situation["order"]["id"])
    assert_order_money(
        order,
        merchandise_subtotal_cents=SUBSTITUTED_LINE_CENTS,
        delivery_fee_cents=BASE_FEE_CENTS,
        loyalty_discount_cents=0,
        order_total_cents=SUBSTITUTED_TOTAL_CENTS,
        authorized_amount_cents=AUTHORIZED_CENTS,
    )
    assert_order_statuses(order, billing_status=BillingStatus.ADJUSTED.value)
    assert order["dispatch_blocked"] is False, (
        "no line of the order is awaiting a substitution decision any more"
    )
    assert_int_field(order, "open_substitution_count", 0)

    wave = fixtures.read_wave(api, situation["wave"]["id"])
    assert_wave_posture(wave, WavePosture.OPEN.value)
    assert_status(wave, WaveStatus.PICKING.value)


def test_an_offer_still_sitting_in_draft_answers_neither_approval_nor_refusal(api):
    """The shopper cannot answer an offer the pick operator has not yet sent out.

    Cites the requirement it rests on: "The target resource is in a state from which the requested transition exists, and every precondition of that transition that concerns the target resource itself holds — for instance a tote must be `OPEN` to be sealed, a retrieval task must be `RETRIEVING` to be completed, a wave must be `CONSOLIDATED` to be sequenced for loading, and a booking must be `HELD` to be confirmed."

    Design: Corner/state_machines/proposal_lifecycle_rejects_approval_from_draft_and_at_the_ttl_boundary
    """
    situation = _short_line_with_offer(api)
    shopper = make_customer_headers(situation["account"]["id"])
    proposal_id = situation["proposal"]["id"]

    early_approval = api.approve_substitution(proposal_id, shopper)
    validate_error(early_approval, ApiError.INVALID_STATE.value)

    early_refusal = api.decline_substitution(proposal_id, shopper)
    validate_error(early_refusal, ApiError.INVALID_STATE.value)

    untouched = fixtures.read_substitution_proposal(api, proposal_id)
    assert_status(untouched, ProposalStatus.DRAFT.value)
    assert_field_absent_or_null(untouched, "expires_at")


def test_at_the_expiry_instant_approval_is_refused_and_retirement_becomes_legal(
    api, wave_planner_headers
):
    """Retiring the offer is too early one instant before its expiry and approving it is too late at that very instant.

    Cites the requirement it rests on: "Substitution timing holds: a proposal in `PROPOSED` status may be approved or declined only while the clock is strictly earlier than its `expires_at`, and a violation there is `ERR_PROPOSAL_EXPIRED` (409); conversely, retiring a proposal as expired requires the clock to be at or after `expires_at`, and a violation there is `ERR_PROPOSAL_NOT_EXPIRED` (409)."

    Design: Corner/state_machines/proposal_lifecycle_rejects_approval_from_draft_and_at_the_ttl_boundary
    """
    situation = _short_line_with_offer(api)
    shopper = make_customer_headers(situation["account"]["id"])
    proposal_id = situation["proposal"]["id"]
    offered = fixtures.propose_substitution(api, proposal_id)
    assert_instant_equals(offered["expires_at"], PROPOSAL_EXPIRY_UTC, "expires_at")

    too_early = api.expire_substitution(proposal_id, wave_planner_headers)
    validate_error(too_early, ApiError.PROPOSAL_NOT_EXPIRED.value)
    assert_status(
        fixtures.read_substitution_proposal(api, proposal_id),
        ProposalStatus.PROPOSED.value,
    )

    fixtures.set_clock(api, PROPOSAL_EXPIRY_UTC)

    too_late = api.approve_substitution(proposal_id, shopper)
    validate_error(too_late, ApiError.PROPOSAL_EXPIRED.value)

    retired = read_object(api.expire_substitution(proposal_id, wave_planner_headers))
    assert_status(retired, ProposalStatus.EXPIRED.value)


def test_a_lapsed_offer_leaves_the_line_short_and_the_wave_restricted(api):
    """Retiring an unanswered offer closes the round without closing the shortage, so the order stays dispatch-blocked.

    Cites the requirement it rests on: "Like a refusal, it leaves the line's `substitution_resolution` at `PENDING` and merely decrements the order's `open_substitution_count`, so the order stays dispatch-blocked."

    Design: Corner/state_machines/proposal_lifecycle_rejects_approval_from_draft_and_at_the_ttl_boundary
    """
    situation = _short_line_with_offer(api)
    account_id = situation["account"]["id"]
    line_id = situation["line"]["id"]
    fixtures.propose_substitution(api, situation["proposal"]["id"])
    fixtures.set_clock(api, PROPOSAL_EXPIRY_UTC)
    fixtures.expire_substitution(api, situation["proposal"]["id"])

    line = fixtures.read_order_line(api, account_id, line_id)
    assert_status(line, LineStatus.SHORT.value, field="line_status")
    assert_status(
        line, SubstitutionResolution.PENDING.value, field="substitution_resolution"
    )
    assert_field_absent_or_null(line, "final_line_price_cents")

    order = fixtures.read_order(api, account_id, situation["order"]["id"])
    assert_int_field(order, "open_substitution_count", 0)
    assert order["dispatch_blocked"] is True, (
        "a line still awaiting a substitution decision keeps the order blocked"
    )
    assert_order_money(
        order,
        merchandise_subtotal_cents=0,
        order_total_cents=SHORTAGE_TOTAL_CENTS,
    )

    assert_wave_posture(
        fixtures.read_wave(api, situation["wave"]["id"]), WavePosture.RESTRICTED.value
    )
    tasks = fixtures.list_pick_tasks(api, order_line_id=line_id)
    assert len(tasks) == 1, (
        f"a retired offer creates no replacement retrieval, got {len(tasks)} tasks"
    )


def test_accepting_the_shortage_retires_the_offer_the_shopper_never_saw(api):
    """The shopper's escape hatch cancels the line, force-retires the draft offer beside it and lets the wave breathe again.

    Cites the requirement it rests on: "Every substitution proposal on that line whose status is `DRAFT` or `PROPOSED` is moved to `EXPIRED` — both the `DRAFT → EXPIRED` and the `PROPOSED → EXPIRED` edges fire here, and each one decrements the order's `open_substitution_count`."

    Design: Corner/state_machines/accept_shortage_expires_the_draft_proposal_then_rejects_a_repeat
    """
    situation = _short_line_with_offer(api)
    account_id = situation["account"]["id"]
    line_id = situation["line"]["id"]

    fixtures.accept_shortage(api, account_id, line_id)

    line = fixtures.read_order_line(api, account_id, line_id)
    assert_status(line, LineStatus.CANCELLED.value, field="line_status")
    assert_status(
        line,
        SubstitutionResolution.SHORTAGE_ACCEPTED.value,
        field="substitution_resolution",
    )
    assert_status(
        fixtures.read_substitution_proposal(api, situation["proposal"]["id"]),
        ProposalStatus.EXPIRED.value,
    )

    order = fixtures.read_order(api, account_id, situation["order"]["id"])
    assert_int_field(order, "open_substitution_count", 0)
    assert order["dispatch_blocked"] is False, (
        "an accepted shortage leaves no line awaiting a substitution decision"
    )
    assert_order_money(
        order,
        merchandise_subtotal_cents=0,
        delivery_fee_cents=BASE_FEE_CENTS,
        order_total_cents=SHORTAGE_TOTAL_CENTS,
        authorized_amount_cents=AUTHORIZED_CENTS,
    )
    assert_order_statuses(order, billing_status=BillingStatus.ADJUSTED.value)
    assert_wave_posture(
        fixtures.read_wave(api, situation["wave"]["id"]), WavePosture.OPEN.value
    )


def test_a_second_shortage_acceptance_on_the_same_line_is_refused(api):
    """Once the shortage is accepted the line is no longer awaiting a decision, so the shopper cannot accept it twice.

    Cites the requirement it rests on: "The line must have `substitution_resolution` `PENDING`, or the request is refused with `ERR_LINE_NOT_SHORT`, and the acting `X-User-ID` must equal the `customer_id` of the line's order."

    Design: Corner/state_machines/accept_shortage_expires_the_draft_proposal_then_rejects_a_repeat
    """
    situation = _short_line_with_offer(api)
    account_id = situation["account"]["id"]
    line_id = situation["line"]["id"]
    fixtures.accept_shortage(api, account_id, line_id)

    repeat = api.accept_shortage(line_id, make_customer_headers(account_id))
    validate_error(repeat, ApiError.LINE_NOT_SHORT.value)

    line = fixtures.read_order_line(api, account_id, line_id)
    assert_status(
        line,
        SubstitutionResolution.SHORTAGE_ACCEPTED.value,
        field="substitution_resolution",
    )
    assert_status(line, LineStatus.CANCELLED.value, field="line_status")
    order = fixtures.read_order(api, account_id, situation["order"]["id"])
    assert_order_money(order, order_total_cents=SHORTAGE_TOTAL_CENTS)
