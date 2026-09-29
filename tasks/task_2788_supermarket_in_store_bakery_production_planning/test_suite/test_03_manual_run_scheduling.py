"""Scheduling a batch by hand: decks, capacity, equipment and precedence."""

from test_helpers import (
    BAKER,
    DECORATOR,
    REGIONAL_ADMIN,
    api_client,
    assert_cents,
    assert_instant,
    assert_minutes,
    assert_null,
    assert_production_run,
    create_nut_free_oven_payload,
    create_nut_free_product_payload,
    create_production_run_payload,
    create_tree_nut_product_payload,
    create_unbuffered_oven_payload,
    drive_run_to_baking,
    list_runs_for_day,
    lock_day,
    provision_oven,
    provision_product,
    read_bake_day,
    read_run,
    schedule_par_baked_run,
    setup_planned_day,
    validate_error,
    validate_paginated,
    validate_success,
)

SHIFT_START_INSTANT = "2026-08-12T04:00:00Z"


def _create_run(bake_day_id, product_id, headers=BAKER, **payload_kwargs):
    """POST one production run and hand back the raw response."""
    return api_client.create_production_run(
        create_production_run_payload(bake_day_id, product_id, **payload_kwargs),
        headers,
    )


def test_a_rack_count_exactly_at_the_deck_capacity_is_accepted():
    """Landing exactly on the deck's rack capacity passes.

    PRD §3.4: "`rack_count` is at least 1, and when an oven is named it may not
    exceed that oven's `rack_capacity_per_deck`; exceeding it is rejected with
    `ERR_OVEN_RACK_CAPACITY_EXCEEDED`, while a rack count exactly equal to the
    capacity passes."  Four racks of croissant on a four-rack deck therefore plan
    160 units and 15 + 4 * 10 * 0.6 = 39.00 labor minutes.

    Design: Difficulty/boundary_precision_check/rack_count_exactly_at_deck_capacity_is_accepted
    """
    setup = setup_planned_day()
    response = _create_run(
        setup["bake_day"]["id"],
        setup["croissant"]["id"],
        rack_count=4,
        oven_id=setup["oven"]["id"],
        deck_index=0,
        bake_start_utc=SHIFT_START_INSTANT,
    )
    run = validate_success(response, 201)

    assert_production_run(run)
    assert run["rack_count"] == 4
    assert run["planned_units"] == 160
    assert_minutes(run["planned_labor_minutes"], 39.00, "planned_labor_minutes")
    assert_cents(run["ingredient_cost_cents"], 1200, "ingredient_cost_cents")
    assert run["origin"] == "MANUAL"
    assert run["execution_status"] == "SCHEDULED"
    assert run["disposition_status"] == "PENDING"


def test_one_rack_beyond_the_deck_capacity_is_rejected():
    """A fifth rack on a four-rack deck busts the capacity check.

    PRD §3.4: "`rack_count` is at least 1, and when an oven is named it may not
    exceed that oven's `rack_capacity_per_deck`; exceeding it is rejected with
    `ERR_OVEN_RACK_CAPACITY_EXCEEDED`, while a rack count exactly equal to the
    capacity passes."  The accepted four-rack batch still stands and the day's rollups
    count it once.

    Design: Difficulty/boundary_precision_check/rack_count_exactly_at_deck_capacity_is_accepted
    """
    setup = setup_planned_day()
    schedule_par_baked_run(setup, rack_count=4, deck_index=0, headers=BAKER)

    rejected = _create_run(
        setup["bake_day"]["id"],
        setup["croissant"]["id"],
        rack_count=5,
        oven_id=setup["oven"]["id"],
        deck_index=1,
        bake_start_utc=SHIFT_START_INSTANT,
    )
    validate_error(rejected, "ERR_OVEN_RACK_CAPACITY_EXCEEDED", 422)

    day = read_bake_day(setup["bake_day"]["id"])
    assert_minutes(day["planned_labor_minutes"], 39.00, "planned_labor_minutes")
    assert day["planned_units_total"] == 161, (
        "Only the accepted four-rack batch and the one-unit filler batch count"
    )
    _, meta = list_runs_for_day(day["id"])
    assert meta["total_count"] == 2


