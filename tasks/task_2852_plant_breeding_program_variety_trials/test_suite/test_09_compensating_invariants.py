"""
Conservation laws that must close after releases arriving by different
mechanisms: the programme's plot ledger and the line's seed-mass ledger.
"""

from test_helpers import (
    AGRONOMIST_HEADERS,
    DIRECTOR_HEADERS,
    PLANNER_HEADERS,
    SCIENTIST_HEADERS,
    ApiErrorId,
    DecisionType,
    EntryStatus,
    LotStatus,
    PipelineStage,
    PlantingStatus,
    assert_plot_budget_consistent,
    assert_seed_ledger_balances,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


def _program_committing_one_hundred_eighteen_plots(api):
    """
    Three different plot commitments at once: 16 plots of HARVESTED trial entries,
    12 plots of an ENTERED entry in a second series, a 50-plot PLANTED nursery
    planting, and 40 plots granted by an ADVANCE decision.
    """
    net = fixtures.single_site_data_complete(
        api,
        site_overrides={"site_code": "CV1"},
        program_overrides={"name": "Soy Conserve"},
    )
    fixtures.run_analysis(api, net.series_id)

    series2 = fixtures.create_series(
        api, net.program_id, replication_count=4, min_locations=1
    )
    entry_a2 = fixtures.create_entry(
        api, series2["id"], net.line_a_id, net.site_id, plot_count=12
    )
    block = fixtures.create_nursery_block(api, block_code="NB-CV1")
    planting = fixtures.create_planting(
        api,
        block["id"],
        net.line_a_id,
        sow_date="2026-10-05",
        expected_harvest_date="2027-02-10",
        plot_count=50,
    )
    validate_success(api.plant_planting(planting["id"], SCIENTIST_HEADERS))
    first_decision = fixtures.record_decision(
        api,
        net.line_a_id,
        net.series_id,
        decision=DecisionType.ADVANCE,
        granted_plots=40,
        rationale="stage 1 allocation",
    )
    net.series2_id = series2["id"]
    net.entry_a2_id = entry_a2["id"]
    net.planting_id = planting["id"]
    net.first_decision_id = first_decision["id"]
    return net


def test_a_hold_supersedes_the_advance_and_releases_only_its_granted_plots(api):
    """
    Superseding an ADVANCE with a HOLD frees the 40 granted plots without moving
    the line back down the ladder, and the ledger drops 118 to 78 exactly once.

    PRD 3.1: "`committed_plot_count` is a conserved quantity summed over exactly
    three sources and no others: the `plot_count` of every trial entry whose series
    belongs to this programme and whose `status` is `ENTERED`, `PLANTED` or
    `HARVESTED`; the `plot_count` of every nursery planting whose line belongs to
    this programme and whose `status` is `SCHEDULED` or `PLANTED`; and the
    `granted_plots` of every advancement decision whose line belongs to this
    programme, whose `decision` is `ADVANCE`, whose `is_superseded` is false, and
    whose line's `pipeline_stage` is not `DISCARDED`."
    PRD 3.8: "A `HOLD` decision is the branch that keeps a line in the pipeline
    without allocating anything to it. The line's `pipeline_stage` is unchanged, so
    `from_stage` and `to_stage` both record the current stage; `granted_plots` must
    be 0; the cited series must be `ANALYZED`; the line must not already be
    `DISCARDED`; and the supersession, plot release and version bump described
    above all still apply."

    Design: Difficulty/compensating_invariant/plot_conservation_across_supersession_withdrawal_and_harvest
    """
    net = _program_committing_one_hundred_eighteen_plots(api)
    before = validate_success(api.get_program(net.program_id, DIRECTOR_HEADERS))
    # 16 entry plots + 12 entry plots + 50 nursery plots + 40 granted plots.
    assert before["committed_plot_count"] == 118
    assert before["plot_budget_remaining"] == 4882
    assert_plot_budget_consistent(before)

    hold = fixtures.record_decision(
        api,
        net.line_a_id,
        net.series_id,
        decision=DecisionType.HOLD,
        granted_plots=0,
        rationale="allocation pulled back pending quality data",
    )
    assert hold["is_superseded"] is False
    assert hold["from_stage"] == PipelineStage.STAGE_1
    assert hold["to_stage"] == PipelineStage.STAGE_1
    superseded = validate_success(
        api.get_decision(net.first_decision_id, DIRECTOR_HEADERS)
    )
    assert superseded["is_superseded"] is True

    line = validate_success(api.get_line(net.line_a_id, DIRECTOR_HEADERS))
    assert line["pipeline_stage"] == PipelineStage.STAGE_1
    program = validate_success(api.get_program(net.program_id, DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 78
    assert program["plot_budget_remaining"] == 4922
    assert_plot_budget_consistent(program)


def test_withdrawal_and_harvest_each_release_their_plots_exactly_once(api):
    """
    An entry withdrawal frees 12 plots and a nursery harvest frees 50, leaving
    only the 16 plots of the two HARVESTED entries; asking for the withdrawal
    twice releases nothing further.

    PRD 3.6: "**Withdrawal** applies to an entry that is `ENTERED` or `PLANTED`,
    whose series is not `CLOSED`: the agronomist supplies a `withdrawal_reason`,
    the entry moves to `WITHDRAWN`, the programme's `committed_plot_count` falls by
    the entry's `plot_count` with `plot_budget_remaining` recomputed, the site's
    `peak_committed_plot_count`, `available_plot_count` and `capacity_posture` are
    re-derived over the remaining active entries, and the series' `entry_count`
    falls by one with `location_count` re-derived — the plots were never used, so
    the location no longer counts."
    PRD 3.3: "Both branches bank the seed: `seed_inventory_g` and
    `cumulative_seed_produced_g` on the line each rise by `harvested_seed_g`, and
    the block's `occupancy_status` becomes `FALLOW`, and the programme's
    `committed_plot_count` falls by the planting's `plot_count` with
    `plot_budget_remaining` recomputed, because the planting has left the set of
    scheduled-or-planted commitments."

    Design: Difficulty/compensating_invariant/plot_conservation_across_supersession_withdrawal_and_harvest
    """
    net = _program_committing_one_hundred_eighteen_plots(api)
    fixtures.record_decision(
        api,
        net.line_a_id,
        net.series_id,
        decision=DecisionType.HOLD,
        granted_plots=0,
    )

    withdrawn = validate_success(
        api.withdraw_entry(
            net.entry_a2_id, factories.withdraw_payload(), AGRONOMIST_HEADERS
        )
    )
    assert withdrawn["status"] == EntryStatus.WITHDRAWN
    program = validate_success(api.get_program(net.program_id, DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 66
    site = validate_success(api.get_site(net.site_id, AGRONOMIST_HEADERS))
    assert site["peak_committed_plot_count"] == 16

    harvested = validate_success(
        api.harvest_planting(
            net.planting_id, factories.harvest_payload(), SCIENTIST_HEADERS
        )
    )
    assert harvested["status"] == PlantingStatus.HARVESTED
    # Generation 6 rises to 7 because 5000 g clears the 250 g minimum.
    assert harvested["generation_advanced_to"] == 7
    program = validate_success(api.get_program(net.program_id, DIRECTOR_HEADERS))
    # Only the two HARVESTED trial entries still hold ground.
    assert program["committed_plot_count"] == 16
    assert program["plot_budget_remaining"] == 4984
    assert_plot_budget_consistent(program)

    validate_error(
        api.withdraw_entry(
            net.entry_a2_id, factories.withdraw_payload(), AGRONOMIST_HEADERS
        ),
        ApiErrorId.ENTRY_INVALID_STATE,
        409,
    )
    program = validate_success(api.get_program(net.program_id, DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 16


def _line_with_one_lot_in_production(api):
    """
    Line SX-1301 opened with 500000 g, an APPROVED package covering three markets,
    and one 619-bag lot holding 386875 g of parent seed already IN_PRODUCTION.
    """
    program_id, objective_id = fixtures.program_with_objective(
        api, program_overrides={"name": "Soy Ledger"}
    )
    line = fixtures.create_line(
        api,
        program_id,
        objective_id,
        designation="SX-1301",
        seed_inventory_g=500000,
        disease_resistance_scores={"RUST": 8, "SDS": 7},
        quality_trait_values={"PROTEIN": 13.4},
    )
    fixtures.approved_agreement(
        api,
        line["id"],
        markets=["US_CORNBELT", "CA_PRAIRIE", "MX_BAJIO"],
        regulatory_dossier_ref="DOS-2852-07",
        grower_agreement_ref="GA-2852-07",
    )
    lot = fixtures.reserve_lot(
        api,
        line["id"],
        "US_CORNBELT",
        [
            factories.allocation("US_CORNBELT", 4000),
            factories.allocation("CA_PRAIRIE", 9000),
            factories.allocation("MX_BAJIO", 1300),
        ],
    )
    validate_success(api.start_lot_production(lot["id"], PLANNER_HEADERS))
    return {
        "program_id": program_id,
        "line_id": line["id"],
        "lot_id": lot["id"],
    }


def test_completion_moves_reserved_seed_into_consumed_rather_than_refunding_it(api):
    """
    A COMPLETED lot's parent seed leaves `reserved_seed_g` for `consumed_seed_g`
    permanently while the multiplied harvest is credited, so the ledger closes on
    a larger total without the 386875 g ever coming back to inventory.

    PRD 3.9: "Together these close the invariant that the line's
    `seed_inventory_g` plus its `reserved_seed_g` plus its `consumed_seed_g` equals
    its `cumulative_seed_produced_g` at every observable moment."
    PRD 3.9: "**Completing** takes an `IN_PRODUCTION` lot to `COMPLETED`: the
    allocated parent seed moves out of `reserved_seed_g` and into `consumed_seed_g`,
    staying out of `seed_inventory_g` permanently, and the multiplied harvest is
    credited — both the line's `seed_inventory_g` and its
    `cumulative_seed_produced_g` rise by `allocated_seed_g` multiplied by the field
    multiplication factor of 40 — so the seed-mass invariant still closes on the
    new, larger total."

    Design: Difficulty/compensating_invariant/seed_mass_conservation_across_lot_completion_and_cancellation
    """
    net = _line_with_one_lot_in_production(api)
    before = validate_success(api.get_line(net["line_id"], PLANNER_HEADERS))
    # 619 bags at 25 kg, multiplied to grams and divided by 40, is 386875 g.
    assert before["seed_inventory_g"] == 113125
    assert before["reserved_seed_g"] == 386875
    assert before["consumed_seed_g"] == 0
    assert before["cumulative_seed_produced_g"] == 500000
    assert_seed_ledger_balances(before)

    completed = validate_success(api.complete_lot(net["lot_id"], PLANNER_HEADERS))
    assert completed["status"] == LotStatus.COMPLETED
    assert completed["allocated_seed_g"] == 386875
    assert completed["planned_units_bags"] == 619

    line = validate_success(api.get_line(net["line_id"], PLANNER_HEADERS))
    assert line["reserved_seed_g"] == 0
    assert line["consumed_seed_g"] == 386875
    # 113125 plus the 15475000 g the field returned.
    assert line["seed_inventory_g"] == 15588125
    assert line["cumulative_seed_produced_g"] == 15975000
    # A refund would have parked the whole conserved total in inventory.
    assert line["seed_inventory_g"] != 15975000
    assert_seed_ledger_balances(line)


def test_cancellation_is_exactly_compensating_and_leaves_consumed_seed_alone(api):
    """
    A second lot reserved after the completion and then cancelled returns its
    35625 g outright, restoring the ledger to the post-completion figures while the
    launch volume still counts only the COMPLETED lot.

    PRD 3.9: "**Cancelling** applies to a lot that is `RESERVED`, `IN_PRODUCTION`
    or `ON_HOLD`, accepts an optional `hold_reason`, and is exactly compensating:
    the lot becomes `CANCELLED`, the line's `seed_inventory_g` is credited back by
    the lot's `allocated_seed_g` while `reserved_seed_g` and
    `planned_launch_units_bags` are re-derived, the line's `version` increments, and
    the programme's `pre_commercial_units_bags` is recomputed — leaving no drift in
    the ledger."
    PRD 3.9: "`planned_launch_units_bags`, meanwhile, sums `planned_units_bags`
    over the line's lots whose `status` is `RESERVED`, `IN_PRODUCTION` or
    `COMPLETED`, excluding lots that are `ON_HOLD` or `CANCELLED` — which is
    exactly why a suspension can drag a line back below the launch-volume condition
    of the commercial gate."

    Design: Difficulty/compensating_invariant/seed_mass_conservation_across_lot_completion_and_cancellation
    """
    net = _line_with_one_lot_in_production(api)
    validate_success(api.complete_lot(net["lot_id"], PLANNER_HEADERS))

    second = fixtures.reserve_lot(
        api,
        net["line_id"],
        "MX_BAJIO",
        [factories.allocation("MX_BAJIO", 1300)],
        launch_year=2029,
    )
    assert second["planned_units_bags"] == 57
    assert second["allocated_seed_g"] == 35625
    mid = validate_success(api.get_line(net["line_id"], PLANNER_HEADERS))
    assert mid["seed_inventory_g"] == 15552500
    assert mid["reserved_seed_g"] == 35625
    assert mid["consumed_seed_g"] == 386875
    assert mid["cumulative_seed_produced_g"] == 15975000
    assert_seed_ledger_balances(mid)

    cancelled = validate_success(
        api.cancel_lot(
            second["id"], PLANNER_HEADERS, {"hold_reason": "launch deferred to 2030"}
        )
    )
    assert cancelled["status"] == LotStatus.CANCELLED

    line = validate_success(api.get_line(net["line_id"], PLANNER_HEADERS))
    assert line["seed_inventory_g"] == 15588125
    assert line["reserved_seed_g"] == 0
    assert line["consumed_seed_g"] == 386875
    assert line["cumulative_seed_produced_g"] == 15975000
    assert_seed_ledger_balances(line)
    assert line["planned_launch_units_bags"] == 619
    program = validate_success(api.get_program(net["program_id"], DIRECTOR_HEADERS))
    assert program["pre_commercial_units_bags"] == 619
