"""Executing the bake: the two status dimensions, labor settlement and cascades."""

from test_helpers import (
    BAKER,
    BAKER_ONE_USER_ID,
    api_client,
    assert_cents,
    assert_instant,
    assert_minutes,
    assert_null,
    assert_production_run,
    assert_ratio,
    attest_waste,
    complete_run,
    complete_run_payload,
    create_scratch_milk_product_payload,
    create_thaw_box_product_payload,
    drive_run_to_baking,
    drive_run_to_completed,
    list_ingredient_orders_for_department,
    list_runs_for_day,
    provision_product,
    read_bake_day,
    read_department,
    read_ingredient,
    read_run,
    recipe_line,
    schedule_par_baked_run,
    schedule_run,
    schedule_scratch_run,
    set_clock,
    set_oven_status,
    setup_planned_day,
    validate_error,
    validate_success,
)

BAKE_DAY_MORNING = "2026-08-12T04:00:00Z"


def _provision_milk_bread(setup):
    """A scratch milk bread carrying WHEAT and MILK, 20 flour units a rack."""
    return provision_product(
        create_scratch_milk_product_payload(
            setup["department"]["id"],
            recipe_lines=[recipe_line(setup["flour"]["id"], 20)],
        )
    )


def test_final_labor_charges_an_allergen_changeover_the_planned_figure_ignores():
    """The settled figure adds half the oven's buffer over a profile change.

    PRD §3.5: "When a predecessor exists and the set of `allergen_tags` on its
    product differs from the set on this run's product, an allergen changeover has
    occurred and a changeover allowance of the oven's `changeover_buffer_minutes`
    multiplied by one half, rounded half up to two decimal places, is granted".
    A WHEAT croissant batch precedes a WHEAT-and-MILK batch on the same deck, so
    the second settles at 68.00 + 10.00 = 78.00 against 68.00 planned.

    Design: Difficulty/dual_variant_calc/run_labor_planned_vs_actual_diverges_on_allergen_changeover
    """
    setup = setup_planned_day()
    milk_bread = _provision_milk_bread(setup)

    predecessor = schedule_par_baked_run(
        setup, rack_count=2, deck_index=0, bake_start_utc="2026-08-12T05:00:00Z"
    )
    settled_predecessor = drive_run_to_completed(predecessor, "PAR_BAKED", 80)
    assert_minutes(
        settled_predecessor["planned_labor_minutes"], 27.00, "predecessor planned labor"
    )
    assert_minutes(
        settled_predecessor["final_labor_minutes"],
        27.00,
        "a run with no predecessor earns no allowance",
    )

    successor = schedule_run(
        setup["bake_day"],
        milk_bread["id"],
        rack_count=4,
        oven_id=setup["oven"]["id"],
        deck_index=0,
        proof_start_utc="2026-08-12T05:15:00Z",
        bake_start_utc="2026-08-12T06:00:00Z",
    )
    assert_minutes(successor["planned_labor_minutes"], 68.00, "planned_labor_minutes")
    assert_cents(successor["ingredient_cost_cents"], 800, "ingredient_cost_cents")

    settled_successor = drive_run_to_completed(successor, "SCRATCH", 80)
    assert_minutes(
        settled_successor["planned_labor_minutes"],
        68.00,
        "the planned figure is fixed at creation and never revised",
    )
    assert_minutes(
        settled_successor["final_labor_minutes"], 78.00, "final_labor_minutes"
    )
    assert_cents(settled_successor["unit_cost_basis_cents"], 10, "unit_cost_basis_cents")

    day = read_bake_day(setup["bake_day"]["id"])
    assert_minutes(day["planned_labor_minutes"], 95.00, "day planned_labor_minutes")
    assert_minutes(day["actual_labor_minutes"], 105.00, "day actual_labor_minutes")


