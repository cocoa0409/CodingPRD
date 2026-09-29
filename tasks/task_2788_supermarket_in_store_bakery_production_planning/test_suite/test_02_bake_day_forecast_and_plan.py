"""Forecast entry and production plan generation on a bake day."""

from test_helpers import (
    BAKER,
    REGIONAL_ADMIN,
    add_forecast_line,
    api_client,
    assert_bake_day,
    assert_instant,
    assert_minutes,
    assert_null,
    assert_production_run,
    find_forecast_line,
    forecast_line_payload,
    generate_plan_payload,
    get_success_data,
    list_runs_for_day,
    open_bake_day,
    read_bake_day,
    run_plan_generation,
    schedule_par_baked_run,
    setup_draft_day,
    setup_planned_day,
    setup_reference_data,
    validate_error,
    validate_success,
)


def _run_for_product(rows, product_id):
    matches = [row for row in rows if row["product_id"] == product_id]
    assert len(matches) == 1, (
        f"Expected exactly one run for product {product_id}, got {len(matches)}"
    )
    return matches[0]


def _setup_waterfall_day():
    """A Wednesday day whose forecast outruns both labor and the oven decks.

    The department's oven has two decks of four racks each and the day carries a
    120-minute labor budget.  The croissant line asks for 60 units (two racks at
    40 a rack) and the dinner-roll line asks for 280 (twelve racks at 25 a rack).
    """
    setup = setup_reference_data()
    day = open_bake_day(setup["department"], labor_budget_minutes=120)
    day = add_forecast_line(
        day, setup["department"], setup["croissant"]["id"], "MORNING", 60
    )
    day = add_forecast_line(
        day, setup["department"], setup["roll"]["id"], "MIDDAY", 280
    )
    setup["bake_day"] = run_plan_generation(day, setup["department"])
    return setup


def test_plan_grants_each_line_the_smallest_of_demand_labor_and_deck_racks():
    """The waterfall allocation grants the minimum of the three caps.

    PRD §3.3: "Granted racks is the smallest of the required racks, the
    affordable racks and the equipment cap."  The croissant line needs two racks
    (60 units at 40 a rack) and can afford seventeen, so demand caps it at two.
    The dinner-roll line needs twelve racks and can afford six, but the chosen
    deck holds four, so equipment caps it at four.

    Design: Difficulty/combinatorial_formula/plan_generation_takes_min_of_forecast_labor_and_oven_racks
    """
    setup = _setup_waterfall_day()
    day = setup["bake_day"]
    assert_bake_day(day)
    assert day["plan_posture"] == "PLANNED"

    rows, meta = list_runs_for_day(day["id"])
    assert meta["total_count"] == 2, (
        f"Expected exactly two generated runs, got {meta['total_count']}"
    )

    croissant_run = _run_for_product(rows, setup["croissant"]["id"])
    assert_production_run(croissant_run)
    assert croissant_run["origin"] == "PLAN_GENERATED"
    assert croissant_run["execution_status"] == "SCHEDULED"
    assert croissant_run["disposition_status"] == "PENDING"
    assert croissant_run["rack_count"] == 2
    assert croissant_run["planned_units"] == 80
    assert_minutes(croissant_run["planned_labor_minutes"], 27.00, "croissant planned labor")
    assert croissant_run["oven_id"] == setup["oven"]["id"]
    assert croissant_run["deck_index"] == 0
    assert_instant(croissant_run["bake_start_utc"], "2026-08-12T04:00:00Z", "bake_start_utc")
    assert_null(croissant_run["proof_start_utc"], "par-baked proof_start_utc")

    roll_run = _run_for_product(rows, setup["roll"]["id"])
    assert roll_run["rack_count"] == 4, (
        "The dinner-roll line must be capped by the deck's four-rack capacity"
    )
    assert roll_run["planned_units"] == 100
    assert_minutes(roll_run["planned_labor_minutes"], 68.00, "roll planned labor")
    assert_instant(roll_run["bake_start_utc"], "2026-08-12T09:00:00Z", "midday bake_start_utc")
    assert_instant(roll_run["proof_start_utc"], "2026-08-12T08:15:00Z", "roll proof_start_utc")

    assert_minutes(day["planned_labor_minutes"], 95.00, "day planned_labor_minutes")
    assert day["planned_units_total"] == 180


