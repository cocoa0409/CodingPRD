"""Shelf life, markdown, waste attestation and the two shrink ratios."""

from test_helpers import (
    BAKER,
    BAKER_ONE_USER_ID,
    BAKER_TWO_USER_ID,
    REGIONAL_ADMIN,
    SECOND_BAKER,
    api_client,
    assert_cents,
    assert_null,
    assert_ratio,
    assert_run_unit_conservation,
    assert_waste_record,
    attest_waste,
    create_completed_par_baked_run,
    create_completed_scratch_run,
    create_scratch_milk_product_payload,
    create_waste_record_payload,
    drive_run_to_completed,
    provision_product,
    read_bake_day,
    read_ingredient,
    read_run,
    read_waste_record,
    recipe_line,
    schedule_par_baked_run,
    schedule_run,
    set_clock,
    setup_completed_run_with_waste,
    setup_planned_day,
    validate_error,
    validate_paginated,
    validate_success,
    void_waste,
    void_waste_record_payload,
)

BAKE_DAY_MORNING = "2026-08-12T04:00:00Z"


def _day_with_a_cheap_and_an_expensive_batch():
    """Two completed batches of 80 units: milk bread at 10 cents, croissant at 8.

    The scratch milk bread costs 800 cents of flour for 80 units and the par-baked
    croissant 600 cents for the same 80 units, so the day carries 1400 cents of
    production cost and 160 produced units across two different cost bases.
    """
    setup = setup_planned_day()
    milk_bread = provision_product(
        create_scratch_milk_product_payload(
            setup["department"]["id"],
            recipe_lines=[recipe_line(setup["flour"]["id"], 20)],
        )
    )
    expensive = schedule_run(
        setup["bake_day"],
        milk_bread["id"],
        rack_count=4,
        oven_id=setup["oven"]["id"],
        deck_index=0,
        proof_start_utc=BAKE_DAY_MORNING,
        bake_start_utc="2026-08-12T04:45:00Z",
    )
    setup["expensive"] = drive_run_to_completed(expensive, "SCRATCH", 80)
    setup["cheap"] = create_completed_par_baked_run(
        setup, rack_count=2, deck_index=1, bake_start_utc=BAKE_DAY_MORNING
    )
    assert_cents(setup["expensive"]["unit_cost_basis_cents"], 10, "milk bread basis")
    assert_cents(setup["cheap"]["unit_cost_basis_cents"], 8, "croissant basis")
    return setup


def test_wasting_expensive_units_drives_the_cost_ratio_above_the_unit_ratio():
    """Ten wasted units read differently on the two bases.

    PRD §3.6: "Because the cost basis weights each wasted unit by the cost basis of
    the run it came from, wasting expensive units moves it faster than wasting cheap
    ones, and a day mixing premium cakes with cheap rolls will report two visibly
    different rates on the same physical waste."  Ten units off the 10-cent batch
    book 100 cents of shrink against 1400 cents of cost, or 0.0714, while the unit
    basis reads a flat 10 of 160.

    Design: Difficulty/dual_variant_calc/shrink_rate_cost_basis_vs_unit_basis_diverge_on_same_waste
    """
    setup = _day_with_a_cheap_and_an_expensive_batch()
    record = attest_waste(
        setup["expensive"]["id"], 10, disposition_reason="BURNT"
    )
    assert_waste_record(record)
    assert_cents(record["unit_cost_basis_cents"], 10, "snapshotted basis")
    assert_cents(record["waste_cost_cents"], 100, "waste_cost_cents")

    day = read_bake_day(setup["bake_day"]["id"])
    assert_cents(day["production_cost_cents"], 1400, "production_cost_cents")
    assert day["produced_units_total"] == 160
    assert day["waste_units_total"] == 10
    assert_cents(day["shrink_cost_cents"], 100, "shrink_cost_cents")
    assert_ratio(day["shrink_cost_basis_pct"], 0.0714, "shrink_cost_basis_pct")
    assert_ratio(day["shrink_unit_basis_pct"], 0.0625, "shrink_unit_basis_pct")
    assert day["markdown_authorization"] == "MANAGER_ONLY"

    run = read_run(setup["expensive"]["id"])
    assert run["wasted_units_total"] == 10
    assert run["on_shelf_units"] == 70
    assert run["disposition_status"] == "ON_SHELF"


