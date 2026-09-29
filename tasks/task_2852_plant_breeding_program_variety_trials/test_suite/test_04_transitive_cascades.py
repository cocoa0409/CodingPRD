"""
Side-effect chains that reach four levels down from a single request whose body
names none of the records it touches.
"""

from test_helpers import (
    AGRONOMIST_HEADERS,
    DIRECTOR_HEADERS,
    PLANNER_HEADERS,
    REGULATORY_THIRD_HEADERS,
    SCIENTIST_HEADERS,
    AgreementStatus,
    ApiErrorId,
    BackcrossStatus,
    CapacityPosture,
    DecisionType,
    EntryStatus,
    HoldReason,
    LotStatus,
    PipelineStage,
    SeriesStatus,
    StewardshipStatus,
    WithdrawalReason,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


def _line_ready_to_discard(api):
    """
    Line A carrying an analysed series, an open entry in a second series, a
    RESERVED seed lot and an ACTIVE backcross project.
    """
    base = fixtures.program_objective_and_two_lines(
        api, program_overrides={"name": "Soy Cascade"}
    )
    site = fixtures.create_site(api, site_code="DS1", total_plot_capacity=60)
    series = fixtures.create_series(api, base.program_id, min_locations=1)
    entry_a1 = fixtures.create_entry(api, series["id"], base.line_a_id, site["id"])
    entry_b1 = fixtures.create_entry(api, series["id"], base.line_b_id, site["id"])
    fixtures.plant_series(api, series["id"])
    fixtures.record_yield_reps(api, entry_a1["id"], [15.0, 15.0, 15.0])
    fixtures.record_yield_reps(api, entry_b1["id"], [14.0, 14.0, 14.0])
    fixtures.finalize_entry(api, entry_a1["id"])
    fixtures.finalize_entry(api, entry_b1["id"])
    fixtures.run_analysis(api, series["id"])

    series2 = fixtures.create_series(api, base.program_id, min_locations=1)
    entry_a2 = fixtures.create_entry(
        api, series2["id"], base.line_a_id, site["id"], plot_count=12
    )

    fixtures.approved_agreement(
        api,
        base.line_a_id,
        markets=["US_CORNBELT", "CA_PRAIRIE", "MX_BAJIO"],
        regulatory_dossier_ref="DOS-2852-04",
        grower_agreement_ref="GA-2852-04",
    )
    lot = fixtures.reserve_lot(
        api,
        base.line_a_id,
        "US_CORNBELT",
        [
            factories.allocation("US_CORNBELT", 4000),
            factories.allocation("CA_PRAIRIE", 9000),
            factories.allocation("MX_BAJIO", 1300),
        ],
    )
    project = validate_success(
        api.create_backcross(
            factories.backcross_payload(base.line_a_id, base.line_b_id),
            SCIENTIST_HEADERS,
        ),
        201,
    )

    base.site_id = site["id"]
    base.series_id = series["id"]
    base.series2_id = series2["id"]
    base.entry_a1_id = entry_a1["id"]
    base.entry_b1_id = entry_b1["id"]
    base.entry_a2_id = entry_a2["id"]
    base.lot_id = lot["id"]
    base.project_id = project["id"]
    return base


def test_discard_withdraws_open_entries_and_redemands_site_and_programme(api):
    """
    The DISCARD names no entry, yet the open entry in the unplanted second
    series is withdrawn and the site and programme counters follow it down.

    PRD 3.8: "First the line itself: `pipeline_stage` becomes `DISCARDED`, its
    `version` increments, and `stewardship_status` is frozen at whatever value it
    held."
    PRD 3.8: "Then the trial entries: every entry of this line whose `status` is
    `ENTERED` or `PLANTED` becomes `WITHDRAWN` with `withdrawal_reason` set to
    `LINE_DISCARDED`, processed in `created_at` ascending order, each entry's
    `version` incrementing; each such withdrawal re-derives that entry's site —
    `peak_committed_plot_count`, `available_plot_count` and `capacity_posture`,
    which may relax `FROZEN → RESTRICTED → OPEN` — and drops the withdrawn
    `plot_count` from the programme's `committed_plot_count` with
    `plot_budget_remaining` recomputed, while the programme's `active_line_count`
    falls by one for the discarded line."

    Design: Difficulty/transitive_cascade/line_discard_cascades_entries_sites_program_lots_and_backcross
    """
    net = _line_ready_to_discard(api)
    decision = fixtures.record_decision(
        api,
        net.line_a_id,
        net.series_id,
        decision=DecisionType.DISCARD,
        granted_plots=0,
        rationale="SDS score fails the market spec",
    )

    line_a = validate_success(api.get_line(net.line_a_id, DIRECTOR_HEADERS))
    assert line_a["pipeline_stage"] == PipelineStage.DISCARDED
    assert line_a["stewardship_status"] == StewardshipStatus.APPROVED

    withdrawn = validate_success(api.get_entry(net.entry_a2_id, AGRONOMIST_HEADERS))
    assert withdrawn["status"] == EntryStatus.WITHDRAWN
    assert withdrawn["withdrawal_reason"] == WithdrawalReason.LINE_DISCARDED
    # Terminal siblings are left alone: the cascade only touches open entries.
    for entry_id in (net.entry_a1_id, net.entry_b1_id):
        entry = validate_success(api.get_entry(entry_id, AGRONOMIST_HEADERS))
        assert entry["status"] == EntryStatus.HARVESTED

    site = validate_success(api.get_site(net.site_id, AGRONOMIST_HEADERS))
    assert site["peak_committed_plot_count"] == 16
    assert site["available_plot_count"] == 44
    assert site["capacity_posture"] == CapacityPosture.OPEN

    program = validate_success(api.get_program(net.program_id, DIRECTOR_HEADERS))
    assert program["committed_plot_count"] == 16
    assert program["plot_budget_remaining"] == 4984
    assert program["active_line_count"] == 1

    series2 = validate_success(api.get_series(net.series2_id, AGRONOMIST_HEADERS))
    assert series2["entry_count"] == 0
    assert series2["status"] == SeriesStatus.PLANNING
    assert decision["from_stage"] == PipelineStage.NURSERY
    assert decision["to_stage"] == PipelineStage.DISCARDED
    assert decision["is_superseded"] is False


def test_discard_refunds_the_seed_lot_and_terminates_the_backcross(api):
    """
    The lot branch and the backcross branch of the same cascade run without ever
    being named, and the seed the lot had reserved comes back.

    PRD 3.8: "Only when the entry cascade has run to completion do the seed lots
    follow: every seed increase lot of this line whose `status` is `RESERVED`,
    `IN_PRODUCTION` or `ON_HOLD` becomes `CANCELLED` with `hold_reason` set to
    `LINE_DISCARDED`, again in `created_at` ascending order, and each cancellation
    credits that lot's `allocated_seed_g` back to the line's `seed_inventory_g`
    and re-derives `reserved_seed_g` and `planned_launch_units_bags`, after which
    the programme's `pre_commercial_units_bags` is recomputed."
    PRD 3.8: "Only when the seed lots have all been cancelled do the backcross
    projects follow: every backcross project whose `recurrent_line_id` is this
    line and whose `status` is `ACTIVE` becomes `TERMINATED`, with no trait score
    written to the recurrent line."

    Design: Difficulty/transitive_cascade/line_discard_cascades_entries_sites_program_lots_and_backcross
    """
    net = _line_ready_to_discard(api)
    fixtures.record_decision(
        api, net.line_a_id, net.series_id, decision=DecisionType.DISCARD
    )

    lot = validate_success(api.get_lot(net.lot_id, PLANNER_HEADERS))
    assert lot["status"] == LotStatus.CANCELLED
    assert lot["hold_reason"] == HoldReason.LINE_DISCARDED

    line_a = validate_success(api.get_line(net.line_a_id, DIRECTOR_HEADERS))
    assert line_a["seed_inventory_g"] == 500000
    assert line_a["reserved_seed_g"] == 0
    assert line_a["planned_launch_units_bags"] == 0

    program = validate_success(api.get_program(net.program_id, DIRECTOR_HEADERS))
    assert program["pre_commercial_units_bags"] == 0

    project = validate_success(api.get_backcross(net.project_id, SCIENTIST_HEADERS))
    assert project["status"] == BackcrossStatus.TERMINATED
    # A terminated conversion writes no resistance score, so SDS stays at 7.
    assert line_a["disease_resistance_scores"]["SDS"] == 7


def _line_with_two_lots(api):
    """Line SX-5001 with one IN_PRODUCTION lot and one RESERVED lot."""
    program_id, objective_id = fixtures.program_with_objective(
        api, program_overrides={"name": "Soy Suspend"}
    )
    line = fixtures.create_line(
        api,
        program_id,
        objective_id,
        designation="SX-5001",
        seed_inventory_g=500000,
        disease_resistance_scores={"RUST": 8, "SDS": 7},
        quality_trait_values={"PROTEIN": 13.4},
    )
    agreement = fixtures.approved_agreement(
        api,
        line["id"],
        markets=["US_CORNBELT", "CA_PRAIRIE"],
        regulatory_dossier_ref="DOS-2852-05",
        grower_agreement_ref="GA-2852-05",
    )
    lot1 = fixtures.reserve_lot(
        api, line["id"], "US_CORNBELT", [factories.allocation("US_CORNBELT", 4000)]
    )
    validate_success(api.start_lot_production(lot1["id"], PLANNER_HEADERS))
    lot2 = fixtures.reserve_lot(
        api, line["id"], "CA_PRAIRIE", [factories.allocation("CA_PRAIRIE", 9000)]
    )
    return {
        "program_id": program_id,
        "line_id": line["id"],
        "agreement_id": agreement["id"],
        "lot1_id": lot1["id"],
        "lot2_id": lot2["id"],
    }


def test_suspension_parks_reserved_and_in_production_lots_and_zeroes_the_rollups(api):
    """
    A suspension by a third officer reaches lots in two different states and
    collapses both launch-volume rollups to zero.

    PRD 3.9: "Because of that, every seed increase lot of the line whose `status`
    is `RESERVED` or `IN_PRODUCTION` moves to `ON_HOLD` with `hold_reason` set to
    `STEWARDSHIP_SUSPENDED`, processed in `created_at` ascending order, and each
    lot keeps its `allocated_seed_g` debited from the line so the seed ledger does
    not drift."
    PRD 3.9: "And because those lots have left the planned set, the line's
    `planned_launch_units_bags` and the programme's `pre_commercial_units_bags`
    are both recomputed."

    Design: Difficulty/transitive_cascade/stewardship_suspension_cascades_lots_line_bags_and_program_rollup
    """
    net = _line_with_two_lots(api)
    line_before = validate_success(api.get_line(net["line_id"], DIRECTOR_HEADERS))
    assert line_before["planned_launch_units_bags"] == 562

    agreement = validate_success(
        api.suspend_agreement(
            net["agreement_id"],
            factories.suspend_payload("refuge compliance audit failed in CA_PRAIRIE"),
            REGULATORY_THIRD_HEADERS,
        )
    )
    assert agreement["status"] == AgreementStatus.SUSPENDED
    assert agreement["suspension_reason"] == "refuge compliance audit failed in CA_PRAIRIE"

    line = validate_success(api.get_line(net["line_id"], DIRECTOR_HEADERS))
    assert line["stewardship_status"] == StewardshipStatus.SUSPENDED
    assert line["pipeline_stage"] == PipelineStage.NURSERY

    for lot_id in (net["lot1_id"], net["lot2_id"]):
        lot = validate_success(api.get_lot(lot_id, PLANNER_HEADERS))
        assert lot["status"] == LotStatus.ON_HOLD
        assert lot["hold_reason"] == HoldReason.STEWARDSHIP_SUSPENDED

    assert line["planned_launch_units_bags"] == 0
    program = validate_success(api.get_program(net["program_id"], DIRECTOR_HEADERS))
    assert program["pre_commercial_units_bags"] == 0


def test_suspension_leaves_the_seed_debited_and_blocks_new_reservations(api):
    """
    Unlike a cancellation, going on hold refunds nothing, and the line can take
    no further reservation while it is suspended.

    PRD 3.9: "**Going on hold** is never requested directly; `RESERVED` and
    `IN_PRODUCTION` lots reach `ON_HOLD` only through the stewardship suspension
    cascade described above, and the seed stays debited while they sit there."
    PRD 3.9: "`reserved_seed_g` is the sum of `allocated_seed_g` over the line's
    lots whose `status` is `RESERVED`, `IN_PRODUCTION` or `ON_HOLD`, excluding
    `COMPLETED` and `CANCELLED` lots."
    PRD 3.9: "Two regulatory gates precede any arithmetic: the line's
    `stewardship_status` must be `APPROVED`, so both `NOT_REQUIRED` and `PENDING`
    fail with `ERR_STEWARDSHIP_NOT_APPROVED`, and a line whose stewardship has
    been withdrawn fails with `ERR_STEWARDSHIP_SUSPENDED`."

    Design: Difficulty/transitive_cascade/stewardship_suspension_cascades_lots_line_bags_and_program_rollup
    """
    net = _line_with_two_lots(api)
    validate_success(
        api.suspend_agreement(
            net["agreement_id"],
            factories.suspend_payload("refuge compliance audit failed in CA_PRAIRIE"),
            REGULATORY_THIRD_HEADERS,
        )
    )

    line = validate_success(api.get_line(net["line_id"], DIRECTOR_HEADERS))
    # 108125 for the 173-bag lot plus 243125 for the 389-bag lot, still debited.
    assert line["seed_inventory_g"] == 148750
    assert line["reserved_seed_g"] == 351250

    validate_error(
        api.create_lot(
            factories.lot_payload(
                net["line_id"], "US_CORNBELT", [factories.allocation("US_CORNBELT", 1000)]
            ),
            PLANNER_HEADERS,
        ),
        ApiErrorId.STEWARDSHIP_SUSPENDED,
        409,
    )
