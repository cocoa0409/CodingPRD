"""Corner queue (state_machines): initial states, invalid/valid transitions,
terminal lockdown, closure cascades, FAIL compensation, and month rollover."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    cancel_order,
    charge_melt,
    confirm_allocation,
    create_allocation,
    create_order,
    create_permit,
    create_product,
    disposition_report,
    get_allocation,
    get_inventory_record,
    get_inventory_record_for_product,
    get_melt,
    get_mold,
    get_order,
    get_permit,
    get_success_data,
    get_unit,
    inspect_unit_defect,
    inspect_unit_pass,
    qa_release,
    record_reading,
    scrap_unit_via_defect,
    setup_charging_melt,
    setup_released_order,
    setup_seasoning_batch_ctx,
    setup_shaken_units,
    setup_inventory_with_stock,
    ship_allocation,
    start_bake,
    validate_error,
)

_FM = TEST_USERS["foundry_manager_headers"]
_OP = TEST_USERS["melt_operator_headers"]
_QI = TEST_USERS["quality_inspector_headers"]


def test_production_order_initial_state_planned(api):
    """PRD §3.2: "The new order starts in state `PLANNED` with `posture` `OPEN`,
    `scrap_tier` `GREEN`, and all counters at zero: `poured_units`, `good_units`,
    `scrapped_units`, `defect_scrapped_units`, and `scrap_weighted_units` are 0,
    `scrap_index` is 0, and `labor_hours_actual`, `energy_kwh_actual`, and
    `unit_cost_final_cents` remain null until completion, while `margin_flag` reads
    false until it is computed at completion."
    With no material charged, the provisional cost is 0 / planned + 1450 == 1450.

    Design: Corner/state_machines/production_order_initial_state_planned
    """
    product = create_product()
    order = create_order(product["id"], planned_quantity=10)
    assert order["state"] == "PLANNED"
    assert order["posture"] == "OPEN"
    assert order["scrap_tier"] == "GREEN"
    for field in ("poured_units", "good_units", "scrapped_units",
                  "defect_scrapped_units"):
        assert order[field] == 0
    assert order["scrap_weighted_units"] == pytest.approx(0, abs=1e-9)
    assert order["scrap_index"] == pytest.approx(0, abs=1e-9)
    assert order["unit_cost_provisional_cents"] == 1450
    assert order["unit_cost_final_cents"] is None
    assert order["margin_flag"] is False
    assert order["version"] == 1


def test_double_release_rejected(api):
    """PRD §3.2: "Releasing the order moves it from `PLANNED` to `MOLDING`; the
    gate requires the order to still be `PLANNED` and the product still `ACTIVE`"
    PRD §2.9: "sixth, state-transition legality, including terminal-state lockdown
    and repeated triggers (`ERR_INVALID_STATE_TRANSITION`)"
    The second release is rejected and the version stays at 2.

    Design: Corner/state_machines/double_release_rejected
    """
    ctx = setup_released_order()
    order_id = ctx["order"]["id"]
    resp = api.release_production_order(order_id, _FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    order = get_order(order_id)
    assert order["state"] == "MOLDING"
    assert order["version"] == 2


def test_tap_from_melting_rejected(api):
    """PRD §3.3: "Tapping moves a `CERTIFIED` batch to `TAPPED` and initializes the
    iron mass ledger."
    A batch still in MELTING (no chemistry recorded) cannot tap; it stays MELTING
    with tapped_lbs null.

    Design: Corner/state_machines/tap_from_melting_rejected
    """
    ctx = setup_charging_melt()
    batch_id = ctx["melt"]["id"]
    charge_melt(batch_id)
    resp = api.tap_melt_batch(batch_id, {"tapped_temp_f": 2690, "tapped_lbs": 2010},
                              _OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    melt = get_melt(batch_id)
    assert melt["state"] == "MELTING"
    assert melt["tapped_lbs"] is None


def test_disposition_on_dispositioned_report_rejected(api):
    """PRD §3.5: "A `QualityInspector` dispositions the report belonging to the
    unit — the report whose `casting_unit_id` equals that unit's `id` and whose
    `status` is still `OPEN`"
    The repeat disposition on the closed report is rejected and the order's scrap
    counters do not double-count.

    Design: Corner/state_machines/disposition_on_dispositioned_report_rejected
    """
    ctx = setup_shaken_units(num_units=3, order_overrides={"planned_quantity": 30})
    unit_id = ctx["unit_ids"][0]
    _, report_id = inspect_unit_defect(unit_id, defect_type="POROSITY",
                                       severity="MINOR")
    disposition_report(report_id, "SCRAP")
    resp = api.disposition_defect_report(report_id, {"disposition": "REWORK"}, _QI)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    reports = get_success_data(api.list_unit_defect_reports(unit_id, _QI))
    report = next(r for r in reports if r["id"] == report_id)
    assert report["status"] == "DISPOSITIONED"
    assert report["disposition"] == "SCRAP"
    order = get_order(ctx["order"]["id"])
    assert order["defect_scrapped_units"] == 1
    assert order["scrap_weighted_units"] == pytest.approx(1.0, abs=1e-9)
    assert get_unit(unit_id)["state"] == "SCRAPPED"


def test_inspect_scrapped_unit_terminal_lockdown(api):
    """PRD §3.5: "`SEASONED` and `SCRAPPED` are the unit's terminal states."
    Inspecting a SCRAPPED unit is rejected and its stored measurements do not
    change.

    Design: Corner/state_machines/inspect_scrapped_unit_terminal_lockdown
    """
    ctx = setup_shaken_units(num_units=2, order_overrides={"planned_quantity": 30})
    unit_id = ctx["unit_ids"][0]
    scrap_unit_via_defect(unit_id, defect_type="CRACK", severity="CRITICAL")
    resp = api.inspect_casting_unit(
        unit_id,
        {"outcome": "PASS", "measured_weight_oz": 128.0,
         "measured_diameter_in": 10.25, "measured_wall_thickness_in": 0.19},
        _QI)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    unit = get_unit(unit_id)
    assert unit["state"] == "SCRAPPED"
    assert unit["measured_weight_oz"] == pytest.approx(128.0, abs=1e-9)


def test_allocation_lifecycle_confirm_ship_and_terminal_lockdown(api):
    """PRD §3.8: "Shipping moves a `CONFIRMED` allocation to `SHIPPED` and settles
    the reservation into a physical movement: the record's `on_hand_units`
    decreases by `allocated_qty`, `reserved_units` decreases by `allocated_qty`,
    `shipped_units` increases by `allocated_qty`, and the inventory record's
    `version` increments by 1."
    PRD §3.8: "A confirmed allocation stamps `confirmed_at` with the logical clock."
    Ship from PROPOSED and cancel from SHIPPED are both invalid transitions.
    (The confirmed_at date-time portion is the pinned logical clock start; the
    fractional-second rendering is implementation detail and only prefix-checked.)

    Design: Corner/state_machines/allocation_lifecycle_confirm_ship_and_terminal_lockdown
    """
    ctx = setup_inventory_with_stock(num_units=3)
    record_id = ctx["inventory_record"]["id"]
    allocation = create_allocation(record_id, allocated_qty=3,
                                   ship_week="2026-11-16")
    early = api.ship_retail_allocation(allocation["id"],
                                       TEST_USERS["retail_planner_headers"])
    validate_error(early, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    allocation = confirm_allocation(allocation["id"])
    assert allocation["status"] == "CONFIRMED"
    assert allocation["confirmed_at"].startswith("2026-09-01T00:00:00")
    ship_allocation(allocation["id"])
    assert get_allocation(allocation["id"])["status"] == "SHIPPED"
    record = get_inventory_record(record_id)
    assert record["on_hand_units"] == 0
    assert record["reserved_units"] == 0
    assert record["shipped_units"] == 3
    late = api.cancel_retail_allocation(allocation["id"],
                                        TEST_USERS["retail_planner_headers"])
    validate_error(late, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_order_cancel_cascades_units_melts_seasoning(api):
    """PRD §3.2: "The cascade itself scraps every casting unit still in a
    non-terminal state with `scrap_reason` `ORDER_CANCEL` and increments
    `scrapped_units` by 1 per unit, deliberately leaving `scrap_weighted_units` and
    `scrap_index` unchanged because the scrap is not defect-driven"
    PRD §3.2: "Every melt batch of the order in `CHARGING`, `MELTING`,
    `CHEMISTRY_CHECK`, `ADJUSTMENT`, `CERTIFIED`, or `HELD` is moved to
    `CANCELLED`."
    The TAPPED melt and the SHAKEOUT_DONE mold are outside the cascade sets and
    survive unchanged (only PREPARED molds cancel, per PRD §3.2).

    Design: Corner/state_machines/order_cancel_cascades_units_melts_seasoning
    """
    ctx = setup_shaken_units(num_units=3)
    order_id = ctx["order"]["id"]
    inspect_unit_pass(ctx["unit_ids"][0])
    cancel_order(order_id)
    order = get_order(order_id)
    assert order["state"] == "CANCELLED"
    for unit_id in ctx["unit_ids"]:
        unit = get_unit(unit_id)
        assert unit["state"] == "SCRAPPED"
        assert unit["scrap_reason"] == "ORDER_CANCEL"
    assert order["scrapped_units"] == 3
    assert order["defect_scrapped_units"] == 0
    assert order["scrap_weighted_units"] == pytest.approx(0, abs=1e-9)
    assert order["scrap_index"] == pytest.approx(0, abs=1e-9)
    assert get_melt(ctx["melt"]["id"])["state"] == "TAPPED"
    assert get_mold(order_id, ctx["mold"]["id"])["state"] == "SHAKEOUT_DONE"


def test_seasoning_batch_fail_returns_units_to_finished(api):
    """PRD §3.6: "A `decision` of `FAIL` moves the batch from `BAKING` to
    `FAILED`, still computes and stores the `cure_score`, sets `released_by`,
    returns every unit from `SEASONING_QUEUED` to `FINISHED` with its
    `seasoning_batch_id` cleared, and changes no inventory."

    Design: Corner/state_machines/seasoning_batch_fail_returns_units_to_finished
    """
    ctx = setup_seasoning_batch_ctx(
        num_units=2, order_overrides={"planned_quantity": 5},
        seasoning_overrides={"oil_type": "CANOLA"})
    batch = start_bake(ctx["seasoning_batch"]["id"], actual_bake_temp_f=450)
    batch = qa_release(batch["id"], bake_duration_min=75,
                       food_safety_verified=True, decision="FAIL")
    assert batch["state"] == "FAILED"
    assert batch["released_by"] == "qi-1"
    for unit_id in ctx["unit_ids"]:
        unit = get_unit(unit_id)
        assert unit["state"] == "FINISHED"
        assert unit["seasoning_batch_id"] is None
    assert get_order(ctx["order"]["id"])["good_units"] == 0
    record = get_inventory_record_for_product(ctx["product"]["id"])
    assert record["on_hand_units"] == 0


def test_clock_month_rollover_clears_warning(api):
    """PRD §2.4: "Advancing the clock across a calendar-month boundary triggers
    period-rollover processing: every permit's
    `over_limit_reading_count_current_period` resets to 0, a permit sitting in
    `WARNING` returns to `ACTIVE`, and the sand-reclamation month-to-date sums
    reset so that `current_sand_rate` becomes null until the next reclamation entry
    of the new month."
    A fresh over-limit reading in October raises WARNING again (count 1), proving
    the September count did not carry over.

    Design: Corner/state_machines/clock_month_rollover_clears_warning
    """
    permit = create_permit("AIR_EMISSIONS", limit_value=100.0)
    record_reading(permit["id"], 120.0)
    assert get_permit(permit["id"])["status"] == "WARNING"
    advance_clock("2026-10-01T00:00:00Z")
    permit = get_permit(permit["id"])
    assert permit["status"] == "ACTIVE"
    assert permit["over_limit_reading_count_current_period"] == 0
    record_reading(permit["id"], 125.0, source="SHAKEOUT_LINE")
    permit = get_permit(permit["id"])
    assert permit["status"] == "WARNING"
    assert permit["over_limit_reading_count_current_period"] == 1