def test_wasting_cheap_units_leaves_the_cost_ratio_below_the_unit_ratio():
    """The same ten units off the cheaper batch invert the two readings.

    PRD §3.6: "`shrink_cost_basis_pct` is the day's `shrink_cost_cents` divided by
    its `production_cost_cents`, rounded half up to four decimal places", while
    "`shrink_unit_basis_pct` is the day's `waste_units_total` divided by its
    `produced_units_total`".  Eighty cents against 1400 reads 0.0571 where the unit
    basis still reads 0.0625.

    Design: Difficulty/dual_variant_calc/shrink_rate_cost_basis_vs_unit_basis_diverge_on_same_waste
    """
    setup = _day_with_a_cheap_and_an_expensive_batch()
    record = attest_waste(setup["cheap"]["id"], 10, disposition_reason="BURNT")
    assert_cents(record["unit_cost_basis_cents"], 8, "snapshotted basis")
    assert_cents(record["waste_cost_cents"], 80, "waste_cost_cents")

    day = read_bake_day(setup["bake_day"]["id"])
    assert day["waste_units_total"] == 10
    assert_cents(day["shrink_cost_cents"], 80, "shrink_cost_cents")
    assert_ratio(day["shrink_cost_basis_pct"], 0.0571, "shrink_cost_basis_pct")
    assert_ratio(
        day["shrink_unit_basis_pct"],
        0.0625,
        "the unit basis is blind to which batch the units came from",
    )
    assert day["shrink_cost_basis_pct"] < day["shrink_unit_basis_pct"]

    untouched = read_run(setup["expensive"]["id"])
    assert untouched["wasted_units_total"] == 0
    assert untouched["on_shelf_units"] == 80


def test_a_waste_attestation_cascades_a_budget_breach_into_the_day():
    """One attestation moves the record, the run, the day and the gate.

    PRD §3.6: "Only one of them has teeth: the cost-basis ratio is the sole variant
    that can restrict markdown, and it does so when it is **strictly** greater than
    the department's `shrink_budget_pct`, at which point the day's
    `markdown_authorization` flips to `MANAGER_ONLY`."  Eighty cents of shrink
    against 600 cents of production is 0.1333, far past the three-percent budget.

    Design: Difficulty/transitive_cascade/waste_attestation_cascades_shrink_breach_into_markdown_lockdown
    """
    setup = setup_completed_run_with_waste(
        waste_units=10, disposition_reason="DAMAGED", clock=BAKE_DAY_MORNING
    )

    record = setup["waste_record"]
    assert_waste_record(record)
    assert record["record_status"] == "ACTIVE"
    assert record["bake_day_id"] == setup["bake_day"]["id"]
    assert record["production_run_id"] == setup["run"]["id"]
    assert record["attested_by_user_id"] == BAKER_TWO_USER_ID
    assert_cents(record["unit_cost_basis_cents"], 8, "unit_cost_basis_cents")
    assert_cents(record["waste_cost_cents"], 80, "waste_cost_cents")
    assert_null(record["voided_by_user_id"], "voided_by_user_id")

    run = setup["run"]
    assert run["wasted_units_total"] == 10
    assert run["on_shelf_units"] == 70
    assert run["disposition_status"] == "ON_SHELF"
    assert_run_unit_conservation(run)

    day = setup["bake_day"]
    assert day["waste_units_total"] == 10
    assert_cents(day["shrink_cost_cents"], 80, "shrink_cost_cents")
    assert_ratio(day["shrink_cost_basis_pct"], 0.1333, "shrink_cost_basis_pct")
    assert_ratio(day["shrink_unit_basis_pct"], 0.1250, "shrink_unit_basis_pct")
    assert day["markdown_authorization"] == "MANAGER_ONLY"


