"""The clearance cadence: windows, stages, the two price variants and liquidation."""
import pytest

from test_helpers import api_client, validate_success, validate_error, validate_paginated, ApiErrorId
from test_helpers import factories as f
from test_helpers.fixtures import (
    ADMIN, MANAGER, LEAD, PLANNER,
    create_item, setup_store, setup_open_day, open_store_day, create_clearance_schedule,
    activate_clearance, advance_cadence, stock_item, received_transfer, shift_iso,
    get_item, get_clearance_schedule, get_location, get_store_day, close_store_day,
    settled_receipt,
)

DECOR_2400, DECOR_1300 = "ITM-DECOR-2400", "ITM-DECOR-1300"


def _decor_2400():
    return create_item(sku=DECOR_2400, name="Harvest Wall Plaque", theme_code="SUMMER",
                       unit_retail_cents=2400, unit_cost_cents=900, import_lead_time_days=40)


def _decor_1300():
    return create_item(sku=DECOR_1300, name="Porch Sign", theme_code="SUMMER",
                       unit_retail_cents=1300, unit_cost_cents=500, import_lead_time_days=40)


def _schedule_to_s4(loc, day, item, units, start="2026-09-21T00:00:00Z",
                    end="2026-10-21T00:00:00Z", activated_clock="2026-09-21T00:00:00Z"):
    """Stock the item, activate a schedule at `activated_clock`, then cross four whole
    weeks so the stage reaches S4. Returns the schedule at S4."""
    transfer = stock_item(loc["id"], day["id"], item["id"], units)
    # PRD 3.8 allows activation only while the logical clock falls inside the
    # window, so the clock is placed at the window's start before activating.
    validate_success(api_client.set_clock(activated_clock, ADMIN))
    schedule = activate_clearance(item["id"], loc["id"], start, end)
    advance_cadence(transfer["id"], shift_iso(activated_clock, days=28))
    return get_clearance_schedule(schedule["id"])


# ==========================================================================
# Difficulty queue A — transitive_cascade (clearance activation)
# ==========================================================================

def test_clearance_activation_writes_the_item_markdown_price(api):
    """PRD §3.8: "activation stamps `activated_at` from the logical clock, freezes the
    schedule's `remaining_units` at the item's current `on_hand_units`, sets `stage` to
    `S1` and applies that stage's markdown percent of 0.25, mirrors that percent onto the
    item's `current_markdown_pct`"
    PRD §2.9: "`effective_price_cents` is the **highest-of-stacked** price"

    Design: Difficulty/transitive_cascade/clearance_activation_cascades_three_hops_to_the_location_slot_counter
    """
    # PRD 3.7 makes clearance_max_active a Location input (default 3), so the cap
    # belongs on the location; a brand payload cannot carry it.
    brand = api.create_brand(f.create_brand_payload(food_storage_corridor_units=310),
                             ADMIN).json()["data"]
    loc = api.create_location(
        f.create_location_payload(brand["id"], clearance_max_active=1), ADMIN).json()["data"]
    day = open_store_day(loc["id"], "2026-09-20T00:00:00Z")
    item = _decor_2400()
    stock_item(loc["id"], day["id"], item["id"], 5)
    current = get_item(item["id"])
    schedule = create_clearance_schedule(loc["id"], item["id"], current["version"],
                                         start_date="2026-09-01T00:00:00Z",
                                         end_date="2026-10-01T00:00:00Z")

    data = validate_success(api.activate_clearance_schedule(schedule["id"], MANAGER))

    assert data["status"] == "ACTIVE"
    assert data["stage"] == "S1"
    refreshed = get_item(item["id"])
    assert refreshed["current_markdown_pct"] == 0.25
    assert refreshed["effective_price_cents"] == 1800