def test_a_deck_rejects_a_batch_starting_inside_the_changeover_buffer():
    """With a buffer, adjacency on the same deck is a collision.

    PRD §3.4: "with a buffer greater than zero that same adjacency *is* a
    collision, and the gap between the two batches must be at least the buffer in
    minutes."  The holder bakes 05:00Z–05:20Z on a deck whose oven carries a
    twenty-minute changeover buffer, so a batch starting at 05:20Z collides and is
    rejected with `ERR_OVEN_SLOT_CONFLICT`.

    Design: Difficulty/resource_temporal_overlap/oven_deck_rejects_run_inside_the_changeover_buffer
    """
    setup = setup_planned_day()
    holder = schedule_par_baked_run(
        setup, rack_count=4, deck_index=0, bake_start_utc="2026-08-12T05:00:00Z"
    )

    inside_buffer = _create_run(
        setup["bake_day"]["id"],
        setup["croissant"]["id"],
        rack_count=4,
        oven_id=setup["oven"]["id"],
        deck_index=0,
        bake_start_utc="2026-08-12T05:20:00Z",
    )
    validate_error(inside_buffer, "ERR_OVEN_SLOT_CONFLICT", 409)

    unchanged = read_run(holder["id"])
    assert unchanged["execution_status"] == "SCHEDULED"
    assert unchanged["version"] == 1, "A rejected neighbour must not mutate the holder"
    _, meta = list_runs_for_day(setup["bake_day"]["id"])
    assert meta["total_count"] == 2


def test_a_gap_equal_to_the_buffer_or_a_different_deck_is_accepted():
    """A gap of exactly the buffer clears the deck, and other decks never collide.

    PRD §3.4: "Different decks of the same oven never collide with one another,
    and neither do batches on different ovens."  The holder's bake ends at
    05:20Z, so 05:40Z is exactly the twenty-minute buffer away and is accepted,
    while the second deck accepts 05:20Z outright.

    Design: Difficulty/resource_temporal_overlap/oven_deck_rejects_run_inside_the_changeover_buffer
    """
    setup = setup_planned_day()
    schedule_par_baked_run(
        setup, rack_count=4, deck_index=0, bake_start_utc="2026-08-12T05:00:00Z"
    )

    after_the_buffer = validate_success(
        _create_run(
            setup["bake_day"]["id"],
            setup["croissant"]["id"],
            rack_count=4,
            oven_id=setup["oven"]["id"],
            deck_index=0,
            bake_start_utc="2026-08-12T05:40:00Z",
        ),
        201,
    )
    assert_instant(
        after_the_buffer["bake_start_utc"], "2026-08-12T05:40:00Z", "bake_start_utc"
    )

    other_deck = validate_success(
        _create_run(
            setup["bake_day"]["id"],
            setup["croissant"]["id"],
            rack_count=4,
            oven_id=setup["oven"]["id"],
            deck_index=1,
            bake_start_utc="2026-08-12T05:20:00Z",
        ),
        201,
    )
    assert other_deck["deck_index"] == 1

    day = read_bake_day(setup["bake_day"]["id"])
    assert_minutes(day["planned_labor_minutes"], 117.00, "planned_labor_minutes")


def test_a_deck_collision_is_reported_ahead_of_the_rack_overflow():
    """Temporal band 10 fires before the capacity check in band 13.

    PRD §2.10 band 10: "the buffered bake interval does not collide on the deck
    (`ERR_OVEN_SLOT_CONFLICT`)", while rack capacity per deck sits in band 13,
    "**Fiscal and capacity**, evaluated last".  A six-rack batch aimed at an
    occupied four-rack deck breaks both rules, so the collision surfaces.

    Design: Difficulty/priority_pair_validation_conflict/oven_overlap_temporal_check_outranks_rack_capacity_check
    """
    setup = setup_planned_day()
    unbuffered = provision_oven(
        create_unbuffered_oven_payload(setup["department"]["id"])
    )
    holder = validate_success(
        _create_run(
            setup["bake_day"]["id"],
            setup["croissant"]["id"],
            rack_count=4,
            oven_id=unbuffered["id"],
            deck_index=0,
            bake_start_utc="2026-08-12T05:00:00Z",
        ),
        201,
    )

    both_broken = _create_run(
        setup["bake_day"]["id"],
        setup["croissant"]["id"],
        rack_count=6,
        oven_id=unbuffered["id"],
        deck_index=0,
        bake_start_utc="2026-08-12T05:10:00Z",
    )
    validate_error(both_broken, "ERR_OVEN_SLOT_CONFLICT", 409)

    unchanged = read_run(holder["id"])
    assert unchanged["rack_count"] == 4
    assert unchanged["version"] == 1
    _, meta = list_runs_for_day(setup["bake_day"]["id"])
    assert meta["total_count"] == 2