def test_the_locked_down_gate_refuses_a_baker_and_admits_the_manager():
    """The flipped gate is what actually stops the discount.

    PRD §2.7: "When it reads `MANAGER_ONLY`, only a `DepartmentManager` may; a
    `Baker` attempting a markdown is rejected with
    `ERR_MARKDOWN_AUTHORIZATION_REQUIRED` (HTTP 403)."  The manager's discount on
    the very same run inside the very same window succeeds.

    Design: Difficulty/transitive_cascade/waste_attestation_cascades_shrink_breach_into_markdown_lockdown
    """
    setup = setup_completed_run_with_waste(waste_units=10, clock=BAKE_DAY_MORNING)
    assert setup["bake_day"]["markdown_authorization"] == "MANAGER_ONLY"
    run_id = setup["run"]["id"]

    set_clock("2026-08-12T11:00:00Z")
    refused = api_client.markdown_run(run_id, BAKER)
    validate_error(refused, "ERR_MARKDOWN_AUTHORIZATION_REQUIRED", 403)

    unchanged = read_run(run_id)
    assert unchanged["disposition_status"] == "ON_SHELF"
    assert_null(unchanged["markdown_unit_price_cents"], "markdown_unit_price_cents")

    allowed = validate_success(api_client.markdown_run(run_id, setup["manager"]), 200)
    assert allowed["disposition_status"] == "MARKED_DOWN"
    assert_cents(allowed["markdown_unit_price_cents"], 75, "markdown_unit_price_cents")
    assert allowed["on_shelf_units"] == 70


def test_a_shrink_ratio_exactly_at_the_budget_leaves_markdown_on_auto():
    """Landing exactly on the budget is compliant.

    PRD §2.7: "Equality with the budget is compliant and never restricts markdown."
    Five wasted units off a 100-unit batch costing 1000 cents book 50 cents of
    shrink, which is exactly the department's five-percent budget.

    Design: Difficulty/boundary_precision_check/shrink_ratio_exactly_at_budget_leaves_markdown_on_auto
    """
    setup = setup_planned_day(department_overrides={"shrink_budget_pct": 0.05})
    run = create_completed_scratch_run(setup, rack_count=4)
    assert_cents(run["ingredient_cost_cents"], 1000, "ingredient_cost_cents")
    assert_cents(run["unit_cost_basis_cents"], 10, "unit_cost_basis_cents")

    attest_waste(run["id"], 5, disposition_reason="OVERPRODUCTION")

    day = read_bake_day(setup["bake_day"]["id"])
    assert_cents(day["shrink_cost_cents"], 50, "shrink_cost_cents")
    assert_ratio(day["shrink_cost_basis_pct"], 0.0500, "shrink_cost_basis_pct")
    assert_ratio(day["shrink_unit_basis_pct"], 0.0500, "shrink_unit_basis_pct")
    assert day["markdown_authorization"] == "AUTO"

    settled = read_run(run["id"])
    assert settled["wasted_units_total"] == 5
    assert settled["on_shelf_units"] == 95
    assert settled["disposition_status"] == "ON_SHELF"


def test_one_unit_past_the_budget_flips_markdown_to_manager_only():
    """A single extra unit takes the ratio strictly above the budget.

    PRD §3.6: "the cost-basis ratio is the sole variant that can restrict markdown,
    and it does so when it is **strictly** greater than the department's
    `shrink_budget_pct`".  Six wasted units book 60 cents of shrink on 1000 cents of
    cost, or 0.0600 against a 0.0500 budget.

    Design: Difficulty/boundary_precision_check/shrink_ratio_exactly_at_budget_leaves_markdown_on_auto
    """
    setup = setup_planned_day(department_overrides={"shrink_budget_pct": 0.05})
    run = create_completed_scratch_run(setup, rack_count=4)

    attest_waste(run["id"], 5, disposition_reason="OVERPRODUCTION")
    at_the_budget = read_bake_day(setup["bake_day"]["id"])
    assert at_the_budget["markdown_authorization"] == "AUTO"

    attest_waste(run["id"], 1, disposition_reason="DAY_OLD_UNSOLD")

    day = read_bake_day(setup["bake_day"]["id"])
    assert day["waste_units_total"] == 6
    assert_cents(day["shrink_cost_cents"], 60, "shrink_cost_cents")
    assert_ratio(day["shrink_cost_basis_pct"], 0.0600, "shrink_cost_basis_pct")
    assert day["markdown_authorization"] == "MANAGER_ONLY"
    assert day["version"] > at_the_budget["version"], (
        "Flipping the gate is a mutation of the bake day"
    )

    settled = read_run(run["id"])
    assert settled["wasted_units_total"] == 6
    assert settled["on_shelf_units"] == 94
    assert settled["disposition_status"] == "ON_SHELF"