def test_clearance_activation_moves_the_location_slot_counter(api):
    """PRD §3.8: "increases the location's `active_clearance_count` by one"
    PRD §3.8: "A location already at its limit refuses the activation with
    `ERR_CLEARANCE_SLOT_LIMIT` (HTTP 409) at priority 14"

    Design: Difficulty/transitive_cascade/clearance_activation_cascades_three_hops_to_the_location_slot_counter
    """
    # PRD 3.7 makes clearance_max_active a Location input (default 3), so the cap
    # belongs on the location; a brand payload cannot carry it.
    brand = api.create_brand(f.create_brand_payload(food_storage_corridor_units=310),
                             ADMIN).json()["data"]
    loc = api.create_location(
        f.create_location_payload(brand["id"], clearance_max_active=1), ADMIN).json()["data"]
    day = open_store_day(loc["id"], "2026-09-20T00:00:00Z")
    item_a = _decor_2400()
    item_b = _decor_1300()
    stock_item(loc["id"], day["id"], item_a["id"], 5)
    stock_item(loc["id"], day["id"], item_b["id"], 3)
    cur_a, cur_b = get_item(item_a["id"]), get_item(item_b["id"])
    sched_a = create_clearance_schedule(loc["id"], item_a["id"], cur_a["version"],
                                        start_date="2026-09-01T00:00:00Z",
                                        end_date="2026-10-01T00:00:00Z")
    sched_b = create_clearance_schedule(loc["id"], item_b["id"], cur_b["version"],
                                        start_date="2026-09-15T00:00:00Z",
                                        end_date="2026-10-20T00:00:00Z")
    validate_success(api.activate_clearance_schedule(sched_a["id"], MANAGER))

    assert get_location(loc["id"])["active_clearance_count"] == 1

    validate_error(api.activate_clearance_schedule(sched_b["id"], MANAGER),
                   ApiErrorId.ERR_CLEARANCE_SLOT_LIMIT.value)
    assert get_clearance_schedule(sched_b["id"])["status"] == "DRAFT"
    assert get_item(item_b["id"])["effective_price_cents"] == 1300


# ==========================================================================
# Difficulty queue A — resource_temporal_overlap (buffered window)
# ==========================================================================

def test_a_clearance_window_must_clear_the_buffer_gap(api):
    """PRD §3.8: "no two non-cancelled windows on the same location and item pair may be
    closer than the brand's `clearance_buffer_hours`, which defaults to 24 hours. A gap of
    zero between windows is a rejection, not an acceptance"
    PRD §3.8: "the refusal is `ERR_CLEARANCE_WINDOW_OVERLAP` (HTTP 409) at priority 13"

    Design: Difficulty/resource_temporal_overlap/clearance_windows_require_a_strictly_positive_buffer_gap
    """
    brand, loc, day = setup_open_day(brand_overrides={"clearance_buffer_hours": 24,
                                                      "food_storage_corridor_units": 310})
    item = _decor_2400()
    cur = get_item(item["id"])
    create_clearance_schedule(loc["id"], item["id"], cur["version"],
                              start_date="2026-09-01T00:00:00Z", end_date="2026-10-01T00:00:00Z")

    zero_gap = f.create_clearance_schedule_payload(loc["id"], item["id"], cur["version"],
                                                   start_date="2026-10-01T00:00:00Z",
                                                   end_date="2026-10-20T00:00:00Z")
    validate_error(api.create_clearance_schedule(zero_gap, MANAGER),
                   ApiErrorId.ERR_CLEARANCE_WINDOW_OVERLAP.value)

    short = f.create_clearance_schedule_payload(loc["id"], item["id"], cur["version"],
                                                start_date="2026-10-01T23:59:59Z",
                                                end_date="2026-10-20T00:00:00Z")
    validate_error(api.create_clearance_schedule(short, MANAGER),
                   ApiErrorId.ERR_CLEARANCE_WINDOW_OVERLAP.value)

    exact = f.create_clearance_schedule_payload(loc["id"], item["id"], cur["version"],
                                                start_date="2026-10-02T00:00:00Z",
                                                end_date="2026-10-20T00:00:00Z")
    admitted = validate_success(api.create_clearance_schedule(exact, MANAGER), 201)
    assert admitted["status"] == "DRAFT"