def test_the_rack_overflow_surfaces_once_the_deck_is_free():
    """With the collision removed, the capacity check becomes the first failure.

    PRD §2.10 band 13 is "**Fiscal and capacity**, evaluated last — markdown
    authorisation (`ERR_MARKDOWN_AUTHORIZATION_REQUIRED`), rack capacity per deck
    (`ERR_OVEN_RACK_CAPACITY_EXCEEDED`)".  The unbuffered oven's occupation ends
    at 05:20Z, so a 06:00Z batch is temporally clean and only the six racks on a
    four-rack deck remain wrong.

    Design: Difficulty/priority_pair_validation_conflict/oven_overlap_temporal_check_outranks_rack_capacity_check
    """
    setup = setup_planned_day()
    unbuffered = provision_oven(
        create_unbuffered_oven_payload(setup["department"]["id"])
    )
    validate_success(
        _create_run(
            setup["bake_day"]["id"],
            setup["croissant"]["id"],
            rack_count=4,
            oven_id=unbuffered["id"],
            deck_index=0,
            bake_start_utc="2026-08-12T05:00:00Z",
        ),
        201,
    )

    only_capacity = _create_run(
        setup["bake_day"]["id"],
        setup["croissant"]["id"],
        rack_count=6,
        oven_id=unbuffered["id"],
        deck_index=0,
        bake_start_utc="2026-08-12T06:00:00Z",
    )
    validate_error(only_capacity, "ERR_OVEN_RACK_CAPACITY_EXCEEDED", 422)

    _, meta = list_runs_for_day(setup["bake_day"]["id"])
    assert meta["total_count"] == 2, "The rejected batch must not have been created"


def test_allergen_segregation_is_reported_ahead_of_the_labor_budget():
    """Safety band 9 fires before the fiscal band, even on a starved budget.

    PRD §2.10 band 9: "This band outranks every temporal, constraint,
    referential and fiscal check below it and is itself outranked by every state
    check above it."  A walnut bar on nut-free-dedicated equipment breaks
    segregation while its 10 + 4 * 10 * 0.6 = 34.00 planned minutes also bust the
    day's 30-minute budget, so the answer is `ERR_ALLERGEN_SEGREGATION_VIOLATION`
    rather than `ERR_LABOR_BUDGET_EXCEEDED`.

    Design: Difficulty/priority_pair_validation_conflict/allergen_safety_check_outranks_labor_budget_check
    """
    setup = setup_planned_day(bake_day_overrides={"labor_budget_minutes": 30})
    nut_bar = provision_product(
        create_tree_nut_product_payload(setup["department"]["id"])
    )
    dedicated = provision_oven(
        create_nut_free_oven_payload(setup["department"]["id"])
    )

    response = _create_run(
        setup["bake_day"]["id"],
        nut_bar["id"],
        rack_count=4,
        oven_id=dedicated["id"],
        deck_index=0,
        bake_start_utc=SHIFT_START_INSTANT,
    )
    validate_error(response, "ERR_ALLERGEN_SEGREGATION_VIOLATION", 422)

    day = read_bake_day(setup["bake_day"]["id"])
    assert_minutes(day["planned_labor_minutes"], 0.00, "planned_labor_minutes")
    _, meta = list_runs_for_day(day["id"])
    assert meta["total_count"] == 1, "Only the zero-labor filler batch exists"