def test_writing_off_a_whole_batch_clears_it_and_puts_shrink_at_one():
    """A total write-off drives every ratio to unity.

    PRD §3.6: "Creating the record drives the run's `wasted_units_total` up and its
    `on_shelf_units` down, and when `on_shelf_units` reaches exactly zero the run's
    disposition falls to `CLEARED`".  A hundred units off a hundred-unit batch is
    1000 cents of shrink against 1000 cents of cost.

    Design: Difficulty/compensating_invariant/voiding_waste_restores_run_unit_conservation
    """
    setup = setup_planned_day()
    run = create_completed_scratch_run(setup, rack_count=4)
    assert run["actual_units"] == 100
    assert_cents(run["unit_cost_basis_cents"], 10, "unit_cost_basis_cents")

    record = attest_waste(run["id"], 100, disposition_reason="BURNT")
    assert record["record_status"] == "ACTIVE"
    assert_cents(record["waste_cost_cents"], 1000, "waste_cost_cents")

    cleared = read_run(run["id"])
    assert cleared["wasted_units_total"] == 100
    assert cleared["on_shelf_units"] == 0
    assert cleared["disposition_status"] == "CLEARED"
    assert cleared["execution_status"] == "COMPLETED"
    assert_run_unit_conservation(cleared)

    day = read_bake_day(setup["bake_day"]["id"])
    assert day["waste_units_total"] == 100
    assert_cents(day["shrink_cost_cents"], 1000, "shrink_cost_cents")
    assert_ratio(day["shrink_cost_basis_pct"], 1.0000, "shrink_cost_basis_pct")
    assert_ratio(day["shrink_unit_basis_pct"], 1.0000, "shrink_unit_basis_pct")
    assert day["markdown_authorization"] == "MANAGER_ONLY"


def test_voiding_that_write_off_restores_the_run_the_day_and_the_gate():
    """The reversal walks the same cascade backwards and leaves no residue.

    PRD §3.6: "A voided record counts toward nothing: it is excluded from every
    waste rollup on the day."  The run's units return to the shelf at full price,
    both ratios fall back to 0.0000 and the gate returns to `AUTO`, while the flour
    the batch actually consumed stays consumed.

    Design: Difficulty/compensating_invariant/voiding_waste_restores_run_unit_conservation
    """
    setup = setup_planned_day()
    run = create_completed_scratch_run(setup, rack_count=4)
    record = attest_waste(run["id"], 100, disposition_reason="BURNT")
    flour_after_baking = read_ingredient(setup["flour"]["id"])
    assert flour_after_baking["on_hand_units"] == 1900, (
        "Four racks at 25 flour units a rack consume 100 units of flour"
    )

    voided = void_waste(record["id"], setup["department"], "Counted the wrong rack")
    assert voided["record_status"] == "VOIDED"
    assert voided["void_reason"] == "Counted the wrong rack"
    assert voided["voided_by_user_id"] == setup["department"]["id"]
    assert voided["version"] == record["version"] + 1
    assert_cents(
        voided["waste_cost_cents"],
        1000,
        "the frozen snapshot survives the void untouched",
    )

    restored = read_run(run["id"])
    assert restored["wasted_units_total"] == 0
    assert restored["on_shelf_units"] == 100
    assert restored["disposition_status"] == "ON_SHELF", (
        "With no markdown price on file the batch returns at full retail"
    )
    assert_null(restored["markdown_unit_price_cents"], "markdown_unit_price_cents")
    assert_run_unit_conservation(restored)

    day = read_bake_day(setup["bake_day"]["id"])
    assert day["waste_units_total"] == 0
    assert_cents(day["shrink_cost_cents"], 0, "shrink_cost_cents")
    assert_ratio(day["shrink_cost_basis_pct"], 0.0000, "shrink_cost_basis_pct")
    assert_ratio(day["shrink_unit_basis_pct"], 0.0000, "shrink_unit_basis_pct")
    assert day["markdown_authorization"] == "AUTO"
    assert day["produced_units_total"] == 100, "The void does not unmake production"

    flour = read_ingredient(setup["flour"]["id"])
    assert flour["on_hand_units"] == 1900, (
        "Reversing a waste record does not put flour back in the bin"
    )