def test_final_labor_grants_no_allowance_when_the_deck_keeps_one_profile():
    """A predecessor with the same allergen set means the raw figure settles as is.

    PRD §3.5: "The raw figure is the `actual_labor_minutes` the baker supplied,
    or, when that field was left out entirely, the run's own
    `planned_labor_minutes`."  Two croissant batches share the WHEAT profile, so
    the second settles at exactly the 30.00 raw minutes the baker reported.

    Design: Difficulty/dual_variant_calc/run_labor_planned_vs_actual_diverges_on_allergen_changeover
    """
    setup = setup_planned_day()
    first = schedule_par_baked_run(
        setup, rack_count=2, deck_index=0, bake_start_utc="2026-08-12T05:00:00Z"
    )
    settled_first = drive_run_to_completed(first, "PAR_BAKED", 80)
    assert_minutes(settled_first["final_labor_minutes"], 27.00, "final_labor_minutes")

    second = schedule_par_baked_run(
        setup, rack_count=2, deck_index=0, bake_start_utc="2026-08-12T05:40:00Z"
    )
    settled_second = drive_run_to_completed(
        second, "PAR_BAKED", 80, actual_labor_minutes=30.00
    )
    assert_minutes(
        settled_second["planned_labor_minutes"], 27.00, "planned_labor_minutes"
    )
    assert_minutes(
        settled_second["final_labor_minutes"],
        30.00,
        "same-profile predecessors grant a 0.00 changeover allowance",
    )

    day = read_bake_day(setup["bake_day"]["id"])
    assert_minutes(day["planned_labor_minutes"], 54.00, "day planned_labor_minutes")
    assert_minutes(day["actual_labor_minutes"], 57.00, "day actual_labor_minutes")
    assert day["produced_units_total"] == 160
    assert_cents(day["production_cost_cents"], 1200, "production_cost_cents")


def test_the_disposition_dimension_stays_pending_for_the_whole_execution():
    """Execution walks SCHEDULED to COMPLETED while merchandising waits.

    PRD §3.6: "It starts at `PENDING` and stays there for the whole of the run's
    execution. Completion moves it: a batch that yielded at least one unit goes
    `PENDING → ON_SHELF` with `on_shelf_units` set to `actual_units`".

    Design: Difficulty/non_linear_state_machine/production_run_execution_and_disposition_dimensions_move_independently
    """
    setup = setup_planned_day(clock=BAKE_DAY_MORNING)
    run = schedule_par_baked_run(
        setup, rack_count=2, deck_index=0, bake_start_utc=BAKE_DAY_MORNING
    )
    assert run["execution_status"] == "SCHEDULED"
    assert run["disposition_status"] == "PENDING"

    baking = validate_success(api_client.start_bake(run["id"], BAKER), 200)
    assert baking["execution_status"] == "BAKING"
    assert baking["disposition_status"] == "PENDING"
    assert baking["version"] == 2

    completed = complete_run(baking, 80)
    assert_production_run(completed)
    assert completed["execution_status"] == "COMPLETED"
    assert completed["disposition_status"] == "ON_SHELF"
    assert completed["actual_units"] == 80
    assert completed["on_shelf_units"] == 80
    assert completed["wasted_units_total"] == 0
    assert_cents(completed["unit_cost_basis_cents"], 8, "unit_cost_basis_cents")
    assert completed["executed_by_user_id"] == BAKER_ONE_USER_ID
    assert_instant(completed["expires_utc"], "2026-08-12T14:35:00Z", "expires_utc")
    assert_null(completed["markdown_unit_price_cents"], "markdown_unit_price_cents")


def test_markdown_and_waste_move_only_the_disposition_dimension():
    """Merchandising keeps moving after execution has reached its terminal state.

    PRD §3.5: "A run carries two status dimensions that move independently on the
    same row."  A discount then a full write-off drive the disposition through
    `MARKED_DOWN` to `CLEARED` while `execution_status` stays `COMPLETED`, and the
    discounted price is deliberately retained.

    Design: Difficulty/non_linear_state_machine/production_run_execution_and_disposition_dimensions_move_independently
    """
    setup = setup_planned_day(clock=BAKE_DAY_MORNING)
    run = schedule_par_baked_run(
        setup, rack_count=2, deck_index=0, bake_start_utc=BAKE_DAY_MORNING
    )
    completed = drive_run_to_completed(run, "PAR_BAKED", 80)
    assert_instant(completed["expires_utc"], "2026-08-12T14:35:00Z", "expires_utc")

    set_clock("2026-08-12T11:00:00Z")
    marked = validate_success(
        api_client.markdown_run(run["id"], setup["manager"]), 200
    )
    assert marked["disposition_status"] == "MARKED_DOWN"
    assert marked["execution_status"] == "COMPLETED"
    assert_cents(marked["markdown_unit_price_cents"], 75, "markdown_unit_price_cents")
    assert marked["on_shelf_units"] == 80

    record = attest_waste(run["id"], 80, disposition_reason="DONATED")
    assert_cents(record["unit_cost_basis_cents"], 8, "snapshotted unit cost basis")
    assert_cents(record["waste_cost_cents"], 640, "waste_cost_cents")

    cleared = read_run(run["id"])
    assert cleared["disposition_status"] == "CLEARED"
    assert cleared["execution_status"] == "COMPLETED"
    assert cleared["on_shelf_units"] == 0
    assert cleared["wasted_units_total"] == 80
    assert_cents(
        cleared["markdown_unit_price_cents"],
        75,
        "a cleared batch retains its discounted price",
    )

    day = read_bake_day(setup["bake_day"]["id"])
    assert day["waste_units_total"] == 80
    assert_cents(day["shrink_cost_cents"], 640, "shrink_cost_cents")
    assert_ratio(day["shrink_cost_basis_pct"], 1.0667, "shrink_cost_basis_pct")
    assert_ratio(day["shrink_unit_basis_pct"], 1.0000, "shrink_unit_basis_pct")
    assert day["markdown_authorization"] == "MANAGER_ONLY"