def test_the_labor_budget_surfaces_once_the_equipment_is_allergen_legal():
    """On shared equipment the walnut bar is legal, so the budget check bites.

    PRD §2.10 band 13 evaluates "rack capacity per deck
    (`ERR_OVEN_RACK_CAPACITY_EXCEEDED`), the day's labor budget
    (`ERR_LABOR_BUDGET_EXCEEDED`)" last of all.  A shared oven accepts a product
    that merely carries `TREE_NUT` and makes no nut-free claim, leaving the
    34.00 planned minutes against a 30-minute budget as the only fault.

    Design: Difficulty/priority_pair_validation_conflict/allergen_safety_check_outranks_labor_budget_check
    """
    setup = setup_planned_day(bake_day_overrides={"labor_budget_minutes": 30})
    nut_bar = provision_product(
        create_tree_nut_product_payload(setup["department"]["id"])
    )

    response = _create_run(
        setup["bake_day"]["id"],
        nut_bar["id"],
        rack_count=4,
        oven_id=setup["oven"]["id"],
        deck_index=0,
        bake_start_utc=SHIFT_START_INSTANT,
    )
    validate_error(response, "ERR_LABOR_BUDGET_EXCEEDED", 422)

    affordable = validate_success(
        _create_run(
            setup["bake_day"]["id"],
            nut_bar["id"],
            rack_count=3,
            oven_id=setup["oven"]["id"],
            deck_index=0,
            bake_start_utc=SHIFT_START_INSTANT,
        ),
        201,
    )
    assert_minutes(affordable["planned_labor_minutes"], 28.00, "planned_labor_minutes")

    day = read_bake_day(setup["bake_day"]["id"])
    assert_minutes(day["planned_labor_minutes"], 28.00, "day planned_labor_minutes")


def test_a_locked_plan_is_reported_ahead_of_the_allergen_violation():
    """Own-entity state band 7 fires before safety band 9.

    PRD §2.10 band 7: "the day's posture permits a plan-shaping write
    (`ERR_BAKE_DAY_PLAN_LOCKED`)", and band 9 states it "is itself outranked by
    every state check above it".  A nut-free-claiming loaf aimed at shared
    equipment on a locked day breaks both rules, so the posture wins.

    Design: Difficulty/priority_pair_validation_conflict/locked_plan_state_check_outranks_allergen_safety_check
    """
    setup = setup_planned_day()
    gluten_free = provision_product(
        create_nut_free_product_payload(setup["department"]["id"])
    )
    locked = lock_day(setup["bake_day"], setup["department"])
    assert locked["plan_posture"] == "LOCKED"

    response = _create_run(
        locked["id"],
        gluten_free["id"],
        rack_count=2,
        oven_id=setup["oven"]["id"],
        deck_index=0,
        bake_start_utc=SHIFT_START_INSTANT,
    )
    validate_error(response, "ERR_BAKE_DAY_PLAN_LOCKED", 409)

    day = read_bake_day(locked["id"])
    assert_minutes(day["planned_labor_minutes"], 0.00, "planned_labor_minutes")
    _, meta = list_runs_for_day(day["id"])
    assert meta["total_count"] == 1, "No run may be created on a locked day"


def test_the_allergen_violation_surfaces_on_a_day_still_open_for_planning():
    """With the posture check satisfied, shared equipment refuses the claim.

    PRD §2.8: "an oven whose `allergen_mode` is `SHARED` refuses any product
    whose `allergen_free_claim` is true — a product merchandised as nut-free may
    only be produced on dedicated equipment."  On a `PLANNED` day the posture check
    passes, so `ERR_ALLERGEN_SEGREGATION_VIOLATION` is the first failing check.

    Design: Difficulty/priority_pair_validation_conflict/locked_plan_state_check_outranks_allergen_safety_check
    """
    setup = setup_planned_day()
    gluten_free = provision_product(
        create_nut_free_product_payload(setup["department"]["id"])
    )

    response = _create_run(
        setup["bake_day"]["id"],
        gluten_free["id"],
        rack_count=2,
        oven_id=setup["oven"]["id"],
        deck_index=0,
        bake_start_utc=SHIFT_START_INSTANT,
    )
    validate_error(response, "ERR_ALLERGEN_SEGREGATION_VIOLATION", 422)

    dedicated = provision_oven(
        create_nut_free_oven_payload(setup["department"]["id"])
    )
    accepted = validate_success(
        _create_run(
            setup["bake_day"]["id"],
            gluten_free["id"],
            rack_count=2,
            oven_id=dedicated["id"],
            deck_index=0,
            bake_start_utc=SHIFT_START_INSTANT,
        ),
        201,
    )
    assert accepted["oven_id"] == dedicated["id"]
    assert_minutes(accepted["planned_labor_minutes"], 27.00, "planned_labor_minutes")