def test_rejected_clearance_windows_leave_no_rows_behind(api):
    """PRD §3.8: "Two rules govern where a window may be placed."
    PRD §3.8: "The window is treated as the half-open interval from its `start_date`
    inclusive to its `end_date` exclusive"

    Design: Difficulty/resource_temporal_overlap/clearance_windows_require_a_strictly_positive_buffer_gap
    """
    brand, loc, day = setup_open_day(brand_overrides={"clearance_buffer_hours": 24,
                                                      "food_storage_corridor_units": 310})
    item = _decor_2400()
    cur = get_item(item["id"])
    create_clearance_schedule(loc["id"], item["id"], cur["version"],
                              start_date="2026-09-01T00:00:00Z", end_date="2026-10-01T00:00:00Z")
    for start in ("2026-10-01T00:00:00Z", "2026-10-01T23:59:59Z"):
        payload = f.create_clearance_schedule_payload(loc["id"], item["id"], cur["version"],
                                                      start_date=start,
                                                      end_date="2026-10-20T00:00:00Z")
        api.create_clearance_schedule(payload, MANAGER)
    validate_success(api.create_clearance_schedule(
        f.create_clearance_schedule_payload(loc["id"], item["id"], cur["version"],
                                            start_date="2026-10-02T00:00:00Z",
                                            end_date="2026-10-20T00:00:00Z"), MANAGER), 201)

    data, meta = validate_paginated(
        api.list_clearance_schedules(MANAGER, {"item_id": item["id"]})
    )
    assert meta["total_count"] == 2


# ==========================================================================
# Corner queue B — calculations
# ==========================================================================

def test_liquidation_waterfall_fills_all_three_buckets_at_five_units(api):
    """PRD §3.8: "the first stage takes 40 percent of the units at a rate of 0.90, the
    second takes 30 percent at 0.70, and the third takes 30 percent at 0.55"
    PRD §3.8: "`liquidation_bucket_units` is the list of unit counts, in stage order, that
    the waterfall produced."

    Design: Corner/calculations/liquidation_waterfall_allocates_across_three_buckets
    """
    brand, loc = setup_store()
    day = open_store_day(loc["id"], "2026-09-21T00:00:00Z")
    item = _decor_2400()
    schedule = _schedule_to_s4(loc, day, item, 5)
    assert schedule["stage"] == "S4"

    data = validate_success(api.liquidate_clearance_schedule(schedule["id"], MANAGER))

    # PRD 3.8: each stage takes floor(total * share) limited to what remains, and
# only then do the stragglers spill into one final bucket at 0.55:
#   stage1 floor(5*0.40)=2 (3 left), stage2 floor(5*0.30)=1 (2 left),
#   stage3 floor(5*0.30)=1 (1 left), final bucket 1 -> [2, 1, 1, 1].
    assert data["liquidation_bucket_units"] == [2, 1, 1, 1]
    assert data["liquidation_price_cents"] == 810
    assert data["liquidated_units"] == 5


def test_liquidation_discontinues_the_item_and_empties_its_stock(api):
    """PRD §3.8: "On liquidation the schedule's `liquidated_units` takes the value of its
    `remaining_units` and `remaining_units` is reset to zero"
    PRD §3.8: "the item's `status` moves to `DISCONTINUED`; and the location's
    `active_clearance_count` is reduced by one"

    Design: Corner/calculations/liquidation_waterfall_allocates_across_three_buckets
    """
    brand, loc = setup_store()
    day = open_store_day(loc["id"], "2026-09-21T00:00:00Z")
    item = _decor_2400()
    schedule = _schedule_to_s4(loc, day, item, 5)

    validate_success(api.liquidate_clearance_schedule(schedule["id"], MANAGER))

    refreshed = get_item(item["id"])
    assert refreshed["status"] == "DISCONTINUED"
    assert refreshed["on_hand_units"] == 0
    assert get_clearance_schedule(schedule["id"])["remaining_units"] == 0


def test_liquidation_waterfall_collapses_to_one_bucket_at_three_units(api):
    """PRD §3.8: "a stage whose share of the total falls below one whole unit takes nothing
    at all and is skipped. After the three stages, any units still unspilled are gathered
    into one final bucket priced at the third stage's rate of 0.55."
    PRD §3.8: "a schedule with three remaining units floors the first stage to a single unit
    and floors the second and third stages to nothing"

    Design: Corner/calculations/liquidation_waterfall_skips_the_third_bucket_at_three_units
    """
    brand, loc = setup_store()
    day = open_store_day(loc["id"], "2026-09-21T00:00:00Z")
    item = _decor_1300()
    schedule = _schedule_to_s4(loc, day, item, 3)

    data = validate_success(api.liquidate_clearance_schedule(schedule["id"], MANAGER))

    assert data["liquidation_price_cents"] == 450, "round_half_up(min(500, 1300) * 0.90)"
    assert sum(data["liquidation_bucket_units"]) == 3