def test_a_run_cannot_be_loaded_while_its_oven_is_in_maintenance():
    """Cross-entity oven state is re-checked at the moment the deck is loaded.

    PRD §3.5: "both require the oven to still be `AVAILABLE`, failing with
    `ERR_OVEN_UNAVAILABLE` if maintenance has intervened since the run was
    scheduled — this is the moment at which a run left standing by an oven going
    out of service is finally stopped."

    Design: Difficulty/cross_entity_state_dependency/run_cannot_start_bake_while_its_oven_is_in_maintenance
    """
    setup = setup_planned_day()
    run = schedule_par_baked_run(setup, rack_count=2, deck_index=0)

    under_service = set_oven_status(
        setup["oven"]["id"], setup["department"], "MAINTENANCE", "burner service"
    )
    assert under_service["oven_status"] == "MAINTENANCE"
    assert under_service["status_reason"] == "burner service"

    blocked = api_client.start_bake(run["id"], BAKER)
    validate_error(blocked, "ERR_OVEN_UNAVAILABLE", 409)

    untouched = read_run(run["id"])
    assert untouched["execution_status"] == "SCHEDULED"
    assert untouched["version"] == 1, "A refused load must not mutate the run"


def test_returning_the_oven_to_available_lets_the_waiting_run_load():
    """The block lifts the moment the oven is back in service.

    PRD §3.1: "Moving `MAINTENANCE → AVAILABLE` has no preconditions at all: the
    note is stored and the oven re-enters the planner's candidate pool."  The note
    itself "defaults to null and simply records the note attached to the most recent
    change", so an unexplained return to service reads back null, and the same run
    that was refused with `ERR_OVEN_UNAVAILABLE` mid-maintenance loads normally
    afterwards.

    Design: Difficulty/cross_entity_state_dependency/run_cannot_start_bake_while_its_oven_is_in_maintenance
    """
    setup = setup_planned_day()
    run = schedule_par_baked_run(setup, rack_count=2, deck_index=0)
    set_oven_status(
        setup["oven"]["id"], setup["department"], "MAINTENANCE", "burner service"
    )
    validate_error(api_client.start_bake(run["id"], BAKER), "ERR_OVEN_UNAVAILABLE", 409)

    back_in_service = set_oven_status(
        setup["oven"]["id"], setup["department"], "AVAILABLE"
    )
    assert back_in_service["oven_status"] == "AVAILABLE"
    assert_null(back_in_service["status_reason"], "status_reason")

    baking = validate_success(api_client.start_bake(run["id"], BAKER), 200)
    assert baking["execution_status"] == "BAKING"
    assert baking["version"] == 2


def test_runs_refuse_execution_triggers_not_declared_from_their_current_status():
    """Each trigger is declared against the product's method and the run's state.

    PRD §3.5: "asking for it on a `PAR_BAKED` or `THAW_AND_SERVE` product, or on
    any product whose `proof_minutes` is zero, is rejected with
    `ERR_PROOF_NOT_REQUIRED`", "Attempting to load a `SCRATCH` run that is still
    in `SCHEDULED` is rejected with `ERR_PROOF_REQUIRED`, because the proof stage
    may not be skipped", and per §3.5 completion of "a `SCRATCH` or `PAR_BAKED`
    run still sitting in `SCHEDULED` is rejected with `ERR_INVALID_RUN_STATE`".

    Design: Corner/state_machines/runs_refuse_execution_triggers_not_declared_from_their_current_status
    """
    setup = setup_planned_day()
    par_baked = schedule_par_baked_run(
        setup, rack_count=2, deck_index=0, bake_start_utc=BAKE_DAY_MORNING
    )
    scratch = schedule_scratch_run(setup, rack_count=4, deck_index=1)

    validate_error(
        api_client.start_proof(par_baked["id"], BAKER), "ERR_PROOF_NOT_REQUIRED", 409
    )
    validate_error(
        api_client.start_bake(scratch["id"], BAKER), "ERR_PROOF_REQUIRED", 409
    )
    validate_error(
        api_client.complete_run(par_baked["id"], complete_run_payload(80), BAKER),
        "ERR_INVALID_RUN_STATE",
        409,
    )

    for run in (par_baked, scratch):
        unchanged = read_run(run["id"])
        assert unchanged["execution_status"] == "SCHEDULED"
        assert unchanged["disposition_status"] == "PENDING"
        assert unchanged["version"] == 1
        assert_null(unchanged["actual_units"], "actual_units")


