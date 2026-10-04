"""Production run gates and loops: the rework cycle's compounding yield loss,
the spec-lock and agreement-state cross-entity gates, facility quarantine
gating, and the line schedule's changeover buffer."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_run,
    create_production_run_payload,
    deliver_lot,
    make_active_agreement,
    make_agreement,
    make_run,
    make_run_in_qa_hold,
    make_spec,
    make_validated_spec,
    record_reading,
    setup_full_pipeline,
    validate_error,
    validate_paginated,
    validate_spec,
    validate_success,
)

QA = TEST_USERS["qa_lead_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
ACCOUNT = TEST_USERS["account_manager_headers"]


def test_rework_loop_recomputes_cases_with_loss(api):
    """PRD §3.6: "On a re-entry after rework, the figure is the previous
    `actual_cases` multiplied by 0.96 — a 4 percent rework loss — again
    rounded down to whole cases."
    PRD §3.6: "Execution advances one stage at a time, driven by a
    `ProductionPlanner`: `SCHEDULED` to `CUTTING` to `BLANCHING` to `COATING`
    to `FREEZING` to `QA_HOLD`, with the rework path re-entering from `REWORK`
    to `COATING`."
    PRD §3.6: "a release moves the run to `RELEASED`, transitions every input
    lot from `ALLOCATED` to `CONSUMED`, and adds the run's `actual_cases` to
    the agreement's `lifetime_released_cases`."

    Design: Difficulty/non_linear_state_machine/production_run_rework_loop_recomputes_cases_with_loss
    """
    world = setup_full_pipeline(api=api)
    run = make_run_in_qa_hold(world["line"]["id"], world["spec"]["id"],
                              world["agreement"]["id"], [world["lot"]["id"]], api=api)
    assert run["actual_cases"] == 620, "first pass: floor(1000.0 x 0.62)"

    reworked = validate_success(api.rework_run(run["id"], QA))
    assert reworked["status"] == "REWORK" and reworked["rework_count"] == 1

    back = advance_run(run["id"], times=3, api=api)  # REWORK -> COATING -> FREEZING -> QA_HOLD
    assert back["status"] == "QA_HOLD"
    assert back["rework_count"] == 1
    assert back["actual_cases"] == 595, f"floor(620 x 0.96) = 595 on re-entry, got {back['actual_cases']}"

    released = validate_success(api.qa_release_run(run["id"], {"measured_color_units": 2.5}, QA))
    assert released["status"] == "RELEASED"
    lot = validate_success(api.get_potato_lot(world["lot"]["id"], QA))
    assert lot["status"] == "CONSUMED"


def test_rework_loop_second_cycle_compounds_the_loss(api):
    """PRD §3.6: "Every entry into `QA_HOLD`, whether the first pass or a
    re-entry after rework, computes the run's `actual_cases`."
    PRD §3.6: "On a re-entry after rework, the figure is the previous
    `actual_cases` multiplied by 0.96 — a 4 percent rework loss — again
    rounded down to whole cases."

    Design: Difficulty/non_linear_state_machine/production_run_rework_loop_recomputes_cases_with_loss
    """
    world = setup_full_pipeline(api=api)
    run = make_run_in_qa_hold(world["line"]["id"], world["spec"]["id"],
                              world["agreement"]["id"], [world["lot"]["id"]], api=api)
    validate_success(api.rework_run(run["id"], QA))
    second = advance_run(run["id"], times=3, api=api)
    assert second["actual_cases"] == 595

    validate_success(api.rework_run(run["id"], QA))
    third = advance_run(run["id"], times=3, api=api)
    assert third["status"] == "QA_HOLD"
    assert third["rework_count"] == 2
    assert third["actual_cases"] == 571, (
        f"floor(595 x 0.96) = 571 after the second rework, got {third['actual_cases']}"
    )

    released = validate_success(api.qa_release_run(run["id"], {"measured_color_units": 2.5}, QA))
    assert released["status"] == "RELEASED"
    agreement = validate_success(api.get_supply_agreement(world["agreement"]["id"], ACCOUNT))
    assert agreement["lifetime_released_cases"] == 571


def test_run_create_requires_spec_locked_not_just_validated(api):
    """PRD §3.6: "Creation enforces a chain of gates. The specification must
    be `LOCKED` (`ERR_SPEC_NOT_LOCKED`), and the specification's `cut_family`
    must appear among the line's `supported_cut_families`
    (`ERR_CUT_FAMILY_UNSUPPORTED`)."
    PRD §3.4: "Locking happens implicitly: the first time a supply agreement
    referencing a `VALIDATED` specification is activated, the specification
    transitions to `LOCKED`, sets `ever_locked` to true, and increments its
    `version`."

    Design: Difficulty/cross_entity_state_dependency/run_create_requires_spec_locked_not_just_validated
    """
    world = setup_full_pipeline(api=api)  # spec_a LOCKED, agreement ACTIVE on it
    # A second spec that is merely VALIDATED: no agreement ever locked it.
    spec_pending = make_spec(world["chain"]["id"], api=api, spec_code="SP-A-2",
                             cut_family="CRINKLE", cut_size_mm=10.0)
    validate_spec(spec_pending["id"], panel_score=8.0, api=api)

    resp = api.create_production_run(
        create_production_run_payload(
            world["line"]["id"], spec_pending["id"], world["agreement"]["id"],
            [world["lot"]["id"]],
        ),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_SPEC_NOT_LOCKED)
    assert resp.status_code == 409, "VALIDATED is not enough; only first activation locks a spec"
    runs, _ = validate_paginated(
        api.list_production_runs(PLANNER, params={"agreement_id": world["agreement"]["id"]})
    )
    assert runs == []


def test_run_create_with_locked_spec_but_draft_agreement_fails(api):
    """PRD §3.6: "The agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`),
    must not carry a stale spec pin (`ERR_SPEC_REVISION_STALE`), and must
    belong to a chain in good standing".

    Design: Difficulty/cross_entity_state_dependency/run_create_requires_spec_locked_not_just_validated
    """
    world = setup_full_pipeline(api=api)  # spec LOCKED via the first agreement
    draft = make_agreement(world["chain"]["id"], world["spec"]["id"], api=api,
                           weekly_contracted_cases=2000)

    resp = api.create_production_run(
        create_production_run_payload(
            world["line"]["id"], world["spec"]["id"], draft["id"], [world["lot"]["id"]],
        ),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
    assert resp.status_code == 409, "the spec lock is satisfied; only the DRAFT agreement fails"
    runs, _ = validate_paginated(api.list_production_runs(PLANNER, params={"agreement_id": draft["id"]}))
    assert runs == []


def test_run_create_blocked_by_quarantined_source_facility(api):
    """PRD §2.8: "Receiving a new lot into a `QUARANTINED` facility is
    rejected with `ERR_FACILITY_QUARANTINED` (HTTP 409), and scheduling a
    production run that would consume a lot stored in a `QUARANTINED` facility
    is rejected with the same error."
    PRD §3.6: "Every input lot must be `IN_STORAGE` (`ERR_LOT_NOT_AVAILABLE`)
    and held in a facility that is not `QUARANTINED` (`ERR_FACILITY_QUARANTINED`)."

    Design: Difficulty/cross_entity_state_dependency/run_create_blocked_by_quarantined_source_facility
    """
    world = setup_full_pipeline(api=api)
    record_reading(
        world["facility"]["id"], api=api,
        recorded_at="2026-09-02T06:00:00Z", temperature_f=41.0, humidity_pct=93.0,
        co2_pct=4.2, sprout_index=4.2, disease_incidence_pct=2.0,
    )  # sprout 4.2 >= 4.0 -> QUARANTINED

    resp = api.create_production_run(
        create_production_run_payload(
            world["line"]["id"], world["spec"]["id"], world["agreement"]["id"],
            [world["lot"]["id"]],
            scheduled_start="2026-09-03T08:00:00Z", scheduled_end="2026-09-03T10:00:00Z",
        ),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_QUARANTINED)
    assert resp.status_code == 409, "the run's feasibility depends on the lot's facility posture"

    lot = validate_success(api.get_potato_lot(world["lot"]["id"], QA))
    assert lot["status"] == "IN_STORAGE", "no allocation happened"
    runs, _ = validate_paginated(api.list_production_runs(PLANNER, params={"line_id": world["line"]["id"]}))
    assert runs == []


def test_run_create_succeeds_after_quarantine_clears(api):
    """PRD §2.8: "Lots already inside a quarantined facility are not destroyed
    — they simply cannot move until the posture clears."
    PRD §3.3: "Each new reading recomputes the facility's `posture` from the
    latest reading alone — the one with the greatest `recorded_at`, with ties
    broken in favor of the reading appended last."

    Design: Difficulty/cross_entity_state_dependency/run_create_blocked_by_quarantined_source_facility
    """
    world = setup_full_pipeline(api=api)
    record_reading(
        world["facility"]["id"], api=api,
        recorded_at="2026-09-02T06:00:00Z", temperature_f=41.0, humidity_pct=93.0,
        co2_pct=4.2, sprout_index=4.2, disease_incidence_pct=2.0,
    )  # QUARANTINED
    record_reading(
        world["facility"]["id"], api=api,
        recorded_at="2026-09-02T12:00:00Z", temperature_f=38.0, humidity_pct=90.0,
        co2_pct=3.0, sprout_index=1.0, disease_incidence_pct=1.0,
    )  # later reading clears every threshold -> NORMAL

    run = make_run(world["line"]["id"], world["spec"]["id"], world["agreement"]["id"],
                   [world["lot"]["id"]], api=api,
                   scheduled_start="2026-09-03T08:00:00Z",
                   scheduled_end="2026-09-03T10:00:00Z")
    assert run["status"] == "SCHEDULED"
    lot = validate_success(api.get_potato_lot(world["lot"]["id"], QA))
    assert lot["status"] == "ALLOCATED", "once the posture clears, the lot may move"


def test_line_schedule_cut_family_changeover_buffer(api):
    """PRD §3.6: "When the windows are disjoint or merely touching, a
    cut-family change demands a changeover buffer: if the candidate's
    `cut_family` differs from the existing run's, the gap between the
    intervals (the candidate's start minus the existing run's end when the
    candidate follows, or the existing run's start minus the candidate's end
    when it precedes) must be at least 60 minutes; any smaller gap, including
    exact adjacency, is rejected with `ERR_LINE_SCHEDULE_CONFLICT`. Runs of
    the same cut family may follow each other with any gap of zero or more,
    exact adjacency included."

    Design: Difficulty/resource_temporal_overlap/line_schedule_cut_family_changeover_buffer
    """
    world = setup_full_pipeline(api=api)
    lot_b = deliver_lot(world["contract"]["id"], world["facility"]["id"],
                        world["grower"]["id"], api=api)
    lot_c = deliver_lot(world["contract"]["id"], world["facility"]["id"],
                        world["grower"]["id"], api=api)
    spec_cr = make_validated_spec(world["chain"]["id"], api=api, spec_code="SP-A-2",
                                  cut_family="CRINKLE", cut_size_mm=10.0,
                                  coating_type="CLEAR", target_color_units=2.5,
                                  max_cook_time_sec=200)
    agr_cr = make_active_agreement(world["chain"]["id"], spec_cr["id"], api=api,
                                   weekly_contracted_cases=5000, price_per_case_cents=320)
    r1 = make_run(world["line"]["id"], world["spec"]["id"], world["agreement"]["id"],
                  [world["lot"]["id"]], api=api)  # STRAIGHT 2026-09-02 08:00-10:00

    adjacent_crinkle = api.create_production_run(
        create_production_run_payload(
            world["line"]["id"], spec_cr["id"], agr_cr["id"], [lot_b["id"]],
            scheduled_start="2026-09-02T10:00:00Z", scheduled_end="2026-09-02T11:00:00Z",
        ),
        PLANNER,
    )
    validate_error(adjacent_crinkle, ApiErrorId.ERR_LINE_SCHEDULE_CONFLICT)
    assert adjacent_crinkle.status_code == 409, (
        "exact adjacency with a family change is 0 minutes < the 60-minute buffer"
    )

    buffered = make_run(world["line"]["id"], spec_cr["id"], agr_cr["id"], [lot_b["id"]],
                        api=api, scheduled_start="2026-09-02T11:00:00Z",
                        scheduled_end="2026-09-02T12:00:00Z")
    assert buffered["status"] == "SCHEDULED", "exactly 60 minutes satisfies the inclusive buffer"

    same_family = make_run(world["line"]["id"], spec_cr["id"], agr_cr["id"], [lot_c["id"]],
                           api=api, scheduled_start="2026-09-02T12:00:00Z",
                           scheduled_end="2026-09-02T12:30:00Z")
    assert same_family["status"] == "SCHEDULED", "same family needs no buffer, adjacency included"

    runs, _ = validate_paginated(api.list_production_runs(PLANNER, params={"line_id": world["line"]["id"]}))
    assert len(runs) == 3


def test_line_schedule_strict_overlap_and_preceding_family_change(api):
    """PRD §3.6: "If the windows strictly overlap — the existing run starts
    before the candidate ends and the candidate starts before the existing run
    ends — creation is always rejected with `ERR_LINE_SCHEDULE_CONFLICT`."
    PRD §3.6: "the gap between the intervals (the candidate's start minus the
    existing run's end when the candidate follows, or the existing run's start
    minus the candidate's end when it precedes) must be at least 60 minutes".

    Design: Difficulty/resource_temporal_overlap/line_schedule_cut_family_changeover_buffer
    """
    world = setup_full_pipeline(api=api)
    lot_b = deliver_lot(world["contract"]["id"], world["facility"]["id"],
                        world["grower"]["id"], api=api)
    spec_cr = make_validated_spec(world["chain"]["id"], api=api, spec_code="SP-A-2",
                                  cut_family="CRINKLE", cut_size_mm=10.0,
                                  coating_type="CLEAR", target_color_units=2.5,
                                  max_cook_time_sec=200)
    agr_cr = make_active_agreement(world["chain"]["id"], spec_cr["id"], api=api,
                                   weekly_contracted_cases=5000, price_per_case_cents=320)
    make_run(world["line"]["id"], world["spec"]["id"], world["agreement"]["id"],
             [world["lot"]["id"]], api=api)  # STRAIGHT 08:00-10:00

    overlap = api.create_production_run(
        create_production_run_payload(
            world["line"]["id"], world["spec"]["id"], world["agreement"]["id"], [lot_b["id"]],
            scheduled_start="2026-09-02T09:30:00Z", scheduled_end="2026-09-02T10:30:00Z",
        ),
        PLANNER,
    )
    validate_error(overlap, ApiErrorId.ERR_LINE_SCHEDULE_CONFLICT)
    assert overlap.status_code == 409, "strict overlap conflicts even within one family"

    preceding_adjacent = api.create_production_run(
        create_production_run_payload(
            world["line"]["id"], spec_cr["id"], agr_cr["id"], [lot_b["id"]],
            scheduled_start="2026-09-02T06:00:00Z", scheduled_end="2026-09-02T08:00:00Z",
        ),
        PLANNER,
    )
    validate_error(preceding_adjacent, ApiErrorId.ERR_LINE_SCHEDULE_CONFLICT)
    assert preceding_adjacent.status_code == 409, (
        "a preceding family change with a 0-minute gap also violates the buffer"
    )

    preceding_buffered = make_run(world["line"]["id"], spec_cr["id"], agr_cr["id"], [lot_b["id"]],
                                  api=api, scheduled_start="2026-09-02T06:00:00Z",
                                  scheduled_end="2026-09-02T07:00:00Z")
    assert preceding_buffered["status"] == "SCHEDULED", (
        "07:00 end leaves exactly 60 minutes before the 08:00 STRAIGHT run"
    )