def test_rack_granularity_surplus_never_offsets_another_lines_shortfall():
    """Unmet demand accumulates the roll's shortfall and nothing else.

    PRD §3.3: "Rack granularity routinely overshoots a line, and that surplus is
    emphatically not negative unmet demand — it must never be allowed to offset
    another line's shortfall."  The croissant line overshoots by twenty units and
    the roll line falls 180 short, so the day reports 180.

    Design: Difficulty/combinatorial_formula/plan_generation_takes_min_of_forecast_labor_and_oven_racks
    """
    setup = _setup_waterfall_day()
    day = read_bake_day(setup["bake_day"]["id"])

    assert day["plan_unmet_unit_count"] == 180, (
        "Expected only the dinner-roll shortfall of 280 - 4 * 25 = 180 units"
    )

    rows, _ = list_runs_for_day(day["id"])
    croissant_run = _run_for_product(rows, setup["croissant"]["id"])
    roll_run = _run_for_product(rows, setup["roll"]["id"])

    # Demand caps the croissant line: two racks required, seventeen affordable,
    # four on the deck.
    assert croissant_run["rack_count"] == 2
    assert croissant_run["planned_units"] == 80
    # Equipment caps the roll line: twelve racks required, six affordable, four
    # on the deck.
    assert roll_run["rack_count"] == 4
    assert roll_run["planned_units"] == 100


def _draft_day_with_a_zero_unit_forecast():
    """A DRAFT day carrying a single croissant line forecast at zero units."""
    setup = setup_reference_data()
    day = open_bake_day(setup["department"])
    setup["bake_day"] = add_forecast_line(
        day, setup["department"], setup["croissant"]["id"], "MORNING", 0
    )
    return setup


def test_a_forecast_of_zero_units_leaves_the_plan_empty_and_is_rejected():
    """A line whose effective demand is zero is skipped, so nothing is planned.

    PRD §3.3: "If the walk created no run at all — because the day has no
    forecast lines, because every line's effective demand rounded to zero, or
    because nothing anywhere proved grantable — the whole request is rejected
    with `ERR_EMPTY_PRODUCTION_PLAN` (HTTP 422) and the day's posture does not
    change."  A skipped line also contributes nothing to unmet demand.

    Design: Difficulty/boundary_precision_check/forecast_of_zero_units_yields_empty_plan_rejection
    """
    setup = _draft_day_with_a_zero_unit_forecast()
    day = setup["bake_day"]
    version_before = day["version"]

    response = api_client.generate_plan(
        day["id"], generate_plan_payload(version_before), setup["manager"]
    )
    validate_error(response, "ERR_EMPTY_PRODUCTION_PLAN", 422)

    unchanged = read_bake_day(day["id"])
    assert unchanged["plan_posture"] == "DRAFT", (
        "A rejected generation leaves the day's posture where it was"
    )
    assert unchanged["version"] == version_before
    assert unchanged["plan_unmet_unit_count"] == 0, (
        "A line skipped for zero effective demand contributes nothing to unmet demand"
    )
    assert_minutes(unchanged["planned_labor_minutes"], 0.00, "planned_labor_minutes")
    assert unchanged["planned_units_total"] == 0

    rows, meta = list_runs_for_day(day["id"])
    assert meta["total_count"] == 0
    assert rows == []