def test_a_zero_yield_completion_clears_the_disposition_but_still_consumes_flour():
    """A failed batch books its labor and its flour and reaches CLEARED at once.

    PRD §3.6: "while a zero-yield batch goes straight `PENDING → CLEARED` with
    `on_shelf_units` set to 0 and `unit_cost_basis_cents` set to 0."  The
    consumption hop still fires, so the two racks of croissant still draw 60 units
    of flour out of stock.

    Design: Corner/state_machines/a_zero_yield_completion_clears_the_disposition_but_still_consumes_flour
    """
    setup = setup_planned_day()
    run = schedule_par_baked_run(setup, rack_count=2, deck_index=0)
    completed = drive_run_to_completed(run, "PAR_BAKED", 0)

    assert completed["execution_status"] == "COMPLETED"
    assert completed["disposition_status"] == "CLEARED"
    assert completed["actual_units"] == 0
    assert completed["on_shelf_units"] == 0
    assert completed["wasted_units_total"] == 0
    assert_cents(completed["unit_cost_basis_cents"], 0, "unit_cost_basis_cents")
    assert_minutes(completed["final_labor_minutes"], 27.00, "final_labor_minutes")
    assert completed["executed_by_user_id"] == BAKER_ONE_USER_ID

    day = read_bake_day(setup["bake_day"]["id"])
    assert day["produced_units_total"] == 0
    assert_cents(day["production_cost_cents"], 600, "production_cost_cents")
    assert_minutes(day["actual_labor_minutes"], 27.00, "actual_labor_minutes")
    assert_ratio(day["shrink_cost_basis_pct"], 0.0000, "shrink_cost_basis_pct")
    assert_ratio(day["shrink_unit_basis_pct"], 0.0000, "shrink_unit_basis_pct")
    assert day["markdown_authorization"] == "AUTO"

    flour = read_ingredient(setup["flour"]["id"])
    assert flour["on_hand_units"] == 1940, "2 racks at 30 flour units a rack"
    assert flour["replenishment_state"] == "OK"


def test_thaw_and_serve_labor_applies_the_quarter_method_factor():
    """The lightest method factor still rounds to two decimal places.

    PRD §3.4: "The figure is the product's `setup_labor_minutes` plus the
    `rack_count` multiplied by the product's `base_labor_minutes_per_rack`
    multiplied by the method labor factor for the product's `production_method`,
    with the result rounded half up to two decimal places."  Three racks of a
    thaw-and-serve box therefore cost 12 + 3 * 8 * 0.25 = 18.00 minutes.

    Design: Corner/calculations/thaw_and_serve_labor_applies_the_quarter_method_factor_to_two_decimals
    """
    setup = setup_planned_day()
    boxed = provision_product(
        create_thaw_box_product_payload(setup["department"]["id"])
    )

    run = schedule_run(setup["bake_day"], boxed["id"], rack_count=3)
    assert_minutes(run["planned_labor_minutes"], 18.00, "planned_labor_minutes")
    assert run["planned_units"] == 18
    assert_null(run["oven_id"], "oven_id")
    assert_null(run["bake_end_utc"], "bake_end_utc")
    assert_instant(run["ready_utc"], setup["clock"], "ready_utc")
    assert_instant(run["expires_utc"], "2026-08-11T04:00:00Z", "expires_utc")

    completed = complete_run(run, 18)
    assert completed["execution_status"] == "COMPLETED"
    assert completed["disposition_status"] == "ON_SHELF"
    assert_minutes(completed["final_labor_minutes"], 18.00, "final_labor_minutes")

    day = read_bake_day(setup["bake_day"]["id"])
    assert_minutes(day["planned_labor_minutes"], 18.00, "day planned_labor_minutes")
    assert_minutes(day["actual_labor_minutes"], 18.00, "day actual_labor_minutes")