def test_a_new_manual_run_opens_scheduled_and_pending_with_a_derived_schedule():
    """Creation fixes both status dimensions and the whole derived schedule.

    PRD §3.4: "`bake_end_utc` is `bake_start_utc` plus the product's
    `bake_minutes`, and is null for a `THAW_AND_SERVE` run that never enters an
    oven. `ready_utc` is `bake_end_utc` plus the product's `cool_minutes` for a
    `SCRATCH` or `PAR_BAKED` run".  Twenty bake and fifteen cool minutes from
    04:00Z give 04:20Z and 04:35Z, and ten shelf-life hours give 14:35Z.

    Design: Corner/state_machines/a_new_manual_run_starts_in_scheduled_and_pending_with_a_derived_schedule
    """
    setup = setup_planned_day()
    run = validate_success(
        _create_run(
            setup["bake_day"]["id"],
            setup["croissant"]["id"],
            rack_count=2,
            oven_id=setup["oven"]["id"],
            deck_index=0,
            bake_start_utc=SHIFT_START_INSTANT,
        ),
        201,
    )

    assert_production_run(run)
    assert run["origin"] == "MANUAL"
    assert run["execution_status"] == "SCHEDULED"
    assert run["disposition_status"] == "PENDING"
    assert run["version"] == 1
    assert run["planned_units"] == 80
    assert_minutes(run["planned_labor_minutes"], 27.00, "planned_labor_minutes")
    assert_cents(run["ingredient_cost_cents"], 600, "ingredient_cost_cents")
    assert_instant(run["bake_end_utc"], "2026-08-12T04:20:00Z", "bake_end_utc")
    assert_instant(run["ready_utc"], "2026-08-12T04:35:00Z", "ready_utc")
    assert_instant(run["expires_utc"], "2026-08-12T14:35:00Z", "expires_utc")
    assert_null(run["proof_start_utc"], "par-baked proof_start_utc")
    assert_null(run["actual_units"], "actual_units")
    assert_null(run["final_labor_minutes"], "final_labor_minutes")
    assert_null(run["executed_by_user_id"], "executed_by_user_id")
    assert_null(run["markdown_unit_price_cents"], "markdown_unit_price_cents")
    assert_null(run["cancelled_reason"], "cancelled_reason")


def test_deck_index_validity_is_read_from_the_referenced_ovens_deck_count():
    """Each oven's own deck count fixes the legal deck range.

    PRD §3.4: "when an oven is named the deck must lie between zero and one less
    than that oven's `deck_count`, inclusive — anything negative or at or beyond
    the deck count is rejected with `ERR_DECK_INDEX_OUT_OF_RANGE`."  Deck 1 is
    illegal on the one-deck oven and perfectly legal on the two-deck oven.

    Design: Corner/validations/deck_index_validity_is_read_from_the_referenced_ovens_deck_count
    """
    setup = setup_planned_day()
    single_deck = provision_oven(
        create_unbuffered_oven_payload(setup["department"]["id"])
    )

    out_of_range = _create_run(
        setup["bake_day"]["id"],
        setup["croissant"]["id"],
        rack_count=2,
        oven_id=single_deck["id"],
        deck_index=1,
        bake_start_utc=SHIFT_START_INSTANT,
    )
    validate_error(out_of_range, "ERR_DECK_INDEX_OUT_OF_RANGE", 422)

    on_the_single_deck = validate_success(
        _create_run(
            setup["bake_day"]["id"],
            setup["croissant"]["id"],
            rack_count=2,
            oven_id=single_deck["id"],
            deck_index=0,
            bake_start_utc=SHIFT_START_INSTANT,
        ),
        201,
    )
    assert on_the_single_deck["deck_index"] == 0

    on_the_second_deck = validate_success(
        _create_run(
            setup["bake_day"]["id"],
            setup["croissant"]["id"],
            rack_count=2,
            oven_id=setup["oven"]["id"],
            deck_index=1,
            bake_start_utc=SHIFT_START_INSTANT,
        ),
        201,
    )
    assert on_the_second_deck["deck_index"] == 1
    assert on_the_second_deck["oven_id"] == setup["oven"]["id"]


