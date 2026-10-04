"""Difficulty queue — validation-priority pairs and cross-entity state gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_irb_protocol,
    create_analysis_plan_payload,
    create_design_plan,
    create_record_payload,
    create_report,
    create_wave,
    design_plan_decision_payload,
    get_participant,
    get_wave,
    open_wave,
    set_clock,
    setup_active_site_study,
    setup_participant_at_burden_cap,
    setup_study_with_locked_plan,
    setup_study_with_sites,
    validate_error,
    validate_paginated,
    validate_success,
)

AO = TEST_USERS["agency_officer_headers"]
PI = TEST_USERS["principal_investigator_headers"]
SD = TEST_USERS["study_director_headers"]
DM = TEST_USERS["data_manager_headers"]


def test_wave_open_irb_expired_beats_window_not_started(api):
    """PRD §2.8: "Every mutating request passes through a fixed pipeline of
    validation stages, and the pipeline is ordered: the first failing stage
    determines the error returned, so a caller can never observe a later-stage
    error while an earlier-stage failure is present." (Human-subjects
    compliance — `ERR_IRB_EXPIRED` — is stage 7; wave windows —
    `ERR_WAVE_WINDOW_NOT_STARTED` — are stage 8.)
    PRD §3.3: "if approved protocols exist but every approval window has
    passed, the rejection is `ERR_IRB_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/wave_open_irb_expired_beats_window_not_started
    """
    ctx = setup_study_with_locked_plan()  # RECRUITMENT, plan LOCKED
    study_id = ctx["study"]["id"]
    approve_irb_protocol(study_id)  # window [2026-09-01, 2027-09-01)
    wave = create_wave(
        study_id, wave_type="SURVEY",
        open_at="2027-11-01T00:00:00Z", close_at="2027-12-01T00:00:00Z",
    )

    # IRB expired (2027-09-01 passed) AND the wave window has not started.
    set_clock("2027-10-01T00:00:00Z")
    resp = api.open_wave(wave["id"], DM)
    validate_error(resp, ApiErrorId.ERR_IRB_EXPIRED)
    assert resp.json()["data"]["error_id"] != "ERR_WAVE_WINDOW_NOT_STARTED"
    assert get_wave(wave["id"])["status"] == "PLANNED"


def test_record_create_wave_not_open_beats_burden_cap(api):
    """PRD §2.8: "Every mutating request passes through a fixed pipeline of
    validation stages, and the pipeline is ordered: the first failing stage
    determines the error returned, so a caller can never observe a later-stage
    error while an earlier-stage failure is present." (State validity —
    `ERR_WAVE_NOT_OPEN` — is stage 6; the burden cap — `ERR_BURDEN_CAP_EXCEEDED`
    — is stage 7.)
    PRD §3.6: "While a wave is `OPEN`, a `DataManager` adds a **ResponseRecord**
    to it — any other wave state is rejected with `ERR_WAVE_NOT_OPEN`."
    PRD §3.6: "a total landing at exactly 480 is allowed."

    Design: Difficulty/priority_pair_validation_conflict/record_create_wave_not_open_beats_burden_cap
    """
    ctx = setup_participant_at_burden_cap()
    p1 = ctx["participant"]
    wave = ctx["wave_visit"]
    assert ctx["record"]["billed_minutes"] == 480, (
        "round_half_up(384 * 1.25) = 480 — exactly at the cap, allowed"
    )
    assert p1["burden_total_minutes"] == 480

    validate_success(api.close_wave(wave["id"], DM), 200)

    # Wave CLOSED (stage 6) AND one more billed minute would reach 481 (stage 7).
    resp = api.create_record(
        wave["id"],
        create_record_payload(p1["id"], instrument_minutes=1, payload_ref="late-record"),
        DM,
    )
    validate_error(resp, ApiErrorId.ERR_WAVE_NOT_OPEN)
    assert resp.json()["data"]["error_id"] != "ERR_BURDEN_CAP_EXCEEDED"
    assert get_participant(p1["id"])["burden_total_minutes"] == 480


def test_site_activate_gated_by_irb_and_locked_design(api):
    """PRD §3.4: "Activation then moves a `RECRUITED` site to `ACTIVE`, but
    only behind two gates: the study must hold an `APPROVED` IRB protocol whose
    window covers the current logical time (`ERR_NO_APPROVED_IRB` when none is
    approved, `ERR_IRB_EXPIRED` when every approved window has passed), and the
    study's current design plan must be `LOCKED` (otherwise
    `ERR_DESIGN_PLAN_INVALID_STATE`)."
    PRD §2.8: "The state-stage errors are `ERR_CONTRACT_NOT_ACTIVE`,
    `ERR_STUDY_INVALID_STATE`, `ERR_DESIGN_PLAN_INVALID_STATE`,
    `ERR_IRB_INVALID_STATE`, `ERR_SITE_INVALID_STATE`,
    `ERR_PARTICIPANT_INVALID_STATE`, `ERR_WAVE_INVALID_STATE`,
    `ERR_ANALYSIS_PLAN_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`,
    `ERR_RUF_INVALID_STATE`, `ERR_DISSEMINATION_INVALID_STATE`, and
    `ERR_WAVE_NOT_OPEN` (each HTTP 409)." (Stage 6, ahead of the stage-7
    compliance errors `ERR_NO_APPROVED_IRB` / `ERR_IRB_EXPIRED`, so the DRAFT
    plan's state failure is the one reported.)

    Design: Difficulty/cross_entity_state_dependency/site_activate_gated_by_irb_and_locked_design
    """
    ctx = setup_study_with_sites(
        site_specs=((60, "RECRUITED"), (300, "CONTACTED"), (300, "CONTACTED"))
    )
    study_id = ctx["study"]["id"]
    site_a = ctx["site"]
    plan = create_design_plan(study_id)  # stays DRAFT

    resp = api.activate_site(site_a["id"], SD)
    validate_error(resp, ApiErrorId.ERR_DESIGN_PLAN_INVALID_STATE)

    validate_success(api.submit_design_plan(plan["id"], PI), 200)
    validate_success(
        api.design_plan_agency_decision(plan["id"], design_plan_decision_payload("APPROVED"), AO),
        200,
    )  # auto-LOCKED: site A already RECRUITED

    resp = api.activate_site(site_a["id"], SD)
    validate_error(resp, ApiErrorId.ERR_NO_APPROVED_IRB)

    approve_irb_protocol(study_id)
    site = validate_success(api.activate_site(site_a["id"], SD), 200)
    assert site["status"] == "ACTIVE"


def test_report_submit_requires_preregistered_plan(api):
    """PRD §3.7: "Two integrity gates apply at every submission: the study must
    hold a `PREREGISTERED` analysis plan (otherwise
    `ERR_ANALYSIS_PLAN_NOT_REGISTERED`), and the report's
    `addressed_primary_outcomes` must include every code in that plan's frozen
    `primary_outcomes`."
    PRD §3.7: "requires that no wave of the study has yet reached `CLOSED` or
    `LINKED`: preregistration must precede unblinded data, and a late attempt
    is rejected with `ERR_PREREGISTRATION_TOO_LATE`."

    Design: Difficulty/cross_entity_state_dependency/report_submit_requires_preregistered_plan
    """
    ctx = setup_active_site_study()
    study_id = ctx["study"]["id"]
    aplan = validate_success(
        api.create_analysis_plan(study_id, create_analysis_plan_payload(), PI), 201
    )  # left in DRAFT — never registered
    wave = create_wave(study_id)
    open_wave(wave["id"])
    validate_success(api.close_wave(wave["id"], DM), 200)  # study -> ANALYSIS
    report = create_report(study_id)  # study -> REPORTING

    resp = api.submit_report(report["id"], PI)
    validate_error(resp, ApiErrorId.ERR_ANALYSIS_PLAN_NOT_REGISTERED)

    resp = api.register_analysis_plan(aplan["id"], PI)
    validate_error(resp, ApiErrorId.ERR_PREREGISTRATION_TOO_LATE)

    reports, _ = validate_paginated(api.list_reports(study_id, PI))
    assert next(r for r in reports if r["id"] == report["id"])["status"] == "DRAFT"
    plans, _ = validate_paginated(api.list_analysis_plans(study_id, PI))
    assert next(p for p in plans if p["id"] == aplan["id"])["status"] == "DRAFT"