def _day_with_two_sibling_croissant_batches():
    """Two completed croissant batches baked at 04:00Z, both expiring at 14:35Z."""
    setup = setup_planned_day(clock=BAKE_DAY_MORNING)
    setup["first"] = create_completed_par_baked_run(
        setup, rack_count=2, deck_index=0, bake_start_utc=BAKE_DAY_MORNING
    )
    setup["second"] = create_completed_par_baked_run(
        setup, rack_count=2, deck_index=1, bake_start_utc=BAKE_DAY_MORNING
    )
    return setup


def test_the_markdown_window_opens_four_hours_out_and_shuts_at_expiry():
    """The two edges of the four-hour window behave differently on purpose.

    PRD §3.6: "The window opens at the run's `expires_utc` less four hours and it
    closes at `expires_utc` itself, and the two edges are treated differently on
    purpose: the opening instant is inside the window, and the expiry instant is
    outside it."  A croissant baked at 04:00Z is ready at 04:35Z and expires ten
    hours later at 14:35Z, so 10:34Z is `ERR_MARKDOWN_WINDOW_NOT_OPEN`, 10:35Z is
    the first legal instant, and 14:35Z is already `ERR_PRODUCT_EXPIRED`.

    Design: Corner/calculations/markdown_window_opens_four_hours_before_expiry_and_shuts_at_expiry
    """
    setup = _day_with_two_sibling_croissant_batches()
    first = setup["first"]
    assert first["ready_utc"].startswith("2026-08-12T04:35:00")
    assert first["expires_utc"].startswith("2026-08-12T14:35:00")
    assert read_bake_day(setup["bake_day"]["id"])["markdown_authorization"] == "AUTO"

    set_clock("2026-08-12T10:34:00Z")
    too_early = api_client.markdown_run(first["id"], BAKER)
    validate_error(too_early, "ERR_MARKDOWN_WINDOW_NOT_OPEN", 422)
    assert read_run(first["id"])["disposition_status"] == "ON_SHELF"

    set_clock("2026-08-12T10:35:00Z")
    discounted = validate_success(api_client.markdown_run(first["id"], BAKER), 200)
    assert discounted["disposition_status"] == "MARKED_DOWN"
    assert_cents(
        discounted["markdown_unit_price_cents"], 75, "markdown_unit_price_cents"
    )
    assert discounted["version"] == first["version"] + 1

    set_clock("2026-08-12T14:35:00Z")
    expired = api_client.markdown_run(setup["second"]["id"], BAKER)
    validate_error(expired, "ERR_PRODUCT_EXPIRED", 422)
    assert read_run(setup["second"]["id"])["disposition_status"] == "ON_SHELF"


def test_the_unit_cost_basis_is_rounded_once_before_waste_multiplies_it():
    """Waste cost multiplies the rounded basis, not the raw quotient.

    PRD §3.6: "Its `waste_cost_cents` is that snapshotted per-unit basis multiplied
    by its own `units`, with no further rounding — the per-unit rounding already
    happened at completion, and multiplying an already-rounded basis is the whole
    point of the ordering."  Six hundred cents over 80 units is 7.5, which rounds to
    a basis of 8, so ten wasted units cost 80 cents rather than the 75 the unrounded
    quotient would have produced.

    Design: Corner/calculations/unit_cost_basis_rounds_once_per_unit_before_waste_multiplies_it
    """
    setup = setup_planned_day()
    run = create_completed_par_baked_run(setup, rack_count=2)
    assert run["actual_units"] == 80
    assert_cents(run["ingredient_cost_cents"], 600, "ingredient_cost_cents")
    assert_cents(run["unit_cost_basis_cents"], 8, "7.5 cents a unit rounds half up")

    record = attest_waste(run["id"], 10, disposition_reason="DAMAGED")
    assert_cents(record["unit_cost_basis_cents"], 8, "snapshotted basis")
    assert record["waste_cost_cents"] == 80, (
        "Ten units at the rounded 8-cent basis cost 80 cents, not 10 * 7.5 = 75"
    )

    day = read_bake_day(setup["bake_day"]["id"])
    assert_cents(day["shrink_cost_cents"], 80, "shrink_cost_cents")
    assert_ratio(day["shrink_cost_basis_pct"], 0.1333, "shrink_cost_basis_pct")
    assert_ratio(day["shrink_unit_basis_pct"], 0.1250, "shrink_unit_basis_pct")

    settled = read_run(run["id"])
    assert settled["on_shelf_units"] == 70
    assert settled["disposition_status"] == "ON_SHELF"


