"""
The arithmetic: inclusion-set filters, pinned rounding order, tier boundaries at
the exact comparison point, variants that can annihilate their own input set,
component caps and spec directions, and the thresholds that flip a branch.
"""

from test_helpers import (
    AGRONOMIST_HEADERS,
    ANALYST_HEADERS,
    DIRECTOR_HEADERS,
    SCIENTIST_HEADERS,
    AnalysisVariant,
    ApiErrorId,
    BackcrossStatus,
    DecisionType,
    EntryStatus,
    PipelineStage,
    QcStatus,
    SeriesStatus,
    StabilityClass,
    AdvancementReadiness,
    PlantingStatus,
    OccupancyStatus,
    approx2,
    approx3,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_rollup_ignores_rejected_outlier_and_other_trait_rows(api):
    """
    The inclusion set is a triple filter, and every excluded row must leave both
    the count and the sum untouched rather than merely the count.

    PRD 3.6: "The rollup uses exactly the inclusion set that defines
    `valid_rep_count`: `ACCEPTED`, non-outlier `YIELD_KG_PLOT` observations of this
    entry, with rejected rows and outlier-flagged rows excluded from both the count
    and the sum."
    PRD 3.6: "Every recorded observation re-derives the entry's `valid_rep_count`,
    which counts only this entry's observations whose `trait_code` is
    `YIELD_KG_PLOT`, whose `qc_status` is `ACCEPTED` and whose `is_outlier` is
    false."
    PRD 3.6: "The entry must be `PLANTED`, and its `valid_rep_count` must be at
    least 3 — fewer valid replications cannot support a mean, so the request is
    refused with `ERR_INSUFFICIENT_REPLICATION`."

    Design: Corner/calculations/entry_rollup_excludes_rejected_outlier_and_other_traits
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line_a = fixtures.create_line(
        api, program_id, objective_id, designation="SX-1001", seed_inventory_g=500000
    )
    line_b = fixtures.create_line(
        api, program_id, objective_id, designation="SX-1002", seed_inventory_g=400000
    )
    site = fixtures.create_site(api, site_code="FR1")
    series = fixtures.create_series(
        api, program_id, replication_count=5, min_locations=1
    )
    entry_a = fixtures.create_entry(
        api, series["id"], line_a["id"], site["id"], plot_count=10
    )
    entry_b = fixtures.create_entry(
        api, series["id"], line_b["id"], site["id"], plot_count=10
    )
    fixtures.plant_series(api, series["id"])

    fixtures.record_yield_reps(api, entry_b["id"], [14.0, 14.0, 14.0])
    fixtures.record_yield_reps(api, entry_a["id"], [14.0, 15.5, 15.5])
    validate_success(
        api.create_observation(
            entry_a["id"],
            factories.rejected_observation_payload(4, 20.0),
            AGRONOMIST_HEADERS,
        ),
        201,
    )
    validate_success(
        api.create_observation(
            entry_a["id"],
            factories.observation_payload(5, 30.0, is_outlier=True),
            AGRONOMIST_HEADERS,
        ),
        201,
    )
    validate_success(
        api.create_observation(
            entry_a["id"],
            factories.observation_payload(1, 13.4, trait_code="PROTEIN_PCT"),
            AGRONOMIST_HEADERS,
        ),
        201,
    )

    pre = validate_success(api.get_entry(entry_a["id"], AGRONOMIST_HEADERS))
    assert pre["valid_rep_count"] == 3

    finalized = validate_success(api.finalize_entry(entry_a["id"], AGRONOMIST_HEADERS))
    assert finalized["status"] == EntryStatus.HARVESTED
    # 45.0 over three usable reps, not 95.0 over five.
    assert finalized["plot_mean_yield_kg"] == approx3(15.000)
    assert finalized["yield_kg_per_ha"] == approx2(12000.00)
    assert finalized["valid_rep_count"] == 3

    _rows, meta = validate_paginated(
        api.list_observations(
            entry_a["id"], AGRONOMIST_HEADERS, {"qc_status": QcStatus.ACCEPTED, "limit": 50}
        )
    )
    # Four accepted yield rows — the outlier is accepted but excluded — plus the protein row.
    assert meta["total_count"] == 5

    other = fixtures.finalize_entry(api, entry_b["id"])
    assert other["plot_mean_yield_kg"] == approx3(14.000)
    assert other["yield_kg_per_ha"] == approx2(11200.00)


def test_the_plot_mean_is_rounded_before_it_is_scaled_to_hectares(api):
    """
    The rounding order is distinguishable to the cent: 42.7 over three reps must
    become 14.233 first and only then be multiplied by 800.

    PRD 3.6: "`plot_mean_yield_kg` is the sum of those observation `value` figures
    divided by `valid_rep_count`, rounded half up to three decimals."
    PRD 3.6: "Then — and the order matters — that already-rounded three-decimal
    mean is scaled to a per-hectare figure and rounded again: `yield_kg_per_ha` is
    `plot_mean_yield_kg` multiplied by 800, rounded half up to two decimals."
    PRD 2.6: "Two cases recur: a per-hectare yield is derived from the
    already-rounded three-decimal plot mean rather than from the raw sum, and a
    stability regression is computed from already-rounded two-decimal yields and
    environment indices rather than from re-derived ones."

    Design: Corner/calculations/entry_rollup_rounds_the_plot_mean_before_scaling_to_hectares
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line_a = fixtures.create_line(
        api, program_id, objective_id, designation="SX-1001", seed_inventory_g=500000
    )
    line_b = fixtures.create_line(
        api, program_id, objective_id, designation="SX-1002", seed_inventory_g=400000
    )
    site = fixtures.create_site(api, site_code="RO1")
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
    fixtures.record_yield_reps(api, entry_b["id"], [14.0, 14.0, 14.0])
    fixtures.record_yield_reps(api, entry_a["id"], [14.1, 14.2, 14.4])

    finalized = fixtures.finalize_entry(api, entry_a["id"])
    # 42.7 / 3 is 14.23333..., which rounds half up to 14.233.
    assert finalized["plot_mean_yield_kg"] == approx3(14.233)
    # 14.233 * 800; scaling the unrounded quotient would give 11386.67.
    assert finalized["yield_kg_per_ha"] == approx2(11386.40)
    assert finalized["yield_kg_per_ha"] != approx2(11386.67)
    assert finalized["valid_rep_count"] == 3
    assert finalized["status"] == EntryStatus.HARVESTED


def test_a_subtotal_of_exactly_ten_thousand_takes_the_second_tier_then_exhausts_the_budget(api):
    """
    Two boundaries meet: the withdrawn entry must be gone from the subtotal, which
    is what lands it exactly on 10000.00, and the strict comparison there selects
    the 0.09 rate rather than 0.12; the cash budget then closes at exactly zero and
    the next series cannot be planted.

    PRD 3.6: "Costing runs in a pinned order over the entries that will actually go
    into the ground — that is, the entries of this series whose `status` is
    `ENTERED` at the moment of the call."
    PRD 3.6: "The comparisons are strict, so a subtotal of exactly 10000.00 selects
    the 0.09 rate and a subtotal of exactly 50000.00 selects 0.07."
    PRD 3.6: "Before anything is written, that total is tested against the
    programme's uncommitted cash: `total_trial_cost_usd` must be no greater than
    `total_budget_usd` less `committed_budget_usd`, or the request is refused with
    `ERR_PROGRAM_BUDGET_USD_EXCEEDED`."

    Design: Corner/calculations/cost_tier_boundary_at_exactly_ten_thousand_then_budget_refusal
    """
    program_id, objective_id = fixtures.program_with_objective(
        api, program_overrides={"total_budget_usd": 10900.00}
    )
    lines = [
        fixtures.create_line(
            api, program_id, objective_id, designation=code, seed_inventory_g=300000
        )
        for code in ("SX-1001", "SX-1002", "SX-1003")
    ]
    site = fixtures.create_site(
        api, site_code="TC1", total_plot_capacity=400, plot_cost_usd=50.00
    )
    alpha = fixtures.create_series(
        api, program_id, replication_count=4, min_locations=1
    )
    fixtures.create_entry(api, alpha["id"], lines[0]["id"], site["id"], plot_count=100)
    fixtures.create_entry(api, alpha["id"], lines[1]["id"], site["id"], plot_count=100)
    entry_c = fixtures.create_entry(
        api, alpha["id"], lines[2]["id"], site["id"], plot_count=40
    )
    beta = fixtures.create_series(api, program_id, replication_count=4, min_locations=1)
    fixtures.create_entry(api, beta["id"], lines[0]["id"], site["id"], plot_count=4)
    fixtures.create_entry(api, beta["id"], lines[1]["id"], site["id"], plot_count=4)

    validate_success(
        api.withdraw_entry(
            entry_c["id"], factories.withdraw_payload(), AGRONOMIST_HEADERS
        )
    )

    planted = fixtures.plant_series(api, alpha["id"])
    # 200 surviving plots at 50.00; the withdrawn 40-plot entry contributes nothing.
    assert planted["plot_cost_subtotal_usd"] == approx2(10000.00)
    # Strictly below 10000.00 selects 0.12, and 10000.00 is not strictly below it.
    assert planted["management_fee_usd"] == approx2(900.00)
    assert planted["total_trial_cost_usd"] == approx2(10900.00)
    assert planted["status"] == SeriesStatus.PLANTED

    report = validate_success(api.get_pipeline_report(program_id, DIRECTOR_HEADERS))
    assert report["committed_budget_usd"] == approx2(10900.00)
    assert report["budget_remaining_usd"] == approx2(0.00)

    # Beta's own 400.00 subtotal plus a 48.00 fee cannot fit inside nothing.
    validate_error(
        api.plant_series(beta["id"], AGRONOMIST_HEADERS),
        ApiErrorId.PROGRAM_BUDGET_USD_EXCEEDED,
        409,
    )
    unplanted = validate_success(api.get_series(beta["id"], AGRONOMIST_HEADERS))
    assert unplanted["status"] == SeriesStatus.PLANNING
    assert unplanted["total_trial_cost_usd"] is None
    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["committed_budget_usd"] == approx2(10900.00)


def test_an_empty_balanced_core_is_refused_while_the_inclusive_variant_analyses_it(api):
    """
    With each line tested at only one of the two sites no site qualifies as core,
    so the variant annihilates its own input set; the refusal burns no version and
    the same token still buys the inclusive analysis.

    PRD 3.7: "Under `BALANCED_CORE` the server first identifies the core locations:
    a site qualifies as core when **every** breeding line that has at least one
    harvested entry anywhere in this series also has a harvested entry at that
    site."
    PRD 3.7: "If the core set turns out to be empty, or if under either variant
    there is no harvested entry at all, the analysis is refused with
    `ERR_EMPTY_BALANCED_CORE`."
    PRD 3.7: "When n is below 2 no line can be fitted, so `stability_regression_b`
    and `deviation_mse` are both null and `stability_class` is `UNCLASSIFIED`."
    PRD 3.6: "The agronomist may plant only a series still in `PLANNING` whose
    programme is `ACTIVE`, whose `location_count` is at least its `min_locations`,
    and whose `entry_count` is at least 2; a network that is short of locations or
    has fewer than two entries is refused with `ERR_INSUFFICIENT_LOCATIONS`."

    Design: Corner/calculations/balanced_core_is_empty_when_no_site_carries_every_line
    """
    program_id, objective_id = fixtures.program_with_objective(
        api, objective_overrides={"quality_trait_specs": {"PROTEIN_MIN": 13.0}}
    )
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
        api,
        program_id,
        objective_id,
        designation="SX-1002",
        seed_inventory_g=400000,
        disease_resistance_scores={"RUST": 8, "SDS": 4},
    )
    site_1 = fixtures.create_site(api, site_code="EC1")
    site_2 = fixtures.create_site(
        api, site_code="EC2", environment_class="DROUGHT_STRESS"
    )
    series = fixtures.create_series(
        api, program_id, replication_count=3, min_locations=2
    )
    entry_a = fixtures.create_entry(
        api, series["id"], line_a["id"], site_1["id"], plot_count=9
    )
    validate_error(
        api.plant_series(series["id"], AGRONOMIST_HEADERS),
        ApiErrorId.INSUFFICIENT_LOCATIONS,
        422,
    )
    entry_b = fixtures.create_entry(
        api, series["id"], line_b["id"], site_2["id"], plot_count=9
    )
    planted = fixtures.plant_series(api, series["id"])
    assert planted["location_count"] == 2
    assert planted["entry_count"] == 2

    fixtures.record_yield_reps(api, entry_a["id"], [15.0, 15.0, 15.0])
    fixtures.record_yield_reps(api, entry_b["id"], [14.0, 14.0, 14.0])
    fixtures.finalize_entry(api, entry_a["id"])
    fixtures.finalize_entry(api, entry_b["id"])

    version = api.series_version(series["id"], ANALYST_HEADERS)
    validate_error(
        api.create_analysis(
            series["id"],
            factories.analysis_payload(version, variant=AnalysisVariant.BALANCED_CORE),
            ANALYST_HEADERS,
        ),
        ApiErrorId.EMPTY_BALANCED_CORE,
        422,
    )
    assert api.series_version(series["id"], ANALYST_HEADERS) == version

    analysis = validate_success(
        api.create_analysis(
            series["id"],
            factories.analysis_payload(
                version, variant=AnalysisVariant.UNBALANCED_INCLUSIVE
            ),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert analysis["included_line_count"] == 2
    assert analysis["included_location_count"] == 2
    means = analysis["entry_means"]
    assert [row["line_id"] for row in means] == [line_a["id"], line_b["id"]]
    assert means[0]["adjusted_mean_kg_per_ha"] == approx2(12000.00)
    assert means[1]["adjusted_mean_kg_per_ha"] == approx2(11200.00)
    for row in means:
        assert row["included_location_count"] == 1
        assert row["stability_regression_b"] is None
        assert row["deviation_mse"] is None
        assert row["stability_class"] == StabilityClass.UNCLASSIFIED
    index = analysis["environment_index"]
    assert [row["trial_site_id"] for row in index] == [site_1["id"], site_2["id"]]
    assert index[0]["index_kg_per_ha"] == approx2(12000.00)
    assert index[1]["index_kg_per_ha"] == approx2(11200.00)

    # 0.50*109.09 + 0.30*100.00 + 0.20*100.00 for A; B's quality is imputed at 60.
    assert validate_success(api.get_line(line_a["id"], DIRECTOR_HEADERS))[
        "advancement_index_provisional"
    ] == approx2(104.55)
    assert validate_success(api.get_line(line_b["id"], DIRECTOR_HEADERS))[
        "advancement_index_provisional"
    ] == approx2(77.91)


def test_the_yield_cap_and_the_two_spec_directions_decide_who_clears_the_bar(api):
    """
    Both lines overshoot the yield target far enough to be clamped at 120, both
    miss exactly one quality spec — one on a `_MIN` floor and one on the
    `MOISTURE_MAX` ceiling — and the disease component plus the nursery confidence
    factor are what separate a 96.30 pass from an 82.80 refusal.

    PRD 3.8: "The component is 100 multiplied by that source figure divided by the
    objective's `target_yield_kg_per_ha`, rounded half up to two decimals, and then
    capped at 120 — a line cannot bank more than a twenty-percent overshoot of its
    market's yield target."
    PRD 3.8: "A spec whose code ends in `_MIN` — `TEST_WEIGHT_MIN`, `PROTEIN_MIN`,
    `OIL_MIN` — passes when the line's measured value for the corresponding trait
    (`TEST_WEIGHT`, `PROTEIN`, `OIL`) is at or above the spec's threshold.
    `MOISTURE_MAX` passes when the line's measured `MOISTURE` value is at or below
    its threshold."
    PRD 3.8: "Each miss costs 15 points off a perfect hundred, and the component is
    the larger of 0 and 100 less 15 times the miss count — so four or more misses
    floor the component at zero rather than driving it negative."
    PRD 3.8: "Every rung additionally requires that the frozen CUMULATIVE index
    reach the objective's `min_advancement_index`, failing which the decision is
    refused with `ERR_INDEX_BELOW_THRESHOLD`, and that `granted_plots` fit inside
    the programme's `plot_budget_remaining`, failing which it is refused with
    `ERR_PROGRAM_PLOT_BUDGET_EXCEEDED`."

    Design: Corner/calculations/advancement_index_caps_yield_and_scores_quality_spec_directions
    """
    program_id, objective_id = fixtures.program_with_objective(
        api,
        objective_overrides={
            "target_yield_kg_per_ha": 8000.00,
            "quality_trait_specs": {"PROTEIN_MIN": 13.0, "MOISTURE_MAX": 12.0},
        },
    )
    line_a = fixtures.create_line(
        api, program_id, objective_id, designation="SX-1001",
        disease_resistance_scores={"RUST": 8, "SDS": 7},
        quality_trait_values={"PROTEIN": 13.4, "MOISTURE": 12.5},
    )
    line_b = fixtures.create_line(
        api, program_id, objective_id, designation="SX-1002",
        disease_resistance_scores={"RUST": 8, "SDS": 4},
        quality_trait_values={"PROTEIN": 12.0, "MOISTURE": 11.0},
    )
    site = fixtures.create_site(api, site_code="CP1")
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
    fixtures.finalize_entry(api, entry_b["id"])
    fixtures.run_analysis(api, series["id"], variant=AnalysisVariant.BALANCED_CORE)

    # 150.00 and 140.00 raw both clamp to 120; quality is 85.00 for both.
    assert validate_success(api.get_line(line_a["id"], DIRECTOR_HEADERS))[
        "advancement_index_provisional"
    ] == approx2(107.00)
    assert validate_success(api.get_line(line_b["id"], DIRECTOR_HEADERS))[
        "advancement_index_provisional"
    ] == approx2(92.00)

    decision = fixtures.record_decision(
        api, line_a["id"], series["id"], decision=DecisionType.ADVANCE,
        granted_plots=40, rationale="clears the bar on disease breadth",
    )
    assert decision["decision_index_value"] == approx2(96.30)
    assert decision["to_stage"] == PipelineStage.STAGE_1
    advanced = validate_success(api.get_line(line_a["id"], DIRECTOR_HEADERS))
    assert advanced["pipeline_stage"] == PipelineStage.STAGE_1
    assert advanced["advancement_readiness"] == AdvancementReadiness.NOT_READY

    validate_error(
        api.create_decision(
            factories.decision_payload(
                line_b["id"], series["id"],
                api.line_version(line_b["id"], DIRECTOR_HEADERS),
                decision=DecisionType.ADVANCE, granted_plots=40,
            ),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.INDEX_BELOW_THRESHOLD,
        422,
    )
    held_back = validate_success(api.get_line(line_b["id"], DIRECTOR_HEADERS))
    assert held_back["pipeline_stage"] == PipelineStage.NURSERY
    _rows, meta = validate_paginated(
        api.list_decisions(DIRECTOR_HEADERS, {"line_id": line_b["id"]})
    )
    assert meta["total_count"] == 0
    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    # 9 + 9 entry plots plus the 40 granted to line A only.
    assert program["committed_plot_count"] == 58


def test_a_non_marker_project_never_earns_the_bonus_and_stalls_at_the_cap(api):
    """
    Eight cycles walk the bare theoretical curve to the 99.900 clamp, and the last
    three of them read above 99.0 yet must stay ACTIVE because the conjunction's
    other half is false; only the cycle that finally reports the marker converts.

    PRD 3.4: "The theoretical part is 100 multiplied by the quantity one minus one
    half raised to the power of the current `bc_generation` plus one. A bonus of
    2.5 percentage points is added when, and only when, both the project's
    `marker_assisted` flag is true and its `target_marker_present` is true;
    otherwise no bonus is added. That sum is rounded half up to three decimal
    places and then capped so that `recurrent_genome_pct` never exceeds 99.900."
    PRD 3.4: "If the recomputed `recurrent_genome_pct` is below 99.0, or if
    `target_marker_present` is false, the project stays where it is — the
    transition is a self-loop `ACTIVE → ACTIVE`, and there is no cap on how many
    cycles a project may run."
    PRD 3.4: "Conversion happens when the recomputed `recurrent_genome_pct`
    reaches 99.0 or more **and** `target_marker_present` is true."

    Design: Corner/calculations/marker_recovery_cap_and_bonus_gate_without_marker_assistance
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    donor = fixtures.create_line(
        api, program_id, objective_id, designation="SX-1001",
        disease_resistance_scores={"SDS": 7},
    )
    recurrent = fixtures.create_line(
        api, program_id, objective_id, designation="SX-1002",
        disease_resistance_scores={"SDS": 4},
    )
    project = validate_success(
        api.create_backcross(
            factories.backcross_payload(
                recurrent["id"], donor["id"], target_trait_code="SDS",
                marker_assisted=False,
            ),
            SCIENTIST_HEADERS,
        ),
        201,
    )
    assert project["bc_generation"] == 1
    assert project["target_marker_present"] is False
    # 100 * (1 - 0.5^2) with no bonus available to a non-marker project.
    assert project["recurrent_genome_pct"] == approx3(75.000)

    curve = [87.500, 93.750, 96.875, 98.438, 99.219, 99.609, 99.805, 99.900]
    for offset, expected in enumerate(curve):
        cycled = validate_success(
            api.marker_cycle(
                project["id"], factories.marker_cycle_payload(False), SCIENTIST_HEADERS
            )
        )
        assert cycled["bc_generation"] == 2 + offset
        assert cycled["recurrent_genome_pct"] == approx3(expected)
        assert cycled["status"] == BackcrossStatus.ACTIVE
        assert cycled["target_marker_present"] is False
    # Generation 9 would reach 99.902 untruncated; the clamp holds it at 99.900.
    assert validate_success(api.get_line(recurrent["id"], SCIENTIST_HEADERS))[
        "disease_resistance_scores"
    ]["SDS"] == 4

    converted = validate_success(
        api.marker_cycle(
            project["id"], factories.marker_cycle_payload(True), SCIENTIST_HEADERS
        )
    )
    assert converted["bc_generation"] == 10
    assert converted["recurrent_genome_pct"] == approx3(99.900)
    assert converted["status"] == BackcrossStatus.CONVERTED
    line = validate_success(api.get_line(recurrent["id"], SCIENTIST_HEADERS))
    assert line["disease_resistance_scores"]["SDS"] == 8


def test_a_harvest_of_exactly_the_minimum_advances_the_generation_and_flips_readiness(api):
    """
    Exactly 250 g is the inclusive edge of the advance branch, and because the line
    sits one generation below the objective's minimum that single gram-exact
    harvest is also what re-derives `advancement_readiness` to READY.

    PRD 3.3: "When `harvested_seed_g` is at least 250 grams — the minimum viable
    seed quantity for the next selfing cycle, so exactly 250 grams succeeds — the
    planting becomes `HARVESTED`, the line's `generation_number` rises by 1, its
    `nursery_cycles_completed` rises by 1, and the planting's
    `generation_advanced_to` records the new `generation_number`."
    PRD 3.3: "The line's `version` advances and its `advancement_readiness` is then
    re-derived against the objective's `min_generation_number`, which is how a line
    flips `NOT_READY → READY`."
    PRD 3.3: "Both branches bank the seed: `seed_inventory_g` and
    `cumulative_seed_produced_g` on the line each rise by `harvested_seed_g`, and
    the block's `occupancy_status` becomes `FALLOW`, and the programme's
    `committed_plot_count` falls by the planting's `plot_count` with
    `plot_budget_remaining` recomputed, because the planting has left the set of
    scheduled-or-planted commitments."

    Design: Corner/calculations/nursery_harvest_threshold_at_exactly_the_minimum_flips_readiness
    """
    program_id, objective_id = fixtures.program_with_objective(
        api, objective_overrides={"min_generation_number": 5}
    )
    line = fixtures.create_line(
        api, program_id, objective_id, designation="SX-1001",
        generation_number=4, seed_inventory_g=1000,
    )
    assert line["advancement_readiness"] == AdvancementReadiness.NOT_READY
    assert line["nursery_cycles_completed"] == 0
    block = fixtures.create_nursery_block(api, block_code="NB-TH1")
    planting = fixtures.create_planting(
        api, block["id"], line["id"], sow_date="2026-10-05",
        expected_harvest_date="2027-02-10", plot_count=20,
    )
    validate_success(api.plant_planting(planting["id"], SCIENTIST_HEADERS))

    harvested = validate_success(
        api.harvest_planting(
            planting["id"],
            factories.harvest_payload(
                actual_harvest_date="2027-02-09", harvested_seed_g=250
            ),
            SCIENTIST_HEADERS,
        )
    )
    assert harvested["status"] == PlantingStatus.HARVESTED
    assert harvested["generation_advanced_to"] == 5

    after = validate_success(api.get_line(line["id"], SCIENTIST_HEADERS))
    assert after["generation_number"] == 5
    assert after["nursery_cycles_completed"] == 1
    assert after["advancement_readiness"] == AdvancementReadiness.READY
    assert after["seed_inventory_g"] == 1250
    assert after["cumulative_seed_produced_g"] == 1250
    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 0
    assert program["plot_budget_remaining"] == 5000

    validate_success(api.set_clock("2027-02-15T00:00:00Z", SCIENTIST_HEADERS))
    assert validate_success(api.get_nursery_block(block["id"], SCIENTIST_HEADERS))[
        "occupancy_status"
    ] == OccupancyStatus.FALLOW