def test_stacked_markdown_applies_the_stage_discount_at_the_first_week(api):
    """PRD §3.8: "the running amount is multiplied by one minus that schedule's
    `markdown_pct` and the product is rounded half-up to a whole cent before the next
    schedule is applied"
    PRD §3.8: "the factor is 1.00 at week 0"

    Design: Corner/calculations/stacked_markdown_applies_the_week_factor_after_the_stage_discount
    """
    brand, loc = setup_store()
    day = open_store_day(loc["id"], "2026-09-21T00:00:00Z")
    item = _decor_2400()
    stock_item(loc["id"], day["id"], item["id"], 5)
    current = get_item(item["id"])
    schedule = create_clearance_schedule(loc["id"], item["id"], current["version"],
                                         start_date="2026-09-01T00:00:00Z",
                                         end_date="2026-10-01T00:00:00Z")

    validate_success(api.activate_clearance_schedule(schedule["id"], MANAGER))
    refreshed = get_item(item["id"])

    assert refreshed["effective_price_cents"] == 1800, "round_half_up(2400 * (1 - 0.25))"
    assert refreshed["current_markdown_pct"] == 0.25


def test_the_activation_snapshot_freezes_remaining_units_from_on_hand(api):
    """PRD §3.8: "activation stamps `activated_at` from the logical clock, freezes the schedule's
    `remaining_units` at the item's current `on_hand_units`"
    PRD §3.8: "`remaining_units` is its own record and is decremented only by the
    schedule's own liquidation event"

    Design: Corner/calculations/stacked_markdown_applies_the_week_factor_after_the_stage_discount
    """
    brand, loc = setup_store()
    day = open_store_day(loc["id"], "2026-09-21T00:00:00Z")
    item = _decor_2400()
    stock_item(loc["id"], day["id"], item["id"], 5)
    current = get_item(item["id"])
    schedule = create_clearance_schedule(loc["id"], item["id"], current["version"],
                                         start_date="2026-09-01T00:00:00Z",
                                         end_date="2026-10-01T00:00:00Z")

    data = validate_success(api.activate_clearance_schedule(schedule["id"], MANAGER))

    assert data["remaining_units"] == 5


# ==========================================================================
# Corner queue B — entities / state_machines
# ==========================================================================

