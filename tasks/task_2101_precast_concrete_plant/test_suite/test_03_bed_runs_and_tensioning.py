"""Bed occupancy, the strand tensioning arithmetic and its compensating abort."""

from test_helpers import (
    ApiErrorId,
    assert_bed_run,
    assert_decimal,
    assert_untensioned_run,
    assert_unallocated_run,
    DEVIATION_C40_PCT,
    DEVIATION_C60_PCT,
    JACK_FORCE_C40_KIPS,
    JACK_FORCE_C60_KIPS,
    THEORETICAL_ELONGATION_C40_IN,
    THEORETICAL_ELONGATION_C60_IN,
    TEST_USERS,
    add_bed_and_run,
    create_bed_run,
    create_bed_run_payload,
    create_high_performance_mix_payload,
    create_qualified_mix,
    read_bed_run,
    read_casting_bed,
    read_piece,
    read_project,
    setup_plant,
    setup_production_line,
    tension_payload,
    tension_run,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["plant_admin_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]


def test_new_bed_run_starts_scheduled_with_null_tension_fields(api):
    """PRD §3.3: "The new run starts in `SCHEDULED` with `piece_count` 0, with
    `blocked_reason`, `strand_count`, `strand_diameter_in`,
    `measured_elongation_in`, `theoretical_elongation_in`,
    `elongation_deviation_pct`, `computed_jacking_force_kips`, `cast_at` and
    `released_at` all null, and with all eight of its cost fields null."
    PRD §3.3: "A new bed's `committed_strand_force_kips` initialises to 0.00 and
    its `cumulative_cycle_count` to 0."

    Design: Corner/state_machines/bed_run_starts_in_scheduled_with_null_tension_fields
    """
    ctx = setup_plant()

    response = api.create_bed_run(
        create_bed_run_payload(ctx["bed"]["id"], ctx["mix"]["id"]), SUPERVISOR
    )
    run = validate_success(response, 201)

    assert_bed_run(run)
    assert run["status"] == "SCHEDULED"
    assert run["piece_count"] == 0
    assert run["blocked_reason"] is None
    assert run["cast_at"] is None
    assert run["released_at"] is None
    assert_untensioned_run(run)
    assert_unallocated_run(run)

    bed = read_casting_bed(ctx["bed"]["id"])
    assert bed["status"] == "AVAILABLE"
    assert bed["committed_strand_force_kips"] == 0


def test_overlapping_run_within_turnaround_buffer_is_rejected(api):
    """PRD §3.3: "Occupancy is then tested: a run's true footprint on the bed
    runs from its `scheduled_start` up to its `scheduled_end` plus that bed's
    `turnaround_buffer_hours`, and a new run is rejected with `ERR_BED_OCCUPIED`
    when that footprint intersects the footprint of any other run on the same
    bed whose status is not yet `STRIPPED`."

    Design: Difficulty/resource_temporal_overlap/bed_occupancy_pairwise_exclusion_with_turnaround_buffer
    """
    ctx = setup_plant()
    first = create_bed_run(
        ctx["bed"]["id"],
        ctx["mix"]["id"],
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-04T06:00:00Z",
    )

    # The bed's 6 h turnaround buffer pushes its footprint out to 12:00 Aug 4.
    response = api.create_bed_run(
        create_bed_run_payload(
            ctx["bed"]["id"],
            ctx["mix"]["id"],
            scheduled_start="2026-08-04T11:00:00Z",
            scheduled_end="2026-08-05T06:00:00Z",
        ),
        SUPERVISOR,
    )
    validate_error(response, ApiErrorId.ERR_BED_OCCUPIED.value, 409)

    rows, meta = validate_paginated(api.list_bed_runs(SUPERVISOR, {"bed_id": ctx["bed"]["id"]}))
    assert meta["total_count"] == 1, f"the rejected run must not persist, got {meta['total_count']}"
    assert [r["id"] for r in rows] == [first["id"]]


def test_run_starting_exactly_at_the_buffer_edge_is_admitted(api):
    """PRD §3.3: "Occupancy is then tested: a run's true footprint on the bed
    runs from its `scheduled_start` up to its `scheduled_end` plus that bed's
    `turnaround_buffer_hours`, and a new run is rejected with `ERR_BED_OCCUPIED`
    when that footprint intersects the footprint of any other run on the same
    bed whose status is not yet `STRIPPED`."
    PRD §3.3: "and the window `scheduled_start` (inclusive) and `scheduled_end`
    (exclusive), both ISO 8601 UTC instants with the end strictly after the
    start."

    Design: Difficulty/resource_temporal_overlap/bed_occupancy_pairwise_exclusion_with_turnaround_buffer
    """
    ctx = setup_plant()
    first = create_bed_run(
        ctx["bed"]["id"],
        ctx["mix"]["id"],
        scheduled_start="2026-08-03T06:00:00Z",
        scheduled_end="2026-08-04T06:00:00Z",
    )

    response = api.create_bed_run(
        create_bed_run_payload(
            ctx["bed"]["id"],
            ctx["mix"]["id"],
            scheduled_start="2026-08-04T12:00:00Z",
            scheduled_end="2026-08-05T06:00:00Z",
        ),
        SUPERVISOR,
    )
    second = validate_success(response, 201)

    assert second["status"] == "SCHEDULED"
    assert second["scheduled_start"].startswith("2026-08-04T12:00:00"), (
        "the run starting exactly at the end of the buffered footprint is admitted"
    )
    rows, meta = validate_paginated(api.list_bed_runs(SUPERVISOR, {"bed_id": ctx["bed"]["id"]}))
    assert meta["total_count"] == 2
    assert {r["id"] for r in rows} == {first["id"], second["id"]}


def test_jacking_force_floor_binds_for_a_c40_mix(api):
    """PRD §3.3: "The base force is scaled by one plus that combined percentage
    expressed as a fraction, and the required force per strand is the greater of
    that scaled figure and the floor of 32.0 kips per strand — a floor high
    enough that on some combinations it swallows the strength-class contribution
    entirely."
    PRD §3.3: "Multiplying the required force per strand by `strand_count` and
    rounding half up to two decimal places gives
    `computed_jacking_force_kips`."
    PRD §3.3: "`theoretical_elongation_in` is obtained by dividing
    `computed_jacking_force_kips` by `strand_count` to recover the per-strand
    force, multiplying by the bed's `length_ft` and then by 12 to convert that
    length to inches, dividing by the product of the strand's nominal area and
    the strand modulus of 28500.0 ksi, and rounding half up to three decimal
    places."

    Design: Difficulty/combinatorial_formula/jacking_force_floor_overrides_strength_class_adjustment
    """
    ctx = setup_plant()
    run = create_bed_run(ctx["bed"]["id"], ctx["mix"]["id"])

    tensioned = validate_success(
        api.tension_bed_run(run["id"], tension_payload(), SUPERVISOR)
    )

    assert_decimal(
        tensioned["computed_jacking_force_kips"],
        JACK_FORCE_C40_KIPS,
        2,
        "bed_run.computed_jacking_force_kips",
    )
    assert tensioned["computed_jacking_force_kips"] != 762.17, (
        "762.17 kips is the seating-loss expression before the 32.0 kip floor binds"
    )
    assert_decimal(
        tensioned["theoretical_elongation_in"],
        THEORETICAL_ELONGATION_C40_IN,
        3,
        "bed_run.theoretical_elongation_in",
    )
    assert_decimal(
        tensioned["elongation_deviation_pct"],
        DEVIATION_C40_PCT,
        2,
        "bed_run.elongation_deviation_pct",
    )
    assert tensioned["status"] == "TENSIONED"

    bed = read_casting_bed(ctx["bed"]["id"])
    assert_decimal(
        bed["committed_strand_force_kips"],
        JACK_FORCE_C40_KIPS,
        2,
        "casting_bed.committed_strand_force_kips",
    )
    assert bed["status"] == "OCCUPIED"


def test_jacking_force_takes_the_strength_class_adjustment_for_a_c60_mix(api):
    """PRD §3.3: "A single adjustment percentage is then formed by adding two
    contributions: the seating loss of the bed's form family, which is 2.5
    percent for `LONG_LINE_PRESTRESS`, 4.5 percent for `SELF_STRESSING_FORM` and
    0.0 percent for `FLAT_BED_RC`; and the temperature adjustment of the mix's
    strength class, which is 0.0 percent for `C40` and for `C50` and 1.5 percent
    for `C60` and for `C70`."
    PRD §3.3: "`elongation_deviation_pct` is the difference between
    `measured_elongation_in` and `theoretical_elongation_in`, divided by
    `theoretical_elongation_in`, multiplied by 100 and rounded half up to two
    decimal places; it is signed, so a short pull reads negative."

    Design: Difficulty/combinatorial_formula/jacking_force_floor_overrides_strength_class_adjustment
    """
    ctx = setup_plant()
    high_performance = create_qualified_mix(**create_high_performance_mix_payload())
    bed_two, run_c60 = add_bed_and_run(ctx, bed_code="B2", mix_design_id=high_performance["id"])
    run_c40 = create_bed_run(ctx["bed"]["id"], ctx["mix"]["id"])

    tension_run(run_c40["id"])
    tensioned = validate_success(
        api.tension_bed_run(run_c60["id"], tension_payload(), SUPERVISOR)
    )

    assert_decimal(
        tensioned["computed_jacking_force_kips"],
        JACK_FORCE_C60_KIPS,
        2,
        "bed_run.computed_jacking_force_kips",
    )
    assert_decimal(
        tensioned["theoretical_elongation_in"],
        THEORETICAL_ELONGATION_C60_IN,
        3,
        "bed_run.theoretical_elongation_in",
    )
    assert_decimal(
        tensioned["elongation_deviation_pct"],
        DEVIATION_C60_PCT,
        2,
        "bed_run.elongation_deviation_pct",
    )
    assert tensioned["status"] == "TENSIONED"
    assert read_bed_run(run_c40["id"])["status"] == "TENSIONED"
    assert_decimal(
        read_casting_bed(bed_two["id"])["committed_strand_force_kips"],
        JACK_FORCE_C60_KIPS,
        2,
        "casting_bed.committed_strand_force_kips",
    )


def test_tension_at_exactly_the_abutment_rating_is_admitted(api):
    """PRD §3.3: "If `computed_jacking_force_kips` exceeds the bed's
    `max_strand_force_kips`, the tensioning is rejected with
    `ERR_BED_STRAND_CAPACITY_EXCEEDED`."
    PRD §3.3: "When both gates are satisfied, the run moves `SCHEDULED →
    TENSIONED`, the three computed figures are written on it, the bed moves
    `AVAILABLE → OCCUPIED`, and the bed's `committed_strand_force_kips`
    increases by this run's `computed_jacking_force_kips`."

    Design: Corner/calculations/bed_strand_capacity_boundary_equal_admitted_one_hundredth_over_rejected
    """
    ctx = setup_plant(bed_overrides={"bed_code": "BEQ", "max_strand_force_kips": 768.00})
    bed_low, run_low = add_bed_and_run(
        ctx, bed_code="BLO", bed_overrides={"max_strand_force_kips": 767.99}
    )
    run_equal = create_bed_run(ctx["bed"]["id"], ctx["mix"]["id"])

    admitted = validate_success(
        api.tension_bed_run(run_equal["id"], tension_payload(), SUPERVISOR)
    )
    assert admitted["status"] == "TENSIONED"
    assert_decimal(
        admitted["computed_jacking_force_kips"],
        JACK_FORCE_C40_KIPS,
        2,
        "bed_run.computed_jacking_force_kips",
    )
    equal_bed = read_casting_bed(ctx["bed"]["id"])
    assert_decimal(
        equal_bed["committed_strand_force_kips"],
        JACK_FORCE_C40_KIPS,
        2,
        "casting_bed.committed_strand_force_kips",
    )
    assert equal_bed["status"] == "OCCUPIED"

    rejected = api.tension_bed_run(run_low["id"], tension_payload(), SUPERVISOR)
    validate_error(rejected, ApiErrorId.ERR_BED_STRAND_CAPACITY_EXCEEDED.value, 422)

    low_run = read_bed_run(run_low["id"])
    assert low_run["status"] == "SCHEDULED"
    assert low_run["computed_jacking_force_kips"] is None
    low_bed = read_casting_bed(bed_low["id"])
    assert low_bed["committed_strand_force_kips"] == 0
    assert low_bed["status"] == "AVAILABLE"


def test_elongation_outside_tolerance_rejects_the_pull(api):
    """PRD §3.3: "If the absolute value of `elongation_deviation_pct` exceeds the
    elongation tolerance of 5.0 percent, the tensioning is rejected with
    `ERR_ELONGATION_OUT_OF_TOLERANCE`; a deviation of exactly 5.0 percent in
    either direction is within tolerance and passes."

    Design: Corner/calculations/elongation_deviation_beyond_tolerance_rejects_tension
    """
    ctx = setup_plant()
    run = create_bed_run(ctx["bed"]["id"], ctx["mix"]["id"])

    rejected = api.tension_bed_run(
        run["id"], tension_payload(measured_elongation_in=38.000), SUPERVISOR
    )
    validate_error(rejected, ApiErrorId.ERR_ELONGATION_OUT_OF_TOLERANCE.value, 422)

    after_reject = read_bed_run(run["id"])
    assert after_reject["status"] == "SCHEDULED"
    assert after_reject["measured_elongation_in"] is None
    assert read_casting_bed(ctx["bed"]["id"])["status"] == "AVAILABLE"

    accepted = validate_success(api.tension_bed_run(run["id"], tension_payload(), SUPERVISOR))
    assert accepted["status"] == "TENSIONED"
    assert_decimal(
        accepted["theoretical_elongation_in"],
        THEORETICAL_ELONGATION_C40_IN,
        3,
        "bed_run.theoretical_elongation_in",
    )
    assert_decimal(
        accepted["elongation_deviation_pct"], DEVIATION_C40_PCT, 2, "bed_run.elongation_deviation_pct"
    )
    assert_decimal(accepted["measured_elongation_in"], 35.500, 3, "bed_run.measured_elongation_in")


def test_tensioning_a_down_bed_is_refused(api):
    """PRD §3.3: "`DOWN` is absorbing: no transition leaves it, and any attempt
    to tension a run on a bed that is `DOWN` is refused with
    `ERR_PLANT_RESOURCE_UNAVAILABLE`."

    Design: Corner/validations/tensioning_a_bed_marked_down_returns_plant_resource_unavailable
    """
    ctx = setup_plant(bed_overrides={"bed_code": "BDN", "status": "DOWN"})
    run = create_bed_run(ctx["bed"]["id"], ctx["mix"]["id"])

    response = api.tension_bed_run(run["id"], tension_payload(), SUPERVISOR)
    validate_error(response, ApiErrorId.ERR_PLANT_RESOURCE_UNAVAILABLE.value, 409)

    bed = read_casting_bed(ctx["bed"]["id"])
    assert bed["status"] == "DOWN", "DOWN is absorbing"
    assert bed["committed_strand_force_kips"] == 0
    reread = read_bed_run(run["id"])
    assert reread["status"] == "SCHEDULED"
    assert reread["computed_jacking_force_kips"] is None


def test_abort_returns_committed_force_to_the_pre_tension_baseline(api):
    """PRD §3.3: "The bed's `committed_strand_force_kips` decreases by exactly
    the `computed_jacking_force_kips` this run had contributed, restoring the
    bed's committed force to precisely its pre-tension value, and the bed moves
    `OCCUPIED → AVAILABLE`."
    PRD §2.11: "Aborting a tensioning must leave the casting bed's
    `committed_strand_force_kips` at precisely the value it held before the
    tensioning."

    Design: Difficulty/compensating_invariant/bed_committed_strand_force_returns_to_baseline_after_abort
    """
    ctx = setup_plant()
    run = create_bed_run(ctx["bed"]["id"], ctx["mix"]["id"])
    baseline = read_casting_bed(ctx["bed"]["id"])["committed_strand_force_kips"]
    assert baseline == 0

    tension_run(run["id"])
    midpoint = read_casting_bed(ctx["bed"]["id"])
    assert_decimal(
        midpoint["committed_strand_force_kips"],
        JACK_FORCE_C40_KIPS,
        2,
        "casting_bed.committed_strand_force_kips",
    )
    assert midpoint["status"] == "OCCUPIED"

    validate_success(
        api.abort_tensioning(run["id"], {"reason": "Chuck slip detected on strand 7"}, SUPERVISOR)
    )

    restored = read_casting_bed(ctx["bed"]["id"])
    assert restored["committed_strand_force_kips"] == baseline, (
        f"committed force must return to exactly {baseline}, got "
        f"{restored['committed_strand_force_kips']}"
    )
    assert restored["status"] == "AVAILABLE"
    assert restored["cumulative_cycle_count"] == 0, "an abort is not a completed casting cycle"


def test_abort_nulls_every_tensioning_field_and_returns_the_run_to_scheduled(api):
    """PRD §3.3: "Performed by the `ProductionSupervisor` with a free-text
    `reason`, it moves the run `TENSIONED → SCHEDULED`."
    PRD §3.3: "Six fields on the run are reset to null: `strand_count`,
    `strand_diameter_in`, `measured_elongation_in`, `theoretical_elongation_in`,
    `elongation_deviation_pct` and `computed_jacking_force_kips`."

    Design: Difficulty/compensating_invariant/bed_committed_strand_force_returns_to_baseline_after_abort
    """
    ctx = setup_plant()
    run = create_bed_run(ctx["bed"]["id"], ctx["mix"]["id"])
    tension_run(run["id"])

    aborted = validate_success(
        api.abort_tensioning(run["id"], {"reason": "Chuck slip detected on strand 7"}, SUPERVISOR)
    )

    assert aborted["status"] == "SCHEDULED"
    assert_untensioned_run(aborted)
    assert_untensioned_run(read_bed_run(run["id"]))


def test_casting_a_run_with_no_pieces_is_refused(api):
    """PRD §3.4: "and its `piece_count` must be at least 1 — pouring an empty bed
    is refused with `ERR_NO_PIECES_ASSIGNED`."
    PRD §3.4: "On success the run's `cast_at` is stamped from the logical clock
    and four effects follow."

    Design: Corner/state_machines/cast_without_assigned_pieces_returns_no_pieces_assigned
    """
    ctx = setup_production_line(stage="tensioned", piece_specs=[], with_cylinder_set=False,
                                with_curing_cycle=False)

    response = api.cast_bed_run(ctx["run"]["id"], SUPERVISOR)
    validate_error(response, ApiErrorId.ERR_NO_PIECES_ASSIGNED.value, 422)

    run = read_bed_run(ctx["run"]["id"])
    assert run["status"] == "TENSIONED"
    assert run["cast_at"] is None
    bed = read_casting_bed(ctx["bed"]["id"])
    assert bed["status"] == "OCCUPIED"
    assert_decimal(
        bed["committed_strand_force_kips"],
        JACK_FORCE_C40_KIPS,
        2,
        "casting_bed.committed_strand_force_kips",
    )


def test_strip_before_release_is_refused(api):
    """PRD §3.6: "The run moves `RELEASED → STRIPPED`, which is terminal; a strip
    issued from any other status is refused with `ERR_BED_RUN_INVALID_STATE`, as
    is any subsequent action on a run that has already reached `STRIPPED`."

    Design: Corner/state_machines/strip_before_release_returns_bed_run_invalid_state
    """
    ctx = setup_production_line(stage="tensioned", with_cylinder_set=False,
                                with_curing_cycle=False)

    response = api.strip_bed_run(ctx["run"]["id"], SUPERVISOR)
    validate_error(response, ApiErrorId.ERR_BED_RUN_INVALID_STATE.value, 409)

    run = read_bed_run(ctx["run"]["id"])
    assert run["total_cost_cents"] is None
    assert run["direct_subtotal_cents"] is None
    piece = read_piece(ctx["pieces"][0]["id"])
    assert piece["production_status"] == "SCHEDULED"
    assert piece["allocated_cost_cents"] is None
    assert read_project(ctx["project"]["id"])["committed_cost_cents"] == 0
