"""
Writes whose legality is decided by the state of a third entity the request body
only references: a crossing block that closes itself, and a series that must be
analysed before a stage gate may rest on it.
"""

from test_helpers import (
    DIRECTOR_HEADERS,
    SCIENTIST_HEADERS,
    AdvancementReadiness,
    AnalysisVariant,
    ApiErrorId,
    CrossingBlockStatus,
    DecisionType,
    PipelineStage,
    SeriesStatus,
    approx2,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


def _planned_block_with_two_parents(api):
    """A PLANNED crossing block with `planned_cross_count` 4 and two founder parents."""
    program_id, objective_id = fixtures.program_with_objective(
        api, program_overrides={"name": "Soy Crosses"}
    )
    female = fixtures.create_line(
        api, program_id, objective_id, designation="PAR-F1", seed_inventory_g=100000
    )
    male = fixtures.create_line(
        api, program_id, objective_id, designation="PAR-M1", seed_inventory_g=100000
    )
    block = fixtures.create_nursery_block(api, block_code="NB-CR1")
    crossing_block = fixtures.create_crossing_block(
        api, program_id, block["id"], planned_cross_count=4
    )
    return {
        "program_id": program_id,
        "objective_id": objective_id,
        "female_id": female["id"],
        "male_id": male["id"],
        "crossing_block_id": crossing_block["id"],
    }


def _progeny(net, designation):
    return factories.progeny_payload(
        net["objective_id"],
        designation=designation,
        female_parent_line_id=net["female_id"],
        male_parent_line_id=net["male_id"],
    )


def test_progeny_is_refused_while_the_block_is_still_planned(api):
    """
    The identical progeny body is refused before pollination and accepted after
    it, so the gate is the other entity's status rather than anything in the body.

    PRD 3.2: "Pollination is the scientist's report of what actually happened in
    the field. It moves the block from `PLANNED` to `POLLINATED` and stores a
    `realized_cross_count` that must be at least 1 and no greater than
    `planned_cross_count`; the block must still be `PLANNED` and its programme
    must be `ACTIVE`."
    PRD 3.2: "Only a `POLLINATED` block accepts progeny: registering a progeny
    line against a block that is still `PLANNED`, or one that has already reached
    `CLOSED`, is refused with `ERR_BLOCK_NOT_POLLINATED`."

    Design: Difficulty/cross_entity_state_dependency/progeny_creation_requires_pollinated_block_and_dies_on_auto_close
    """
    net = _planned_block_with_two_parents(api)
    validate_error(
        api.create_progeny(
            net["crossing_block_id"], _progeny(net, "PRG-0001"), SCIENTIST_HEADERS
        ),
        ApiErrorId.BLOCK_NOT_POLLINATED,
        409,
    )

    pollinated = validate_success(
        api.pollinate_crossing_block(
            net["crossing_block_id"], {"realized_cross_count": 2}, SCIENTIST_HEADERS
        )
    )
    assert pollinated["status"] == CrossingBlockStatus.POLLINATED
    assert pollinated["realized_cross_count"] == 2
    assert pollinated["planned_cross_count"] == 4
    assert pollinated["progeny_line_count"] == 0

    progeny = validate_success(
        api.create_progeny(
            net["crossing_block_id"], _progeny(net, "PRG-0001"), SCIENTIST_HEADERS
        ),
        201,
    )
    assert progeny["origin_block_id"] == net["crossing_block_id"]
    assert progeny["program_id"] == net["program_id"]
    assert progeny["pipeline_stage"] == PipelineStage.NURSERY
    assert progeny["cumulative_seed_produced_g"] == 400
    # Generation 2 sits below the objective's min_generation_number of 5.
    assert progeny["advancement_readiness"] == AdvancementReadiness.NOT_READY


def test_the_block_closes_itself_at_realized_cross_count_and_locks_out_the_third(api):
    """
    The window shuts on its own the moment `progeny_line_count` reaches
    `realized_cross_count` — two, not the planned four — and the next identical
    request draws the same refusal as before pollination.

    PRD 3.2: "Immediately after the progeny is created the block re-derives
    `progeny_line_count`, which counts the lines whose `origin_block_id` is this
    block and whose `pipeline_stage` is not `DISCARDED`; when that count equals
    `realized_cross_count`, the block auto-transitions `POLLINATED → CLOSED`
    without any client request, and subsequent progeny registrations against it
    fail with `ERR_BLOCK_NOT_POLLINATED`."
    PRD 3.2: "The new line takes its `program_id` from the block's programme and
    its `origin_block_id` from the block in the path, opens at `pipeline_stage`
    `NURSERY` and `stewardship_status` `NOT_REQUIRED`, has
    `cumulative_seed_produced_g` set to whatever `seed_inventory_g` it was
    created with, and increments the programme's `active_line_count` by one."

    Design: Difficulty/cross_entity_state_dependency/progeny_creation_requires_pollinated_block_and_dies_on_auto_close
    """
    net = _planned_block_with_two_parents(api)
    validate_success(
        api.pollinate_crossing_block(
            net["crossing_block_id"], {"realized_cross_count": 2}, SCIENTIST_HEADERS
        )
    )
    validate_success(
        api.create_progeny(
            net["crossing_block_id"], _progeny(net, "PRG-0001"), SCIENTIST_HEADERS
        ),
        201,
    )
    second = validate_success(
        api.create_progeny(
            net["crossing_block_id"], _progeny(net, "PRG-0002"), SCIENTIST_HEADERS
        ),
        201,
    )
    assert second["cumulative_seed_produced_g"] == 400

    block = validate_success(
        api.get_crossing_block(net["crossing_block_id"], SCIENTIST_HEADERS)
    )
    assert block["progeny_line_count"] == 2
    assert block["status"] == CrossingBlockStatus.CLOSED
    assert block["realized_cross_count"] == 2

    validate_error(
        api.create_progeny(
            net["crossing_block_id"], _progeny(net, "PRG-0003"), SCIENTIST_HEADERS
        ),
        ApiErrorId.BLOCK_NOT_POLLINATED,
        409,
    )
    program = validate_success(api.get_program(net["program_id"], DIRECTOR_HEADERS))
    # Two founders plus the two admitted progenies; the third never existed.
    assert program["active_line_count"] == 4


def _data_complete_series_with_no_analysis(api):
    """One STAGE_1 series at DATA_COMPLETE and deliberately never analysed."""
    return fixtures.single_site_data_complete(
        api,
        site_overrides={"site_code": "GK1"},
        program_overrides={"name": "Soy Gatekeeper"},
    )


def test_a_decision_on_a_data_complete_series_is_refused(api):
    """
    Harvested data is not analysed data: the gate reads the cited series' status,
    and the line itself gives no reason for the refusal.

    PRD 3.8: "In every branch, any earlier decision for the same combination of
    `line_id` and `trial_series_id` has `is_superseded` set to true and its
    `granted_plots` released from the programme's `committed_plot_count`, the
    line's `version` increments by one and its `updated_at` is refreshed, and the
    cited series must be `ANALYZED` — a decision resting on unanalysed data is
    refused with `ERR_SERIES_INVALID_STATE`."
    PRD 3.2: "Both routes derive `advancement_readiness` immediately and
    identically from the submitted `generation_number` measured against the
    objective's `min_generation_number`: the field reads `READY` when the line's
    `generation_number` is greater than or equal to that minimum, and `NOT_READY`
    otherwise."

    Design: Difficulty/cross_entity_state_dependency/advancement_decision_requires_analyzed_series_not_merely_complete_data
    """
    net = _data_complete_series_with_no_analysis(api)
    series = validate_success(api.get_series(net.series_id, DIRECTOR_HEADERS))
    assert series["status"] == SeriesStatus.DATA_COMPLETE
    line = validate_success(api.get_line(net.line_a_id, DIRECTOR_HEADERS))
    assert line["advancement_readiness"] == AdvancementReadiness.READY
    assert line["pipeline_stage"] == PipelineStage.NURSERY

    validate_error(
        api.create_decision(
            factories.decision_payload(
                net.line_a_id,
                net.series_id,
                line["version"],
                decision=DecisionType.ADVANCE,
                granted_plots=40,
                rationale="premature",
            ),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.SERIES_INVALID_STATE,
        409,
    )
    after = validate_success(api.get_line(net.line_a_id, DIRECTOR_HEADERS))
    assert after["pipeline_stage"] == PipelineStage.NURSERY
    assert after["version"] == line["version"]


def test_one_analysis_makes_the_identical_decision_body_legal(api):
    """
    Running a single analysis changes no entry and no line stage, yet it is what
    opens the gate the previous request was refused at.

    PRD 3.7: "The series moves to `ANALYZED` (from `DATA_COMPLETE`, or remaining
    there if it was already `ANALYZED`) and its `version` increments by one, which
    is why a second analyst working from a stale read is turned away."
    PRD 3.8: "On success the stage moves, `granted_plots` is added to the
    programme's `committed_plot_count` with `plot_budget_remaining` recomputed,
    and the line's `advancement_readiness` is reset to `NOT_READY` for the next
    stage."

    Design: Difficulty/cross_entity_state_dependency/advancement_decision_requires_analyzed_series_not_merely_complete_data
    """
    net = _data_complete_series_with_no_analysis(api)
    validate_error(
        api.create_decision(
            factories.decision_payload(
                net.line_a_id,
                net.series_id,
                api.line_version(net.line_a_id, DIRECTOR_HEADERS),
                decision=DecisionType.ADVANCE,
                granted_plots=40,
            ),
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.SERIES_INVALID_STATE,
        409,
    )

    analysis = fixtures.run_analysis(
        api, net.series_id, variant=AnalysisVariant.BALANCED_CORE
    )
    assert analysis["is_superseded"] is False
    series = validate_success(api.get_series(net.series_id, DIRECTOR_HEADERS))
    assert series["status"] == SeriesStatus.ANALYZED

    decision = fixtures.record_decision(
        api,
        net.line_a_id,
        net.series_id,
        decision=DecisionType.ADVANCE,
        granted_plots=40,
        rationale="clears the bar",
    )
    assert decision["from_stage"] == PipelineStage.NURSERY
    assert decision["to_stage"] == PipelineStage.STAGE_1
    # 0.50*109.09 + 0.30*100.00 + 0.20*85.00 = 101.55, discounted 0.90 at NURSERY.
    assert decision["decision_index_value"] == approx2(91.40)
    line = validate_success(api.get_line(net.line_a_id, DIRECTOR_HEADERS))
    assert line["pipeline_stage"] == PipelineStage.STAGE_1
    assert line["advancement_readiness"] == AdvancementReadiness.NOT_READY
    program = validate_success(api.get_program(net.program_id, DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 56
    assert program["plot_budget_remaining"] == 4944