def test_a_single_forecast_unit_is_enough_to_grant_one_whole_rack():
    """One forecast unit rounds up to a whole rack and the day becomes PLANNED.

    PRD §3.3: "Required racks is the effective demand divided by the product's
    `units_per_rack`, rounded up to the next whole rack."  One croissant unit
    therefore buys a whole forty-unit rack, and the zero-unit line beside it is
    still skipped.

    Design: Difficulty/boundary_precision_check/forecast_of_zero_units_yields_empty_plan_rejection
    """
    setup = _draft_day_with_a_zero_unit_forecast()
    day = add_forecast_line(
        setup["bake_day"], setup["department"], setup["croissant"]["id"], "MIDDAY", 1
    )
    planned = run_plan_generation(day, setup["department"])

    assert planned["plan_posture"] == "PLANNED"
    assert planned["planned_units_total"] == 40
    assert planned["plan_unmet_unit_count"] == 0

    rows, meta = list_runs_for_day(planned["id"])
    assert meta["total_count"] == 1, "Only the one-unit midday line is grantable"
    run = rows[0]
    assert run["rack_count"] == 1
    assert run["planned_units"] == 40
    assert_minutes(run["planned_labor_minutes"], 21.00, "planned_labor_minutes")
    assert run["deck_index"] == 0
    assert_instant(run["bake_start_utc"], "2026-08-12T09:00:00Z", "midday bake_start_utc")


def test_regeneration_supersedes_generated_runs_and_spares_manual_ones():
    """The supersede pass cancels only plan-generated scheduled runs.

    PRD §3.3: "every run on the day whose `origin` is `PLAN_GENERATED` and whose
    `execution_status` is still `SCHEDULED` is moved to `CANCELLED` with
    `cancelled_reason` set to `PLAN_SUPERSEDED`".  Anything a human created by
    hand survives untouched and its labor still consumes the budget.

    Design: Corner/state_machines/plan_regeneration_supersedes_generated_runs_and_spares_manual_ones
    """
    setup = setup_planned_day()
    old_filler_run = setup["filler_run"]
    manual = schedule_par_baked_run(setup, rack_count=2, deck_index=0, headers=BAKER)

    day_before = read_bake_day(setup["bake_day"]["id"])
    version_before = day_before["version"]
    regenerated = run_plan_generation(day_before, setup["department"])

    superseded = get_success_data(
        api_client.get_production_run(old_filler_run["id"], REGIONAL_ADMIN)
    )
    assert superseded["execution_status"] == "CANCELLED"
    assert superseded["cancelled_reason"] == "PLAN_SUPERSEDED"

    survivor = get_success_data(
        api_client.get_production_run(manual["id"], REGIONAL_ADMIN)
    )
    assert survivor["execution_status"] == "SCHEDULED"
    assert survivor["origin"] == "MANUAL"
    assert survivor["version"] == 1, "A spared manual run is not mutated at all"
    assert_null(survivor["cancelled_reason"], "manual run cancelled_reason")

    rows, meta = list_runs_for_day(regenerated["id"], execution_status="SCHEDULED")
    assert meta["total_count"] == 2
    scheduled_ids = {row["id"] for row in rows}
    assert manual["id"] in scheduled_ids
    assert old_filler_run["id"] not in scheduled_ids, (
        "The superseded run is replaced by a freshly generated one"
    )

    assert_minutes(regenerated["planned_labor_minutes"], 27.00, "planned_labor_minutes")
    assert regenerated["planned_units_total"] == 81
    assert regenerated["plan_unmet_unit_count"] == 0
    assert regenerated["version"] == version_before + 1


def test_a_second_forecast_line_for_the_same_product_and_daypart_is_rejected():
    """One line per product-and-daypart pair, but other dayparts stay open.

    PRD §3.2: "Only one line may exist per product-and-daypart pair on a given
    day: a second attempt at the same pair is rejected with
    `ERR_DUPLICATE_FORECAST_LINE`."  The same product in a different daypart is a
    different pair and is accepted.

    Design: Corner/validations/a_second_forecast_line_for_the_same_product_and_daypart_is_rejected
    """
    setup = setup_draft_day()
    croissant_id = setup["croissant"]["id"]
    day = add_forecast_line(
        setup["bake_day"], setup["department"], croissant_id, "MORNING", 40
    )

    duplicate = api_client.append_forecast_line(
        day["id"],
        forecast_line_payload(croissant_id, "MORNING", 25),
        setup["manager"],
    )
    validate_error(duplicate, "ERR_DUPLICATE_FORECAST_LINE", 409)

    other_daypart = validate_success(
        api_client.append_forecast_line(
            day["id"],
            forecast_line_payload(croissant_id, "MIDDAY", 25),
            setup["manager"],
        ),
        200,
    )
    assert len(other_daypart["forecast_lines"]) == 2
    morning = find_forecast_line(other_daypart, croissant_id, "MORNING")
    assert morning["forecasted_units"] == 40, (
        "The rejected duplicate must not have overwritten the original line"
    )
    midday = find_forecast_line(other_daypart, croissant_id, "MIDDAY")
    assert midday["forecasted_units"] == 25