def test_attested_waste_may_equal_but_never_exceed_the_units_on_shelf():
    """Two attestations may drain the shelf exactly; a third unit cannot.

    PRD §3.6: "The `units` figure must be at least 1 and may not exceed the run's
    remaining `on_shelf_units`; exceeding it is rejected with
    `ERR_WASTE_EXCEEDS_ON_SHELF`, which is also what a run whose shelf stock has
    already reached zero returns for any further attestation."  Thirty units then
    fifty drain an 80-unit batch to exactly zero.

    Design: Corner/validations/attested_waste_may_equal_but_never_exceed_the_units_on_shelf
    """
    setup = setup_planned_day()
    run = create_completed_par_baked_run(setup, rack_count=2)

    attest_waste(run["id"], 30, disposition_reason="DAMAGED")
    partial = read_run(run["id"])
    assert partial["on_shelf_units"] == 50
    assert partial["disposition_status"] == "ON_SHELF"

    attest_waste(run["id"], 50, disposition_reason="BURNT")
    drained = read_run(run["id"])
    assert drained["wasted_units_total"] == 80
    assert drained["on_shelf_units"] == 0
    assert drained["disposition_status"] == "CLEARED"
    assert_run_unit_conservation(drained)

    one_too_many = api_client.create_waste_record(
        create_waste_record_payload(run["id"], 1, "OVERPRODUCTION"), SECOND_BAKER
    )
    validate_error(one_too_many, "ERR_WASTE_EXCEEDS_ON_SHELF", 422)

    day = read_bake_day(setup["bake_day"]["id"])
    assert day["waste_units_total"] == 80, "The rejected unit was never recorded"
    assert_cents(day["shrink_cost_cents"], 640, "80 units at the 8-cent basis")


def test_waste_attestation_checks_the_run_state_before_the_unit_ceiling():
    """A scheduled run reports its state, not the impossible unit count.

    PRD §2.10 puts own-entity state in band 7 — "the run being written off is
    completed (`ERR_RUN_NOT_COMPLETED`)" — while the unit ceiling sits in band 11,
    "attested waste within the run's remaining shelf units
    (`ERR_WASTE_EXCEEDS_ON_SHELF`)".  Nine hundred and ninety-nine units against a
    `SCHEDULED` run breaks both, so `ERR_RUN_NOT_COMPLETED` surfaces first and the
    ceiling only becomes visible once the batch has been baked.

    Design: Corner/validations/waste_attestation_checks_the_runs_state_before_it_checks_the_unit_ceiling
    """
    setup = setup_planned_day()
    run = schedule_par_baked_run(setup, rack_count=2)
    assert run["execution_status"] == "SCHEDULED"

    state_first = api_client.create_waste_record(
        create_waste_record_payload(run["id"], 999, "DAMAGED"), SECOND_BAKER
    )
    validate_error(state_first, "ERR_RUN_NOT_COMPLETED", 409)

    completed = drive_run_to_completed(run, "PAR_BAKED", 80)
    assert completed["on_shelf_units"] == 80

    ceiling_now = api_client.create_waste_record(
        create_waste_record_payload(run["id"], 999, "DAMAGED"), SECOND_BAKER
    )
    validate_error(ceiling_now, "ERR_WASTE_EXCEEDS_ON_SHELF", 422)

    records, meta = validate_paginated(
        api_client.list_waste_records(REGIONAL_ADMIN, {"production_run_id": run["id"]})
    )
    assert meta["total_count"] == 0, "Neither rejected attestation created a record"
    assert records == []
    assert read_run(run["id"])["wasted_units_total"] == 0