def test_rollups_count_planned_figures_for_live_runs_and_actuals_for_completed():
    """Planned rollups follow creation; actual rollups follow completion.

    PRD §3.5: "First, the owning bake day absorbs the run: its
    `produced_units_total`, `actual_labor_minutes` and `production_cost_cents` all
    take this run in."  A batch still sitting in `SCHEDULED` contributes its
    planned labor and units but nothing to the actual figures.

    Design: Corner/calculations/rollups_count_planned_figures_for_all_live_runs_but_actuals_only_for_completed
    """
    setup = setup_planned_day()
    to_complete = schedule_par_baked_run(
        setup, rack_count=2, deck_index=0, bake_start_utc=BAKE_DAY_MORNING
    )
    schedule_par_baked_run(
        setup, rack_count=2, deck_index=1, bake_start_utc=BAKE_DAY_MORNING
    )
    drive_run_to_completed(to_complete, "PAR_BAKED", 80)

    day = read_bake_day(setup["bake_day"]["id"])
    assert_minutes(day["planned_labor_minutes"], 54.00, "planned_labor_minutes")
    assert day["planned_units_total"] == 161
    assert_minutes(day["actual_labor_minutes"], 27.00, "actual_labor_minutes")
    assert day["produced_units_total"] == 80
    assert_cents(
        day["production_cost_cents"],
        600,
        "only the completed batch books its ingredient cost",
    )

    rows, meta = list_runs_for_day(setup["bake_day"]["id"], execution_status="SCHEDULED")
    assert meta["total_count"] == 2
    for row in rows:
        assert_null(row["actual_units"], "a live run has no actual units")


def test_run_completion_effects_are_visible_in_the_same_response_and_next_read():
    """Every hop of the cascade is already settled in the completion response.

    PRD §3.5: "On the run itself, completion stores `actual_units`, stamps
    `executed_by_user_id` from the caller's `X-User-ID`, settles
    `final_labor_minutes`, computes `unit_cost_basis_cents`, sets
    `wasted_units_total` to 0 and sets `on_shelf_units` to `actual_units`."  The
    four outward hops — day rollups, recipe consumption, replenishment and the
    department's commitment — are equally settled by the time the call returns, so
    a later read of each touched row agrees with it.

    Design: Corner/consistency_model/run_completion_effects_are_visible_in_the_same_response_and_next_read
    """
    setup = setup_planned_day(flour_on_hand=100)
    run = schedule_par_baked_run(setup, rack_count=2, deck_index=0)
    # PRD §3.5: a PAR_BAKED run goes straight from SCHEDULED into BAKING, and a
    # PAR_BAKED run still sitting in SCHEDULED may not be completed.
    baking = drive_run_to_baking(run, "PAR_BAKED")
    assert baking["execution_status"] == "BAKING"
    assert baking["version"] == 2

    completed = validate_success(
        api_client.complete_run(run["id"], complete_run_payload(80), BAKER), 200
    )
    assert completed["execution_status"] == "COMPLETED"
    assert completed["disposition_status"] == "ON_SHELF"
    assert completed["actual_units"] == 80
    assert completed["on_shelf_units"] == 80
    assert_minutes(completed["final_labor_minutes"], 27.00, "final_labor_minutes")
    assert_cents(completed["unit_cost_basis_cents"], 8, "unit_cost_basis_cents")
    assert completed["version"] == 3

    day = read_bake_day(setup["bake_day"]["id"])
    assert_minutes(day["actual_labor_minutes"], 27.00, "actual_labor_minutes")
    assert_cents(day["production_cost_cents"], 600, "production_cost_cents")
    assert day["produced_units_total"] == 80
    assert day["planned_units_total"] == 81

    flour = read_ingredient(setup["flour"]["id"])
    assert flour["on_hand_units"] == 40
    assert flour["replenishment_state"] == "REORDER_DUE"

    drafts, meta = list_ingredient_orders_for_department(
        setup["department"]["id"], origin="AUTO_REORDER"
    )
    assert meta["total_count"] == 1, "One automatic order is created per completion"
    draft = drafts[0]
    assert draft["order_status"] == "DRAFT"
    assert_null(draft["target_bake_day_id"], "target_bake_day_id")
    assert len(draft["lines"]) == 1
    line = draft["lines"][0]
    assert line["ingredient_id"] == setup["flour"]["id"]
    assert line["required_units"] == 200, "twice the 120-unit reorder point less 40 on hand"
    assert line["cases"] == 5
    assert line["ordered_units"] == 225
    assert_cents(line["line_cost_cents"], 2363, "line_cost_cents")
    assert_cents(draft["order_total_cents"], 2363, "order_total_cents")

    department = read_department(setup["department"]["id"])
    assert_cents(
        department["open_purchase_commitment_cents"],
        2363,
        "open_purchase_commitment_cents",
    )