def test_plan_generation_rejects_a_stale_bake_day_version_and_bumps_it_on_success():
    """The version precondition is exact, and a successful pass advances it.

    PRD §2.5: "If that number does not equal the bake day's current `version`,
    the request is rejected with `ERR_STALE_BAKE_DAY_VERSION` (HTTP 412)."
    Appending a forecast line is an ordinary mutation, so it invalidates the
    version a client observed before it, and replaying an accepted version fails
    the same way.

    Design: Corner/complexity_layers/plan_generation_rejects_a_stale_bake_day_version_and_bumps_it_on_success
    """
    setup = setup_draft_day()
    stale_version = setup["bake_day"]["version"]
    day = add_forecast_line(
        setup["bake_day"], setup["department"], setup["croissant"]["id"], "MORNING", 40
    )
    fresh_version = day["version"]
    assert fresh_version == stale_version + 1, (
        "Appending a forecast line increments the bake day's version by exactly 1"
    )

    rejected = api_client.generate_plan(
        day["id"], generate_plan_payload(stale_version), setup["manager"]
    )
    validate_error(rejected, "ERR_STALE_BAKE_DAY_VERSION", 412)

    untouched = read_bake_day(day["id"])
    assert untouched["plan_posture"] == "DRAFT"
    assert untouched["version"] == fresh_version
    _, meta = list_runs_for_day(day["id"])
    assert meta["total_count"] == 0, "A stale generation must create no runs"

    planned = validate_success(
        api_client.generate_plan(
            day["id"], generate_plan_payload(fresh_version), setup["manager"]
        ),
        200,
    )
    assert planned["plan_posture"] == "PLANNED"
    assert planned["version"] == fresh_version + 1

    replay = api_client.generate_plan(
        day["id"], generate_plan_payload(fresh_version), setup["manager"]
    )
    validate_error(replay, "ERR_STALE_BAKE_DAY_VERSION", 412)


def test_forecast_line_links_a_product_to_a_bake_day_on_the_parent_record():
    """The link lives on the bake day's forecast_lines array, not on the product.

    PRD §3.2: "The append is an ordinary mutation of the day and answers with the
    whole bake day, whose `forecast_lines` array grows by one object of the shape
    product, daypart and forecast count."  The product row itself is not mutated
    by being forecast.

    Design: Corner/endpoints/forecast_line_links_a_product_to_a_bake_day_on_the_parent_record
    """
    setup = setup_draft_day()
    croissant_id = setup["croissant"]["id"]
    product_before = get_success_data(
        api_client.get_product(croissant_id, REGIONAL_ADMIN)
    )

    day = add_forecast_line(
        setup["bake_day"], setup["department"], croissant_id, "MORNING", 40
    )
    day = add_forecast_line(day, setup["department"], croissant_id, "MIDDAY", 20)

    assert len(day["forecast_lines"]) == 2
    for daypart, units in (("MORNING", 40), ("MIDDAY", 20)):
        line = find_forecast_line(day, croissant_id, daypart)
        assert line["product_id"] == croissant_id
        assert line["daypart"] == daypart
        assert line["forecasted_units"] == units

    product_after = get_success_data(
        api_client.get_product(croissant_id, REGIONAL_ADMIN)
    )
    assert product_after["version"] == product_before["version"], (
        "Forecasting a product does not mutate the product row"
    )
    assert product_after["updated_at"] == product_before["updated_at"]

    planned = run_plan_generation(day, setup["department"])
    assert planned["plan_posture"] == "PLANNED"
    assert planned["planned_units_total"] > 0
    rows, _ = list_runs_for_day(planned["id"])
    forecast_driven = [row for row in rows if row["product_id"] == croissant_id]
    assert forecast_driven, "The forecast line must drive a run for that product"
    for row in forecast_driven:
        assert row["origin"] == "PLAN_GENERATED"