def test_voiding_an_already_voided_waste_record_is_rejected():
    """A reversal is one-shot: the second void finds the record inactive.

    PRD §3.6: "The record must still be `ACTIVE` — a second attempt is rejected with
    `ERR_WASTE_RECORD_ALREADY_VOIDED`".  The first void has already put the units
    back on the shelf, and the rejected second attempt changes nothing further.

    Design: Corner/state_machines/voiding_an_already_voided_waste_record_is_rejected
    """
    setup = setup_completed_run_with_waste(waste_units=10)
    record = setup["waste_record"]

    voided = void_waste(record["id"], setup["department"], "Counted twice")
    assert voided["record_status"] == "VOIDED"
    assert voided["void_reason"] == "Counted twice"

    again = api_client.void_waste_record(
        record["id"],
        void_waste_record_payload("Counted three times"),
        setup["manager"],
    )
    validate_error(again, "ERR_WASTE_RECORD_ALREADY_VOIDED", 409)

    unchanged = read_waste_record(record["id"])
    assert unchanged["record_status"] == "VOIDED"
    assert unchanged["void_reason"] == "Counted twice", (
        "The rejected second void must not overwrite the stored reason"
    )
    assert unchanged["version"] == voided["version"]
    assert unchanged["voided_by_user_id"] == setup["department"]["id"]

    run = read_run(setup["run"]["id"])
    assert run["wasted_units_total"] == 0
    assert run["on_shelf_units"] == 80
    assert run["disposition_status"] == "ON_SHELF"

    day = read_bake_day(setup["bake_day"]["id"])
    assert day["waste_units_total"] == 0
    assert_cents(day["shrink_cost_cents"], 0, "shrink_cost_cents")
    assert day["markdown_authorization"] == "AUTO"


def test_the_operator_who_completed_a_run_may_not_write_that_run_off():
    """Each baker must have the other one attest the batch he baked.

    PRD §2.9: "If the caller attesting waste is the very operator whose identifier
    completed the run, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."  The two identifiers are compared only to each other, so each baker
    is free to write off the batch the other one completed.

    Design: Corner/rbac/the_operator_who_completed_a_run_cannot_attest_its_waste
    """
    setup = setup_planned_day(department_overrides={"shrink_budget_pct": 0.50})
    baked_by_one = create_completed_par_baked_run(
        setup, rack_count=2, actual_units=40, deck_index=0, headers=BAKER
    )
    baked_by_two = create_completed_par_baked_run(
        setup, rack_count=2, actual_units=40, deck_index=1, headers=SECOND_BAKER
    )
    assert baked_by_one["executed_by_user_id"] == BAKER_ONE_USER_ID
    assert baked_by_two["executed_by_user_id"] == BAKER_TWO_USER_ID

    own_batch = api_client.create_waste_record(
        create_waste_record_payload(baked_by_one["id"], 5, "DAMAGED"), BAKER
    )
    validate_error(own_batch, "ERR_SEGREGATION_OF_DUTIES", 403)
    other_batch = api_client.create_waste_record(
        create_waste_record_payload(baked_by_two["id"], 5, "DAMAGED"), SECOND_BAKER
    )
    validate_error(other_batch, "ERR_SEGREGATION_OF_DUTIES", 403)

    crossed_one = attest_waste(baked_by_one["id"], 5, headers=SECOND_BAKER)
    assert crossed_one["attested_by_user_id"] == BAKER_TWO_USER_ID
    crossed_two = attest_waste(baked_by_two["id"], 5, headers=BAKER)
    assert crossed_two["attested_by_user_id"] == BAKER_ONE_USER_ID

    for run in (baked_by_one, baked_by_two):
        settled = read_run(run["id"])
        assert settled["wasted_units_total"] == 5, (
            "Only the cross-attested record counted"
        )
        assert settled["on_shelf_units"] == 35
        assert settled["disposition_status"] == "ON_SHELF"

    day = read_bake_day(setup["bake_day"]["id"])
    assert day["waste_units_total"] == 10
    assert_cents(day["shrink_cost_cents"], 150, "ten units at the 15-cent basis")
    assert day["markdown_authorization"] == "AUTO"
