"""
The state machines: declared initial states, non-idempotent triggers, forking
transitions, quorum-guarded terminal states, derived compound transitions, and the
lock-outs that a terminal state imposes on everything downstream of it.
"""

from test_helpers import (
    AGRONOMIST_HEADERS,
    ANALYST_HEADERS,
    DIRECTOR_HEADERS,
    PLANNER_HEADERS,
    REGULATORY_HEADERS,
    SCIENTIST_HEADERS,
    AnalysisVariant,
    ApiErrorId,
    BackcrossStatus,
    CrossingBlockStatus,
    DecisionType,
    EntryStatus,
    OccupancyStatus,
    PipelineStage,
    PlantingStatus,
    ProgramStatus,
    SeriesStatus,
    StewardshipStatus,
    approx2,
    approx3,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_six_freshly_created_records_sit_in_their_declared_initial_states(api):
    """
    Nothing is created mid-flight: a line, a crossing block, a planting, a series,
    an entry and a nursery block each open on the state their own rule names.

    PRD 3.2: "A directly registered line has `origin_block_id` null, opens at
    `pipeline_stage` `NURSERY` with `stewardship_status` `NOT_REQUIRED`, sets
    `cumulative_seed_produced_g` to its opening `seed_inventory_g`, and increments
    the programme's `active_line_count`."
    PRD 3.2: "The block opens in `status` `PLANNED` with `realized_cross_count` at
    0 and `progeny_line_count` at 0."
    PRD 3.3: "The planting is created in `status` `SCHEDULED`; the server computes
    `occupancy_end_date` as the `expected_harvest_date` advanced by the block's
    `fallow_buffer_days` days, which is the exclusive end of the block's occupancy
    interval and therefore the first date on which the block may be re-sown."
    PRD 3.3: "It reads `AVAILABLE` unless the logical clock's calendar date falls
    inside the occupancy interval of a planting on this block whose `status` is
    `SCHEDULED`, `PLANTED`, `HARVESTED` or `FAILED`."
    PRD 3.5: "The series opens in `status` `PLANNING` with `entry_count` and
    `location_count` at 0 and all three cost fields — `plot_cost_subtotal_usd`,
    `management_fee_usd` and `total_trial_cost_usd` — null."
    PRD 3.5: "The entry is created in `status` `ENTERED` with `valid_rep_count` at
    0 and both `plot_mean_yield_kg` and `yield_kg_per_ha` null."

    Design: Corner/state_machines/every_machine_starts_in_its_declared_initial_state
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line = fixtures.create_line_a(api, program_id, objective_id)
    assert line["pipeline_stage"] == PipelineStage.NURSERY
    assert line["stewardship_status"] == StewardshipStatus.NOT_REQUIRED
    assert line["origin_block_id"] is None
    site = fixtures.create_site(api, site_code="IS1")

    block = fixtures.create_nursery_block(api, block_code="NB-IS1")
    assert block["occupancy_status"] == OccupancyStatus.AVAILABLE

    crossing_block = fixtures.create_crossing_block(
        api, program_id, block["id"], planned_cross_count=4
    )
    assert crossing_block["status"] == CrossingBlockStatus.PLANNED
    assert crossing_block["realized_cross_count"] == 0
    assert crossing_block["progeny_line_count"] == 0

    planting = fixtures.create_planting(
        api,
        block["id"],
        line["id"],
        sow_date="2026-10-05",
        expected_harvest_date="2027-02-10",
        plot_count=50,
    )
    assert planting["status"] == PlantingStatus.SCHEDULED
    # 2027-02-10 advanced by the block's 14 fallow days.
    assert planting["occupancy_end_date"] == "2027-02-24"

    series = fixtures.create_series(
        api, program_id, replication_count=3, min_locations=1
    )
    assert series["status"] == SeriesStatus.PLANNING
    assert series["entry_count"] == 0
    assert series["location_count"] == 0
    assert series["plot_cost_subtotal_usd"] is None
    assert series["management_fee_usd"] is None
    assert series["total_trial_cost_usd"] is None

    entry = fixtures.create_entry(
        api, series["id"], line["id"], site["id"], plot_count=9
    )
    assert entry["status"] == EntryStatus.ENTERED
    assert entry["valid_rep_count"] == 0
    assert entry["plot_mean_yield_kg"] is None
    assert entry["yield_kg_per_ha"] is None

    reread_series = validate_success(api.get_series(series["id"], AGRONOMIST_HEADERS))
    assert reread_series["entry_count"] == 1
    assert reread_series["location_count"] == 1
    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["status"] == ProgramStatus.ACTIVE
    # 50 nursery plots plus the 9-plot trial entry.
    assert program["committed_plot_count"] == 59

    # The clock decides occupancy, so it must be inside the crop leg to read OCCUPIED.
    validate_success(api.set_clock("2026-11-01T00:00:00Z", SCIENTIST_HEADERS))
    occupied = validate_success(api.get_nursery_block(block["id"], SCIENTIST_HEADERS))
    assert occupied["occupancy_status"] == OccupancyStatus.OCCUPIED


def _planted_planting_of_fifty_plots(api, block_code):
    """Line SX-1001 at generation 6 with a PLANTED 50-plot winter planting."""
    program_id, objective_id = fixtures.program_with_objective(api)
    line = fixtures.create_line_a(api, program_id, objective_id)
    block = fixtures.create_nursery_block(api, block_code=block_code)
    planting = fixtures.create_planting(
        api,
        block["id"],
        line["id"],
        sow_date="2026-10-05",
        expected_harvest_date="2027-02-10",
        plot_count=50,
    )
    validate_success(api.plant_planting(planting["id"], SCIENTIST_HEADERS))
    return {
        "program_id": program_id,
        "line_id": line["id"],
        "block_id": block["id"],
        "planting_id": planting["id"],
    }


def test_neither_the_plant_nor_the_harvest_trigger_is_idempotent(api):
    """
    Replaying either trigger from the state it already produced is a state
    conflict, and the seed credit and the generation advance each happen once.

    PRD 3.3: "Marking a scheduled planting as sown moves it `SCHEDULED → PLANTED`
    and re-derives the block's `occupancy_status`, which becomes `OCCUPIED`; the
    planting must be `SCHEDULED` and the line it advances must not be `DISCARDED`."
    PRD 3.3: "When `harvested_seed_g` is at least 250 grams — the minimum viable
    seed quantity for the next selfing cycle, so exactly 250 grams succeeds — the
    planting becomes `HARVESTED`, the line's `generation_number` rises by 1, its
    `nursery_cycles_completed` rises by 1, and the planting's
    `generation_advanced_to` records the new `generation_number`."

    Design: Corner/state_machines/nursery_planting_plant_from_planted_is_rejected
    """
    net = _planted_planting_of_fifty_plots(api, "NB-ID1")
    validate_error(
        api.plant_planting(net["planting_id"], SCIENTIST_HEADERS),
        ApiErrorId.PLANTING_INVALID_STATE,
        409,
    )

    harvested = validate_success(
        api.harvest_planting(
            net["planting_id"],
            factories.harvest_payload(actual_harvest_date="2027-02-12", harvested_seed_g=4000),
            SCIENTIST_HEADERS,
        )
    )
    assert harvested["status"] == PlantingStatus.HARVESTED
    validate_error(
        api.harvest_planting(
            net["planting_id"],
            factories.harvest_payload(actual_harvest_date="2027-02-12", harvested_seed_g=4000),
            SCIENTIST_HEADERS,
        ),
        ApiErrorId.PLANTING_INVALID_STATE,
        409,
    )

    line = validate_success(api.get_line(net["line_id"], SCIENTIST_HEADERS))
    # 500000 opening grams plus one 4000 g credit, not two.
    assert line["seed_inventory_g"] == 504000
    assert line["cumulative_seed_produced_g"] == 504000
    assert line["generation_number"] == 7
    assert line["nursery_cycles_completed"] == 1
    program = validate_success(api.get_program(net["program_id"], DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 0
    assert program["plot_budget_remaining"] == 5000


def test_a_harvest_one_gram_short_banks_the_seed_but_not_the_generation(api):
    """
    The fork at 250 g is asymmetric: 249 g still credits the ledger and still
    releases the ground, yet the generation and the cycle counter stand still.

    PRD 3.3: "Both branches bank the seed: `seed_inventory_g` and
    `cumulative_seed_produced_g` on the line each rise by `harvested_seed_g`, and
    the block's `occupancy_status` becomes `FALLOW`, and the programme's
    `committed_plot_count` falls by the planting's `plot_count` with
    `plot_budget_remaining` recomputed, because the planting has left the set of
    scheduled-or-planted commitments."
    PRD 3.3: "When `harvested_seed_g` is below 250 grams the planting becomes
    `FAILED` instead: the seed is still banked exactly as above, but
    `generation_advanced_to` stays null, `generation_number` is not incremented and
    `nursery_cycles_completed` is not incremented, so `advancement_readiness` cannot
    flip on this branch."

    Design: Corner/state_machines/nursery_harvest_below_min_seed_branches_to_failed_without_advancing
    """
    net = _planted_planting_of_fifty_plots(api, "NB-FL1")
    failed = validate_success(
        api.harvest_planting(
            net["planting_id"],
            factories.harvest_payload(actual_harvest_date="2027-02-12", harvested_seed_g=249),
            SCIENTIST_HEADERS,
        )
    )
    assert failed["status"] == PlantingStatus.FAILED
    assert failed["generation_advanced_to"] is None
    assert failed["harvested_seed_g"] == 249
    assert failed["actual_harvest_date"] == "2027-02-12"

    line = validate_success(api.get_line(net["line_id"], SCIENTIST_HEADERS))
    assert line["seed_inventory_g"] == 500249
    assert line["cumulative_seed_produced_g"] == 500249
    assert line["generation_number"] == 6
    assert line["nursery_cycles_completed"] == 0
    program = validate_success(api.get_program(net["program_id"], DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 0

    # The fallow leg runs from the expected harvest date to the occupancy end date.
    validate_success(api.set_clock("2027-02-15T00:00:00Z", SCIENTIST_HEADERS))
    block = validate_success(api.get_nursery_block(net["block_id"], SCIENTIST_HEADERS))
    assert block["occupancy_status"] == OccupancyStatus.FALLOW


def test_close_needs_every_harvested_line_decided_and_then_locks_the_series(api):
    """
    The quorum is cross-entity — one undecided line with harvested data blocks the
    sign-off — and once CLOSED the series refuses both further analyses and further
    entries, which is what makes it terminal rather than merely labelled.

    PRD 3.8: "A series may be closed only while it is `ANALYZED`, and only when
    every breeding line holding a `HARVESTED` entry in that series has a
    non-superseded advancement decision for it; a series with an undecided line, or
    one not yet `ANALYZED`, is refused with `ERR_SERIES_INVALID_STATE`."
    PRD 3.8: "Closure moves the series to `CLOSED` and releases nothing — the plots
    stayed in the ground — but from then on the series accepts no further entries,
    no further analyses and no other mutation."
    PRD 3.8: "First the line itself: `pipeline_stage` becomes `DISCARDED`, its
    `version` increments, and `stewardship_status` is frozen at whatever value it
    held."

    Design: Corner/state_machines/series_close_needs_a_decision_for_every_harvested_line_then_locks
    """
    net = fixtures.single_site_analyzed(api, site_overrides={"site_code": "CL1"})
    fixtures.record_decision(
        api,
        net.line_a_id,
        net.series_id,
        decision=DecisionType.HOLD,
        granted_plots=0,
        rationale="await quality panel",
    )

    validate_error(
        api.close_series(net.series_id, DIRECTOR_HEADERS),
        ApiErrorId.SERIES_INVALID_STATE,
        409,
    )
    still_open = validate_success(api.get_series(net.series_id, DIRECTOR_HEADERS))
    assert still_open["status"] == SeriesStatus.ANALYZED

    fixtures.record_decision(
        api,
        net.line_b_id,
        net.series_id,
        decision=DecisionType.DISCARD,
        granted_plots=0,
        rationale="SDS score 4 misses the spec",
    )
    closed = validate_success(api.close_series(net.series_id, DIRECTOR_HEADERS))
    assert closed["status"] == SeriesStatus.CLOSED

    validate_error(
        api.create_analysis(
            net.series_id,
            factories.analysis_payload(
                api.series_version(net.series_id, ANALYST_HEADERS),
                variant=AnalysisVariant.UNBALANCED_INCLUSIVE,
            ),
            ANALYST_HEADERS,
        ),
        ApiErrorId.SERIES_INVALID_STATE,
        409,
    )
    validate_error(
        api.create_entry(
            net.series_id,
            factories.entry_payload(net.line_a_id, net.site_id, plot_count=8),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.SERIES_INVALID_STATE,
        409,
    )

    line_b = validate_success(api.get_line(net.line_b_id, DIRECTOR_HEADERS))
    assert line_b["pipeline_stage"] == PipelineStage.DISCARDED
    program = validate_success(api.get_program(net.program_id, DIRECTOR_HEADERS))
    assert program["active_line_count"] == 1
    _rows, meta = validate_paginated(
        api.list_analyses(net.series_id, ANALYST_HEADERS)
    )
    assert meta["total_count"] == 1


def test_the_last_entry_to_leave_planted_bubbles_the_series_whichever_exit_it_takes(api):
    """
    The compound parent transition is driven by the aggregate of its children and
    fires on the last child out of PLANTED, so an invalidation triggers it just as a
    finalisation would while the invalidated entry stays outside every rollup.

    PRD 3.6: "After a finalisation, a withdrawal or an invalidation, the server
    re-evaluates the parent series: when the series is `PLANTED`, no entry of the
    series is left in `status` `PLANTED`, and at least one entry of the series has
    reached `HARVESTED`, the series auto-transitions `PLANTED → DATA_COMPLETE` and
    its `version` advances."
    PRD 3.6: "**Invalidation** applies to an entry that is `PLANTED` and whose plot
    data failed quality control: the agronomist again supplies a
    `withdrawal_reason`, the entry moves `PLANTED → INVALIDATED`, both
    `plot_mean_yield_kg` and `yield_kg_per_ha` are set back to null, the programme's
    `committed_plot_count` falls by the entry's `plot_count` exactly as on a
    withdrawal, and the site's peak, availability and posture are re-derived."
    PRD 3.6: "An invalidated entry is excluded from every analysis inclusion set."

    Design: Corner/state_machines/series_bubbles_to_data_complete_only_when_the_last_planted_entry_leaves
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line_a = fixtures.create_line(
        api,
        program_id,
        objective_id,
        designation="SX-1001",
        seed_inventory_g=500000,
        disease_resistance_scores={"RUST": 8, "SDS": 7},
        quality_trait_values={"PROTEIN": 13.4},
    )
    line_b = fixtures.create_line(
        api, program_id, objective_id, designation="SX-1002", seed_inventory_g=400000
    )
    site = fixtures.create_site(api, site_code="BB1")
    series = fixtures.create_series(
        api, program_id, replication_count=3, min_locations=1
    )
    entry_a = fixtures.create_entry(
        api, series["id"], line_a["id"], site["id"], plot_count=9
    )
    entry_b = fixtures.create_entry(
        api, series["id"], line_b["id"], site["id"], plot_count=9
    )
    fixtures.plant_series(api, series["id"])
    fixtures.record_yield_reps(api, entry_a["id"], [15.0, 15.0, 15.0])
    fixtures.record_yield_reps(api, entry_b["id"], [14.0, 14.0, 14.0])

    fixtures.finalize_entry(api, entry_a["id"])
    mid = validate_success(api.get_series(series["id"], AGRONOMIST_HEADERS))
    assert mid["status"] == SeriesStatus.PLANTED

    invalidated = validate_success(
        api.invalidate_entry(
            entry_b["id"],
            AGRONOMIST_HEADERS,
            {"withdrawal_reason": "QC_FAILURE"},
        )
    )
    assert invalidated["status"] == EntryStatus.INVALIDATED
    assert invalidated["withdrawal_reason"] == "QC_FAILURE"
    assert invalidated["plot_mean_yield_kg"] is None
    bubbled = validate_success(api.get_series(series["id"], AGRONOMIST_HEADERS))
    assert bubbled["status"] == SeriesStatus.DATA_COMPLETE

    site_after = validate_success(api.get_site(site["id"], AGRONOMIST_HEADERS))
    assert site_after["peak_committed_plot_count"] == 9
    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 9

    analysis = fixtures.run_analysis(api, series["id"])
    assert analysis["included_line_count"] == 1
    assert analysis["included_location_count"] == 1
    # 0.50*109.09 + 0.30*100.00 + 0.20*85.00, with no stage discount.
    assert validate_success(api.get_line(line_a["id"], DIRECTOR_HEADERS))[
        "advancement_index_provisional"
    ] == approx2(101.55)
    assert (
        validate_success(api.get_line(line_b["id"], DIRECTOR_HEADERS))[
            "advancement_index_provisional"
        ]
        is None
    )


def test_a_discarded_line_is_locked_out_of_every_creation_that_names_it(api):
    """
    DISCARDED is the terminal of the pipeline dimension, and the same code answers
    on all five creation surfaces that reference a line rather than a state error
    from the child entity.

    PRD 2.7: "**Line not discarded.** Every `BreedingLine` the mutation references
    has `pipeline_stage` other than `DISCARDED` — otherwise `ERR_LINE_DISCARDED`
    (409). This guards eight operations: nursery planting creation, marking a
    planting as sown, trial entry creation, stewardship agreement drafting,
    agreement submission, seed increase lot reservation, backcross project
    creation, and running a marker cycle."
    PRD 3.8: "First the line itself: `pipeline_stage` becomes `DISCARDED`, its
    `version` increments, and `stewardship_status` is frozen at whatever value it
    held."

    Design: Corner/state_machines/discarded_line_is_locked_out_of_every_downstream_creation
    """
    net = fixtures.single_site_analyzed(api, site_overrides={"site_code": "LK1"})
    block = fixtures.create_nursery_block(api, block_code="NB-LK1")
    planning_series = fixtures.create_series(
        api, net.program_id, replication_count=4, min_locations=1
    )
    fixtures.record_decision(
        api,
        net.line_a_id,
        net.series_id,
        decision=DecisionType.DISCARD,
        granted_plots=0,
        rationale="lodging in every rep",
    )
    discarded = validate_success(api.get_line(net.line_a_id, DIRECTOR_HEADERS))
    assert discarded["pipeline_stage"] == PipelineStage.DISCARDED
    assert discarded["stewardship_status"] == StewardshipStatus.NOT_REQUIRED

    validate_error(
        api.create_planting(
            factories.planting_payload(block["id"], net.line_a_id), SCIENTIST_HEADERS
        ),
        ApiErrorId.LINE_DISCARDED,
        409,
    )
    validate_error(
        api.create_entry(
            planning_series["id"],
            factories.entry_payload(net.line_a_id, net.site_id, plot_count=8),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.LINE_DISCARDED,
        409,
    )
    # Rung 16 outranks the no-live-package rung.
    validate_error(
        api.create_agreement(
            net.line_a_id,
            factories.agreement_payload(
                regulatory_dossier_ref="DOS-2852-08",
                grower_agreement_ref="GA-2852-08",
            ),
            REGULATORY_HEADERS,
        ),
        ApiErrorId.LINE_DISCARDED,
        409,
    )
    # Rung 16 outranks the stewardship rung, so this is not ERR_STEWARDSHIP_NOT_APPROVED.
    validate_error(
        api.create_lot(
            factories.lot_payload(
                net.line_a_id,
                "US_CORNBELT",
                [factories.allocation("US_CORNBELT", 100)],
            ),
            PLANNER_HEADERS,
        ),
        ApiErrorId.LINE_DISCARDED,
        409,
    )
    validate_error(
        api.create_backcross(
            factories.backcross_payload(net.line_a_id, net.line_b_id),
            SCIENTIST_HEADERS,
        ),
        ApiErrorId.LINE_DISCARDED,
        409,
    )

    program = validate_success(api.get_program(net.program_id, DIRECTOR_HEADERS))
    # Both HARVESTED entries survive the discard cascade.
    assert program["committed_plot_count"] == 16
    assert program["active_line_count"] == 1
    _rows, meta = validate_paginated(
        api.list_lines(DIRECTOR_HEADERS, {"pipeline_stage": PipelineStage.DISCARDED})
    )
    assert meta["total_count"] == 1


def test_the_marker_cycle_self_loop_counts_up_before_it_recomputes_recovery(api):
    """
    The generation counter rises first and only then feeds the recovery formula, so
    the three cycles read 90.000, 96.250 and 99.375; the third crosses the
    conversion bar, writes the trait score across into the germplasm, and closes the
    loop.

    PRD 3.4: "The project opens in `status` `ACTIVE` with `bc_generation` at 1 and
    `target_marker_present` false, and the server immediately computes the project's
    `recurrent_genome_pct`."
    PRD 3.4: "A **marker cycle** reports the outcome of one more backcross
    generation: the scientist supplies `target_marker_present` for the cycle just
    completed, the project's `bc_generation` rises by 1, the reported flag is
    stored, and `recurrent_genome_pct` is recomputed from the new generation count."
    PRD 3.4: "Conversion happens when the recomputed `recurrent_genome_pct` reaches
    99.0 or more **and** `target_marker_present` is true."
    PRD 3.4: "Then the project moves `ACTIVE → CONVERTED`, and the conversion
    reaches across into the germplasm: the recurrent line's
    `disease_resistance_scores` map gains an entry for the project's
    `target_trait_code` with the score 8, overwriting any lower score already
    recorded there, and the line's `version` advances."

    Design: Corner/state_machines/backcross_marker_cycles_loop_then_convert_and_write_the_trait_score
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    donor = fixtures.create_line(
        api,
        program_id,
        objective_id,
        designation="SX-1001",
        seed_inventory_g=500000,
        disease_resistance_scores={"RUST": 8, "SDS": 7},
    )
    recurrent = fixtures.create_line(
        api,
        program_id,
        objective_id,
        designation="SX-1002",
        seed_inventory_g=400000,
        disease_resistance_scores={"RUST": 8, "SDS": 4},
    )
    project = validate_success(
        api.create_backcross(
            factories.backcross_payload(recurrent["id"], donor["id"]),
            SCIENTIST_HEADERS,
        ),
        201,
    )
    assert project["bc_generation"] == 1
    assert project["target_marker_present"] is False
    assert project["status"] == BackcrossStatus.ACTIVE
    # 100 * (1 - 0.5 ** 2) with no marker bonus.
    assert project["recurrent_genome_pct"] == approx3(75.000)

    expected = [(2, 90.000), (3, 96.250), (4, 99.375)]
    for index, (generation, recovery) in enumerate(expected):
        cycled = validate_success(
            api.marker_cycle(
                project["id"], factories.marker_cycle_payload(True), SCIENTIST_HEADERS
            )
        )
        assert cycled["bc_generation"] == generation
        assert cycled["recurrent_genome_pct"] == approx3(recovery)
        assert cycled["target_marker_present"] is True
        expected_status = (
            BackcrossStatus.CONVERTED if index == 2 else BackcrossStatus.ACTIVE
        )
        assert cycled["status"] == expected_status

    line = validate_success(api.get_line(recurrent["id"], SCIENTIST_HEADERS))
    assert line["disease_resistance_scores"]["SDS"] == 8
    assert line["disease_resistance_scores"]["RUST"] == 8

    validate_error(
        api.marker_cycle(
            project["id"], factories.marker_cycle_payload(True), SCIENTIST_HEADERS
        ),
        ApiErrorId.PROJECT_NOT_ACTIVE,
        409,
    )
    frozen = validate_success(api.get_backcross(project["id"], SCIENTIST_HEADERS))
    assert frozen["bc_generation"] == 4
    assert frozen["recurrent_genome_pct"] == approx3(99.375)


def test_closing_a_programme_freezes_every_mutation_it_owns_but_not_its_reads(api):
    """
    The programme guard is reached through a different reference path on each
    surface — the path, the body, or the series behind an entry — and it stops all
    three while the read-only projection keeps answering.

    PRD 3.1: "Closing a programme is a director's prerogative and flips `status` to
    `CLOSED`."
    PRD 3.1: "From that moment every write that would create or mutate a resource
    owned by the programme is refused with `ERR_PROGRAM_CLOSED`; reads continue to
    work, because a closed programme still has to be auditable."
    PRD 2.7: "**Programme open.** The `BreedingProgram` behind the resource being
    created or mutated has `status` `ACTIVE` — otherwise `ERR_PROGRAM_CLOSED` (409).
    Applies to every write that creates or mutates a resource owned by a
    programme."

    Design: Corner/state_machines/closing_a_program_freezes_every_mutation_it_owns
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line = fixtures.create_line_a(api, program_id, objective_id)
    site = fixtures.create_site(api, site_code="PZ1")
    series = fixtures.create_series(
        api, program_id, replication_count=3, min_locations=1
    )

    closed = validate_success(api.close_program(program_id, DIRECTOR_HEADERS))
    assert closed["status"] == ProgramStatus.CLOSED

    validate_error(
        api.create_line(
            factories.line_payload(
                program_id,
                objective_id,
                designation="SX-1099",
                seed_inventory_g=100000,
            ),
            SCIENTIST_HEADERS,
        ),
        ApiErrorId.PROGRAM_CLOSED,
        409,
    )
    validate_error(
        api.create_entry(
            series["id"],
            factories.entry_payload(line["id"], site["id"], plot_count=9),
            AGRONOMIST_HEADERS,
        ),
        ApiErrorId.PROGRAM_CLOSED,
        409,
    )
    validate_error(
        api.create_objective(
            program_id,
            factories.objective_payload(market_segment="MG3_SOUTH"),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.PROGRAM_CLOSED,
        409,
    )

    report = validate_success(api.get_pipeline_report(program_id, DIRECTOR_HEADERS))
    assert report["status"] == ProgramStatus.CLOSED
    assert report["active_line_count"] == 1
    assert report["committed_plot_count"] == 0
    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["active_line_count"] == 1
    reread = validate_success(api.get_series(series["id"], AGRONOMIST_HEADERS))
    assert reread["entry_count"] == 0
    assert reread["status"] == SeriesStatus.PLANNING
