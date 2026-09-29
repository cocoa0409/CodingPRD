"""
Endpoint surfaces judged as endpoints: action routes that each guard their own
source state, a read that is a pure projection of the graph beneath it, and one
write whose three preconditions must be reached in ladder order.
"""

from test_helpers import (
    ANALYST_HEADERS,
    DIRECTOR_HEADERS,
    PLANNER_HEADERS,
    AnalysisVariant,
    AdvancementReadiness,
    ApiErrorId,
    DecisionType,
    LotStatus,
    PipelineStage,
    ProgramStatus,
    SeriesStatus,
    approx2,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


def test_each_lot_action_admits_only_its_own_source_state(api):
    """
    Four routes share one record and each names a different admissible source: a
    completion cannot jump the reservation, a start cannot repeat, and once
    COMPLETED the lot is outside the cancellable set entirely, so no compensating
    credit may be applied.

    PRD 2.7: "**Lot state.** The seed increase lot is `RESERVED` to start
    production, `IN_PRODUCTION` to be completed, and one of `RESERVED`,
    `IN_PRODUCTION` or `ON_HOLD` to be cancelled — otherwise
    `ERR_LOT_INVALID_STATE` (409)."
    PRD 3.9: "**Completing** takes an `IN_PRODUCTION` lot to `COMPLETED`: the
    allocated parent seed moves out of `reserved_seed_g` and into `consumed_seed_g`,
    staying out of `seed_inventory_g` permanently, and the multiplied harvest is
    credited — both the line's `seed_inventory_g` and its
    `cumulative_seed_produced_g` rise by `allocated_seed_g` multiplied by the field
    multiplication factor of 40 — so the seed-mass invariant still closes on the
    new, larger total."

    Design: Corner/endpoints/seed_lot_action_endpoints_each_guard_their_own_source_state
    """
    program_id, objective_id = fixtures.program_with_objective(api)
    line = fixtures.create_line(api, program_id, objective_id, designation="SX-1001")
    fixtures.approved_agreement(
        api, line["id"], markets=["US_CORNBELT"],
        regulatory_dossier_ref="DOS-2852-05", grower_agreement_ref="GA-2852-05",
    )
    lot = fixtures.reserve_lot(
        api, line["id"], "US_CORNBELT", [factories.allocation("US_CORNBELT", 100)]
    )
    assert lot["status"] == LotStatus.RESERVED
    assert lot["planned_units_bags"] == 5
    assert lot["allocated_seed_g"] == 3125

    validate_error(
        api.complete_lot(lot["id"], PLANNER_HEADERS),
        ApiErrorId.LOT_INVALID_STATE,
        409,
    )
    assert validate_success(api.get_lot(lot["id"], PLANNER_HEADERS))[
        "status"
    ] == LotStatus.RESERVED

    started = validate_success(api.start_lot_production(lot["id"], PLANNER_HEADERS))
    assert started["status"] == LotStatus.IN_PRODUCTION
    validate_error(
        api.start_lot_production(lot["id"], PLANNER_HEADERS),
        ApiErrorId.LOT_INVALID_STATE,
        409,
    )

    completed = validate_success(api.complete_lot(lot["id"], PLANNER_HEADERS))
    assert completed["status"] == LotStatus.COMPLETED
    after = validate_success(api.get_line(line["id"], PLANNER_HEADERS))
    assert after["reserved_seed_g"] == 0
    assert after["consumed_seed_g"] == 3125
    # 496875 left in hand plus the 125000 g the multiplication field returned.
    assert after["seed_inventory_g"] == 621875
    assert after["cumulative_seed_produced_g"] == 625000

    validate_error(
        api.cancel_lot(lot["id"], PLANNER_HEADERS),
        ApiErrorId.LOT_INVALID_STATE,
        409,
    )
    unchanged = validate_success(api.get_line(line["id"], PLANNER_HEADERS))
    assert unchanged["seed_inventory_g"] == 621875
    assert unchanged["consumed_seed_g"] == 3125
    assert validate_success(api.get_lot(lot["id"], PLANNER_HEADERS))[
        "planned_units_bags"
    ] == 5
    assert validate_success(api.get_program(program_id, DIRECTOR_HEADERS))[
        "pre_commercial_units_bags"
    ] == 5


def test_the_pipeline_report_is_derived_live_from_the_graph_beneath_it(api):
    """
    One advance and one discard later, every figure the report prints — the stage
    histogram, both census counts, the two budgets and the stewardship tallies —
    must agree with the records that produced them.

    PRD 3.1: "A read-only **pipeline report** serves the portfolio review meeting,
    deriving its whole payload live from the programme's lines, entries, plantings,
    decisions and lots rather than from stored snapshots."
    PRD 3.1: "Its body reports `program_id`, the programme's `status`, a
    `lines_by_stage` object keyed by pipeline stage with the count of lines
    currently at each stage, `active_line_count`, `discarded_line_count` for the
    lines whose `pipeline_stage` is `DISCARDED`, `committed_plot_count`,
    `plot_budget_remaining`, `total_plot_budget`, `committed_budget_usd`,
    `budget_remaining_usd` (the programme's `total_budget_usd` less its
    `committed_budget_usd`), `pre_commercial_units_bags`, and two stewardship
    census figures: `stewardship_approved_line_count` for lines whose
    `stewardship_status` is `APPROVED` and `stewardship_suspended_line_count` for
    lines whose `stewardship_status` is `SUSPENDED`."
    PRD 3.1: "On the cash side, `committed_budget_usd` is the sum of
    `total_trial_cost_usd` over the programme's trial series whose `status` is
    `PLANTED`, `DATA_COMPLETE`, `ANALYZED` or `CLOSED`."

    Design: Corner/endpoints/pipeline_report_is_a_pure_projection_of_the_program_graph
    """
    program_id, objective_id = fixtures.program_with_objective(
        api, objective_overrides={"quality_trait_specs": {"PROTEIN_MIN": 13.0}}
    )
    line_a = fixtures.create_line_a(api, program_id, objective_id)
    line_b = fixtures.create_line_b(api, program_id, objective_id)
    site = fixtures.create_site(api, site_code="PR1")
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

    advance = fixtures.record_decision(
        api, line_a["id"], series["id"], decision=DecisionType.ADVANCE,
        granted_plots=40, rationale="clears the bar",
    )
    assert advance["from_stage"] == PipelineStage.NURSERY
    assert advance["to_stage"] == PipelineStage.STAGE_1
    # The provisional 104.55 discounted by the NURSERY confidence factor of 0.90.
    assert advance["decision_index_value"] == approx2(94.10)
    fixtures.record_decision(
        api, line_b["id"], series["id"], decision=DecisionType.DISCARD,
        granted_plots=0, rationale="SDS score 4",
    )

    fixtures.approved_agreement(
        api, line_a["id"], markets=["US_CORNBELT"],
        regulatory_dossier_ref="DOS-2852-04", grower_agreement_ref="GA-2852-04",
    )
    fixtures.reserve_lot(
        api, line_a["id"], "US_CORNBELT", [factories.allocation("US_CORNBELT", 100)]
    )

    report = validate_success(api.get_pipeline_report(program_id, ANALYST_HEADERS))
    assert report["program_id"] == program_id
    assert report["status"] == ProgramStatus.ACTIVE
    stages = report["lines_by_stage"]
    assert stages["NURSERY"] == 0
    assert stages["STAGE_1"] == 1
    assert stages["STAGE_2"] == 0
    assert stages["STAGE_3"] == 0
    assert stages["PRE_COMMERCIAL"] == 0
    assert stages["DISCARDED"] == 1
    assert report["active_line_count"] == 1
    assert report["discarded_line_count"] == 1
    # 18 plots of HARVESTED entries — a discard withdraws neither — plus 40 granted.
    assert report["committed_plot_count"] == 58
    assert report["plot_budget_remaining"] == 4942
    assert report["total_plot_budget"] == 5000
    # 18 plots at 45.00 is 810.00, and the sub-10000.00 tier adds 97.20.
    assert report["committed_budget_usd"] == approx2(907.20)
    assert report["budget_remaining_usd"] == approx2(1999092.80)
    assert report["pre_commercial_units_bags"] == 5
    assert report["stewardship_approved_line_count"] == 1
    assert report["stewardship_suspended_line_count"] == 0


def test_the_three_decision_preconditions_are_reached_in_ladder_order(api):
    """
    Until the series is analysed no line is even looked at; then a line with no
    harvested entry is turned away on its data; then a short-generation line is
    turned away on readiness rather than on the index it would also miss — and the
    HOLD branch is exempt from that readiness rung altogether.

    PRD 2.7: "**Trial data exists.** The decision's line has at least one
    `TrialEntry` with `status` `HARVESTED` in the cited series — otherwise
    `ERR_NO_TRIAL_DATA` (422). Applies to advancement decision recording."
    PRD 2.7: "**Line ready.** For an `ADVANCE` decision leaving `NURSERY`, the
    line's `advancement_readiness` is `READY` — otherwise `ERR_LINE_NOT_READY`
    (422). Applies to advancement decision recording."
    PRD 3.8: "The first rung out of `NURSERY` also requires
    `advancement_readiness` to read `READY`, so a line that has not yet reached the
    objective's `min_generation_number` is turned away with `ERR_LINE_NOT_READY`."
    PRD 3.8: "A `HOLD` decision is the branch that keeps a line in the pipeline
    without allocating anything to it. The line's `pipeline_stage` is unchanged, so
    `from_stage` and `to_stage` both record the current stage; `granted_plots` must
    be 0; the cited series must be `ANALYZED`; the line must not already be
    `DISCARDED`; and the supersession, plot release and version bump described
    above all still apply."

    Design: Corner/endpoints/advancement_decision_preconditions_fire_in_rung_order
    """
    program_id, objective_id = fixtures.program_with_objective(
        api, objective_overrides={"quality_trait_specs": {"PROTEIN_MIN": 13.0}}
    )
    line_a = fixtures.create_line_a(api, program_id, objective_id)
    line_b = fixtures.create_line_b(api, program_id, objective_id, generation_number=3)
    line_c = fixtures.create_line(
        api, program_id, objective_id, designation="SX-1003", seed_inventory_g=300000
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
    fixtures.record_yield_reps(api, entry_a["id"], [15.0, 15.0, 15.0])
    fixtures.record_yield_reps(api, entry_b["id"], [14.0, 14.0, 14.0])
    fixtures.finalize_entry(api, entry_a["id"])
    fixtures.finalize_entry(api, entry_b["id"])
    assert validate_success(api.get_series(series["id"], ANALYST_HEADERS))[
        "status"
    ] == SeriesStatus.DATA_COMPLETE

    validate_error(
        api.create_decision(
            factories.decision_payload(
                line_a["id"], series["id"],
                api.line_version(line_a["id"], DIRECTOR_HEADERS),
                decision=DecisionType.HOLD, granted_plots=0, rationale="too early",
            ),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.SERIES_INVALID_STATE,
        409,
    )

    fixtures.run_analysis(api, series["id"], variant=AnalysisVariant.BALANCED_CORE)

    # SX-1003 is READY at generation 6 and still has no harvested entry here.
    validate_error(
        api.create_decision(
            factories.decision_payload(
                line_c["id"], series["id"],
                api.line_version(line_c["id"], DIRECTOR_HEADERS),
                decision=DecisionType.ADVANCE, granted_plots=10,
                rationale="no data at all",
            ),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.NO_TRIAL_DATA,
        422,
    )

    b_version = api.line_version(line_b["id"], DIRECTOR_HEADERS)
    validate_error(
        api.create_decision(
            factories.decision_payload(
                line_b["id"], series["id"], b_version,
                decision=DecisionType.ADVANCE, granted_plots=10,
                rationale="generation is short",
            ),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.LINE_NOT_READY,
        422,
    )

    hold = validate_success(
        api.create_decision(
            factories.decision_payload(
                line_b["id"], series["id"], b_version,
                decision=DecisionType.HOLD, granted_plots=0,
                rationale="carry to another winter cycle",
            ),
            DIRECTOR_HEADERS,
        ),
        201,
    )
    assert hold["decision"] == DecisionType.HOLD
    assert hold["granted_plots"] == 0
    assert hold["to_stage"] == PipelineStage.NURSERY

    after = validate_success(api.get_line(line_b["id"], DIRECTOR_HEADERS))
    assert after["pipeline_stage"] == PipelineStage.NURSERY
    assert after["advancement_readiness"] == AdvancementReadiness.NOT_READY
    program = validate_success(api.get_program(program_id, DIRECTOR_HEADERS))
    # None of the three refusals granted a plot.
    assert program["committed_plot_count"] == 18