def test_oven_assignment_is_required_or_forbidden_by_the_products_method():
    """The two equipment rules are symmetric and share one error id.

    PRD §3.4: "An `oven_id` is mandatory for a `SCRATCH` or `PAR_BAKED` run and
    must be omitted for a `THAW_AND_SERVE` run; getting either direction wrong is
    rejected with `ERR_OVEN_METHOD_MISMATCH`."  A thaw-and-serve batch is ready
    at the logical clock instant it was created and carries no oven fields at all.

    Design: Corner/validations/oven_assignment_is_required_or_forbidden_according_to_the_products_method
    """
    setup = setup_planned_day()

    missing_oven = _create_run(
        setup["bake_day"]["id"],
        setup["croissant"]["id"],
        rack_count=2,
        bake_start_utc=SHIFT_START_INSTANT,
    )
    validate_error(missing_oven, "ERR_OVEN_METHOD_MISMATCH", 422)

    forbidden_oven = _create_run(
        setup["bake_day"]["id"],
        setup["filler"]["id"],
        rack_count=2,
        oven_id=setup["oven"]["id"],
        deck_index=0,
    )
    validate_error(forbidden_oven, "ERR_OVEN_METHOD_MISMATCH", 422)

    thaw_run = validate_success(
        _create_run(setup["bake_day"]["id"], setup["filler"]["id"], rack_count=2),
        201,
    )
    assert_null(thaw_run["oven_id"], "thaw-and-serve oven_id")
    assert_null(thaw_run["deck_index"], "thaw-and-serve deck_index")
    assert_null(thaw_run["bake_start_utc"], "thaw-and-serve bake_start_utc")
    assert_null(thaw_run["bake_end_utc"], "thaw-and-serve bake_end_utc")
    assert_null(thaw_run["proof_start_utc"], "thaw-and-serve proof_start_utc")
    assert_instant(thaw_run["ready_utc"], setup["clock"], "ready_utc")
    assert_instant(thaw_run["expires_utc"], "2026-08-11T04:00:00Z", "expires_utc")
    assert thaw_run["shared_equipment_label_tags"] == [], (
        "A run with no oven carries an empty shared-equipment label"
    )


def test_a_run_whose_cooling_tail_overruns_the_oven_shift_is_rejected():
    """Both temporal bounds are measured against the day's shift window.

    PRD §3.4: "`proof_start_utc` must be at or after `oven_shift_start_utc`, and
    `bake_start_utc` plus the product's `bake_minutes` plus its `cool_minutes`
    must be at or before `oven_shift_end_utc`. A violation of either is reported
    as `ERR_OVEN_SHIFT_WINDOW_VIOLATION`."  On a shift closing at 06:00Z a
    05:40Z bake cools until 06:15Z and is refused, while 05:25Z lands exactly on
    the edge and passes.

    Design: Corner/validations/a_run_whose_cooling_tail_overruns_the_oven_shift_window_is_rejected
    """
    setup = setup_planned_day(
        bake_day_overrides={"oven_shift_end_utc": "2026-08-12T06:00:00Z"}
    )

    tail_overruns = _create_run(
        setup["bake_day"]["id"],
        setup["croissant"]["id"],
        rack_count=2,
        oven_id=setup["oven"]["id"],
        deck_index=0,
        bake_start_utc="2026-08-12T05:40:00Z",
    )
    validate_error(tail_overruns, "ERR_OVEN_SHIFT_WINDOW_VIOLATION", 422)

    proof_starts_too_early = _create_run(
        setup["bake_day"]["id"],
        setup["roll"]["id"],
        rack_count=2,
        oven_id=setup["oven"]["id"],
        deck_index=1,
        proof_start_utc="2026-08-12T03:45:00Z",
        bake_start_utc="2026-08-12T04:30:00Z",
    )
    validate_error(proof_starts_too_early, "ERR_OVEN_SHIFT_WINDOW_VIOLATION", 422)

    exactly_on_the_edge = validate_success(
        _create_run(
            setup["bake_day"]["id"],
            setup["croissant"]["id"],
            rack_count=2,
            oven_id=setup["oven"]["id"],
            deck_index=0,
            bake_start_utc="2026-08-12T05:25:00Z",
        ),
        201,
    )
    assert_instant(exactly_on_the_edge["bake_end_utc"], "2026-08-12T05:45:00Z", "bake_end_utc")
    assert_instant(exactly_on_the_edge["ready_utc"], "2026-08-12T06:00:00Z", "ready_utc")

    _, meta = list_runs_for_day(setup["bake_day"]["id"])
    assert meta["total_count"] == 2, "Only the filler and the edge batch were created"