def test_a_clearance_window_whose_end_precedes_its_start_is_malformed(api):
    """PRD §2.12: "A malformed request - a body that will not parse, a missing required
    field, a violated numeric bound ... - is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.8: "who supplies a `location_id`, an `item_id`, a `start_date`, an `end_date`
    that must be at or after the `start_date`"

    Design: Corner/entities/clearance_schedule_end_before_start_returns_invalid_request
    """
    brand, loc = setup_store()
    item = _decor_2400()
    cur = get_item(item["id"])
    payload = f.create_clearance_schedule_payload(loc["id"], item["id"], cur["version"],
                                                  start_date="2026-11-01T00:00:00Z",
                                                  end_date="2026-10-01T00:00:00Z")
    validate_error(api.create_clearance_schedule(payload, MANAGER),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


def test_activating_a_clearance_window_twice_is_refused(api):
    """PRD §3.8: "A schedule in `DRAFT` may be activated only when the logical clock's
    current instant falls within the window"
    PRD §2.12: "State-machine membership - whether the target resource is in a state from which
    the requested operation is defined - is priority 7 and reports `ERR_INVALID_STATE`
    (HTTP 409)"

    Design: Corner/state_machines/clearance_activate_twice_returns_invalid_state
    """
    brand, loc = setup_store()
    item = _decor_2400()
    stock_item(loc["id"], open_store_day(loc["id"], "2026-09-21T00:00:00Z")["id"], item["id"], 5)
    cur = get_item(item["id"])
    schedule = create_clearance_schedule(loc["id"], item["id"], cur["version"],
                                         start_date="2026-09-01T00:00:00Z",
                                         end_date="2026-10-01T00:00:00Z")
    validate_success(api.activate_clearance_schedule(schedule["id"], MANAGER))

    validate_error(api.activate_clearance_schedule(schedule["id"], MANAGER),
                   ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = get_clearance_schedule(schedule["id"])
    assert refreshed["stage"] == "S1"
    assert get_location(loc["id"])["active_clearance_count"] == 1


# ==========================================================================
# Corner queue B — validations
# ==========================================================================

def test_missing_end_date_on_a_clearance_create_is_malformed(api):
    """PRD §2.12: "A malformed request - a body that will not parse, a missing required
    field ... - is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.8: "The schedule opens in `DRAFT` status with `stage` of `S1`, `markdown_pct` of
    zero - note that a draft schedule carries no markdown at all despite sitting at `S1`"

    Design: Corner/validations/clearance_create_missing_end_date_returns_invalid_request_and_present_fields_succeed
    """
    brand, loc = setup_store()
    item = _decor_2400()
    cur = get_item(item["id"])
    payload = {"location_id": loc["id"], "item_id": item["id"],
               "start_date": "2026-09-25T00:00:00Z",
               "expected_item_version": cur["version"]}
    validate_error(api.create_clearance_schedule(payload, MANAGER),
                   ApiErrorId.ERR_INVALID_REQUEST.value)

    full = f.create_clearance_schedule_payload(loc["id"], item["id"], cur["version"],
                                               start_date="2026-09-25T00:00:00Z",
                                               end_date="2026-10-25T00:00:00Z")
    data = validate_success(api.create_clearance_schedule(full, MANAGER), 201)
    assert data["status"] == "DRAFT"
    assert data["markdown_pct"] == 0


def test_activation_beyond_the_store_slot_cap_is_refused(api):
    """PRD §3.8: "only when the location's `active_clearance_count` is still below the
    location's `clearance_max_active`"
    PRD §3.8: "A location already at its limit refuses the activation with
    `ERR_CLEARANCE_SLOT_LIMIT` (HTTP 409) at priority 14"

    Design: Corner/validations/clearance_activation_beyond_the_store_slot_cap_is_refused
    """
    # PRD 3.7 makes clearance_max_active a Location input (default 3), so the cap
    # belongs on the location; a brand payload cannot carry it.
    brand = api.create_brand(f.create_brand_payload(food_storage_corridor_units=310),
                             ADMIN).json()["data"]
    loc = api.create_location(
        f.create_location_payload(brand["id"], clearance_max_active=1), ADMIN).json()["data"]
    day = open_store_day(loc["id"], "2026-09-20T00:00:00Z")
    item_a, item_b = _decor_2400(), _decor_1300()
    stock_item(loc["id"], day["id"], item_a["id"], 4)
    stock_item(loc["id"], day["id"], item_b["id"], 4)
    cur_a, cur_b = get_item(item_a["id"]), get_item(item_b["id"])
    sched_a = create_clearance_schedule(loc["id"], item_a["id"], cur_a["version"],
                                        start_date="2026-09-01T00:00:00Z",
                                        end_date="2026-09-30T00:00:00Z")
    validate_success(api.activate_clearance_schedule(sched_a["id"], MANAGER))
    sched_b = create_clearance_schedule(loc["id"], item_b["id"], cur_b["version"],
                                        start_date="2026-09-15T00:00:00Z",
                                        end_date="2026-10-20T00:00:00Z")

    validate_error(api.activate_clearance_schedule(sched_b["id"], MANAGER),
                   ApiErrorId.ERR_CLEARANCE_SLOT_LIMIT.value)
    assert get_clearance_schedule(sched_b["id"])["status"] == "DRAFT"


def test_liquidating_before_the_final_stage_is_refused(api):
    """PRD §3.8: "A liquidation attempted before the final stage, or against an item that is not on
    clearance, is refused with `ERR_CLEARANCE_NOT_FINAL` (HTTP 409) at priority 15."
    PRD §3.8: "sets `stage` to `S1` and applies that stage's markdown percent of 0.25"

    Design: Corner/validations/liquidating_before_the_final_stage_returns_clearance_not_final
    """
    brand, loc = setup_store()
    day = open_store_day(loc["id"], "2026-09-21T00:00:00Z")
    item = _decor_2400()
    stock_item(loc["id"], day["id"], item["id"], 4)
    cur = get_item(item["id"])
    schedule = create_clearance_schedule(loc["id"], item["id"], cur["version"],
                                         start_date="2026-09-01T00:00:00Z",
                                         end_date="2026-10-01T00:00:00Z")
    activated = validate_success(api.activate_clearance_schedule(schedule["id"], MANAGER))
    assert activated["stage"] == "S1"

    validate_error(api.liquidate_clearance_schedule(schedule["id"], MANAGER),
                   ApiErrorId.ERR_CLEARANCE_NOT_FINAL.value)
    assert get_item(item["id"])["status"] == "CLEARANCE"


# ==========================================================================
# Corner queue B — endpoints / cross_cutting_layers
# ==========================================================================

def test_store_day_close_extends_a_clearance_window_below_the_trigger(api):
    """PRD §3.5: "If the closing day's freshly computed `retail_sales_per_guest_cents` is
    below the brand's `liquidation_trigger_rpg_cents`, then every `ClearanceSchedule` of
    that location currently in `ACTIVE` status is moved to `EXTENDED`, its
    `extension_count` is increased by one"
    PRD §3.8: "only those whose `end_date` lies before the logical clock's current instant"

    Design: Corner/endpoints/store_day_close_runs_the_clearance_extension_only_below_the_trigger
    """
    brand = api.create_brand(f.create_brand_payload(liquidation_trigger_rpg_cents=700,
                                                    food_storage_corridor_units=310), ADMIN).json()["data"]
    loc = api.create_location(f.create_location_payload(brand["id"]), ADMIN).json()["data"]
    item = _decor_2400()
    early_day = open_store_day(loc["id"], "2026-09-05T00:00:00Z")
    stock_item(loc["id"], early_day["id"], item["id"], 8)
    cur = get_item(item["id"])
    schedule = create_clearance_schedule(loc["id"], item["id"], cur["version"],
                                         start_date="2026-09-01T00:00:00Z",
                                         end_date="2026-09-10T00:00:00Z")
    validate_success(api.activate_clearance_schedule(schedule["id"], MANAGER))
    # Move the clock past the window's end so the automatic extension is eligible.
    validate_success(api.set_clock("2026-09-21T00:00:00Z", ADMIN))

    busy_day = open_store_day(loc["id"], "2026-09-21T00:00:00Z")
    settled_receipt(loc["id"], busy_day["id"],
                    [f.retail_line(item["id"], 1, 50000, 0.0, "RETAIL")], "R-1042-0081")
    current = get_store_day(busy_day["id"])
    closed = close_store_day(busy_day["id"], current["version"])

    assert closed["retail_sales_per_guest_cents"] < 700
    refreshed = get_clearance_schedule(schedule["id"])
    assert refreshed["status"] == "EXTENDED"
    assert refreshed["extension_count"] == 1


def test_a_cancelled_clearance_window_is_terminal_for_the_forward_path(api):
    """PRD §3.8: "A `BoutiqueManager` cancels a draft window, moving its status to
    `CANCELLED`"
    PRD §3.8: "`CANCELLED` is the schedule's second terminal state."
    PRD §2.12: "State-machine membership - whether the target resource is in a state from which
    the requested operation is defined - is priority 7 and reports `ERR_INVALID_STATE`
    (HTTP 409)"

    Design: Corner/cross_cutting_layers/credit_memo_is_immutable_once_posted_and_can_be_reversed
    """
    brand, loc = setup_store()
    item = _decor_2400()
    cur = get_item(item["id"])
    schedule = create_clearance_schedule(loc["id"], item["id"], cur["version"],
                                         start_date="2026-09-25T00:00:00Z",
                                         end_date="2026-10-25T00:00:00Z")
    cancelled = validate_success(api.cancel_clearance_schedule(schedule["id"], MANAGER))
    assert cancelled["status"] == "CANCELLED"

    validate_error(api.cancel_clearance_schedule(schedule["id"], MANAGER),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_activating_a_cancelled_clearance_window_is_refused(api):
    """PRD §3.8: "`CANCELLED` is the schedule's second terminal state."
    PRD §3.8: "A `BoutiqueManager` cancels a draft window, moving its status to `CANCELLED` and
    leaving the item's `current_markdown_pct` untouched"

    Design: Corner/cross_cutting_layers/credit_memo_is_immutable_once_posted_and_can_be_reversed
    """
    brand, loc = setup_store()
    item = _decor_2400()
    cur = get_item(item["id"])
    schedule = create_clearance_schedule(loc["id"], item["id"], cur["version"],
                                         start_date="2026-09-01T00:00:00Z",
                                         end_date="2026-10-25T00:00:00Z")
    validate_success(api.cancel_clearance_schedule(schedule["id"], MANAGER))

    validate_error(api.activate_clearance_schedule(schedule["id"], MANAGER),
                   ApiErrorId.ERR_INVALID_STATE.value)