def test_run_read_exposes_every_derived_schedule_labor_and_cost_field():
    """A single run read carries the whole derived picture, for any role.

    PRD §2.1: "Every role may read every collection and every single resource
    exposed by the API."  A `Decorator` who never touches production may
    therefore read a bread batch and see its schedule, its planned labor and its
    ingredient cost.

    Design: Corner/endpoints/run_read_exposes_every_derived_schedule_labor_and_cost_field
    """
    setup = setup_planned_day()
    created = schedule_par_baked_run(setup, rack_count=2, deck_index=0)

    run = validate_success(
        api_client.get_production_run(created["id"], DECORATOR), 200
    )
    assert_production_run(run)
    assert run["id"] == created["id"]
    assert run["bake_day_id"] == setup["bake_day"]["id"]
    assert run["product_id"] == setup["croissant"]["id"]
    assert run["oven_id"] == setup["oven"]["id"]
    assert run["deck_index"] == 0
    assert run["rack_count"] == 2
    assert run["planned_units"] == 80
    assert_minutes(run["planned_labor_minutes"], 27.00, "planned_labor_minutes")
    assert_cents(run["ingredient_cost_cents"], 600, "ingredient_cost_cents")
    assert_instant(run["bake_start_utc"], SHIFT_START_INSTANT, "bake_start_utc")
    assert_instant(run["bake_end_utc"], "2026-08-12T04:20:00Z", "bake_end_utc")
    assert_instant(run["ready_utc"], "2026-08-12T04:35:00Z", "ready_utc")
    assert_instant(run["expires_utc"], "2026-08-12T14:35:00Z", "expires_utc")
    assert run["shared_equipment_label_tags"] == ["WHEAT"]

    day = read_bake_day(setup["bake_day"]["id"])
    assert day["planned_units_total"] == 81
    assert_minutes(day["planned_labor_minutes"], 27.00, "day planned_labor_minutes")


def test_run_listing_composes_oven_and_status_filters_with_offset_paging():
    """Filters intersect, and paging reports the filtered total.

    PRD §3.4: "Runs are readable one at a time, and listable with filters on
    `bake_day_id`, `product_id`, `oven_id`, `execution_status` and
    `disposition_status`; that list is the only channel through which
    plan-generated runs can be discovered."  The oven filter hides the
    thaw-and-serve batch that has no oven at all.

    Design: Corner/endpoints/run_listing_composes_oven_and_status_filters_with_offset_paging
    """
    setup = setup_planned_day()
    oven_id = setup["oven"]["id"]
    loaded = schedule_par_baked_run(setup, rack_count=2, deck_index=0)
    still_scheduled = schedule_par_baked_run(setup, rack_count=2, deck_index=1)
    drive_run_to_baking(loaded, "PAR_BAKED")

    on_the_oven, meta = validate_paginated(
        api_client.list_production_runs(
            REGIONAL_ADMIN,
            params={"bake_day_id": setup["bake_day"]["id"], "oven_id": oven_id},
        )
    )
    assert meta["total_count"] == 2, "The oven filter excludes the ovenless filler batch"
    assert {row["id"] for row in on_the_oven} == {loaded["id"], still_scheduled["id"]}

    baking, baking_meta = validate_paginated(
        api_client.list_production_runs(
            REGIONAL_ADMIN,
            params={
                "bake_day_id": setup["bake_day"]["id"],
                "oven_id": oven_id,
                "execution_status": "BAKING",
            },
        )
    )
    assert baking_meta["total_count"] == 1
    assert baking[0]["id"] == loaded["id"]

    scheduled, scheduled_meta = validate_paginated(
        api_client.list_production_runs(
            REGIONAL_ADMIN,
            params={
                "bake_day_id": setup["bake_day"]["id"],
                "oven_id": oven_id,
                "execution_status": "SCHEDULED",
            },
        )
    )
    assert scheduled_meta["total_count"] == 1
    assert scheduled[0]["id"] == still_scheduled["id"]

    second_page, page_meta = validate_paginated(
        api_client.list_production_runs(
            REGIONAL_ADMIN,
            params={
                "bake_day_id": setup["bake_day"]["id"],
                "oven_id": oven_id,
                "limit": 1,
                "offset": 1,
            },
        )
    )
    assert len(second_page) == 1
    assert page_meta["total_count"] == 2
    assert page_meta["limit"] == 1
    assert page_meta["offset"] == 1
    assert page_meta["has_more"] is False
