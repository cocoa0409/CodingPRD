"""Corner queue — state-machine valid/invalid transitions and terminal-state
lockdowns across the study lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_participant,
    add_record,
    consent_payload,
    create_design_plan,
    create_dissemination_activity_payload,
    create_report,
    create_study_payload,
    create_wave,
    get_contract,
    get_study,
    get_wave,
    make_participant_headers,
    open_wave,
    report_decision_payload,
    setup_active_site_study,
    setup_contract_with_study,
    setup_registered_analysis_plan,
    setup_study_with_locked_plan,
    setup_study_with_sites,
    setup_submitted_report,
    terminate_contract_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

AO = TEST_USERS["agency_officer_headers"]
PI = TEST_USERS["principal_investigator_headers"]
SD = TEST_USERS["study_director_headers"]
DM = TEST_USERS["data_manager_headers"]
PEER = TEST_USERS["peer_reviewer_headers"]


def _find(items, entity_id):
    return next(e for e in items if e["id"] == entity_id)


def test_design_plan_submit_twice_rejected(api):
    """PRD §3.2: "A `PrincipalInvestigator` submits a plan only from `DRAFT` —
    submission from any other state is rejected with
    `ERR_DESIGN_PLAN_INVALID_STATE`."

    Design: Corner/state_machines/design_plan_submit_twice_rejected
    """
    ctx = setup_study_with_sites()  # one RECRUITED site of 250 clears the gate
    study_id = ctx["study"]["id"]
    plan = create_design_plan(study_id)
    plan = validate_success(api.submit_design_plan(plan["id"], PI), 200)
    assert plan["status"] == "SUBMITTED"

    resp = api.submit_design_plan(plan["id"], PI)
    validate_error(resp, ApiErrorId.ERR_DESIGN_PLAN_INVALID_STATE)
    plans, _ = validate_paginated(api.list_design_plans(study_id, PI))
    assert _find(plans, plan["id"])["status"] == "SUBMITTED"


def test_report_publish_from_submitted_rejected(api):
    """PRD §3.8: "An `AgencyOfficer` publishes an `ACCEPTED` report — any other
    state is rejected with `ERR_REPORT_INVALID_STATE`."

    Design: Corner/state_machines/report_publish_from_submitted_rejected
    """
    ctx = setup_submitted_report()
    resp = api.publish_report(ctx["report"]["id"], AO)
    validate_error(resp, ApiErrorId.ERR_REPORT_INVALID_STATE)
    reports, _ = validate_paginated(api.list_reports(ctx["study"]["id"], PI))
    assert _find(reports, ctx["report"]["id"])["status"] == "SUBMITTED"
    assert get_contract(ctx["contract"]["id"])["disbursed_cents"] == 0, (
        "no premature disbursement"
    )


def test_site_withdraw_from_declined_rejected(api):
    """PRD §3.4: "A `StudyDirector` may withdraw a site from `RECRUITED` or
    `ACTIVE` — from any other state the rejection is `ERR_SITE_INVALID_STATE`."
    PRD §3.4: "moves it to `CONTACTED` when the `outcome` is `CONTACTED`, or to
    the terminal `DECLINED` when the `outcome` is `DECLINED`."

    Design: Corner/state_machines/site_withdraw_from_declined_rejected
    """
    ctx = setup_study_with_sites(site_specs=((40, "DECLINED"),))
    site_d = ctx["site"]
    resp = api.withdraw_site(site_d["id"], SD, {"reason": "late"})
    validate_error(resp, ApiErrorId.ERR_SITE_INVALID_STATE)
    sites, _ = validate_paginated(api.list_sites(ctx["study"]["id"], SD))
    assert _find(sites, site_d["id"])["status"] == "DECLINED"


def test_participant_consent_twice_rejected(api):
    """PRD §3.5: "the participant must be `IDENTIFIED` (otherwise
    `ERR_PARTICIPANT_INVALID_STATE`)."

    Design: Corner/state_machines/participant_consent_twice_rejected
    """
    ctx = setup_active_site_study()
    p1 = add_participant(ctx["site"]["id"], external_ref="P001", consent=True)
    assert p1["status"] == "CONSENTED"

    resp = api.consent_participant(
        p1["id"], consent_payload(1), make_participant_headers(p1["id"])
    )
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_INVALID_STATE)
    sites, _ = validate_paginated(api.list_sites(ctx["study"]["id"], SD))
    assert _find(sites, ctx["site"]["id"])["enrolled_count"] == 1, "no double count"


def test_wave_close_from_planned_rejected(api):
    """PRD §3.6: "Closing — by a `DataManager`, only from `OPEN` (otherwise
    `ERR_WAVE_INVALID_STATE`)."

    Design: Corner/state_machines/wave_close_from_planned_rejected
    """
    ctx = setup_study_with_locked_plan()
    wave = create_wave(ctx["study"]["id"])
    assert wave["status"] == "PLANNED"

    resp = api.close_wave(wave["id"], DM)
    validate_error(resp, ApiErrorId.ERR_WAVE_INVALID_STATE)
    assert get_wave(wave["id"])["status"] == "PLANNED"


def test_terminated_contract_lockdown(api):
    """PRD §3.1: "While a contract lives, its `ACTIVE` status is also the gate
    for creating studies beneath it: attempting to create a study under a
    contract that is not `ACTIVE` fails with `ERR_CONTRACT_NOT_ACTIVE`."
    PRD §3.1: "An `AgencyOfficer` closes out a contract only while it is
    `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`)."
    PRD §3.1: "every non-terminal study of the contract moves to `TERMINATED`."

    Design: Corner/state_machines/terminated_contract_lockdown
    """
    ctx = setup_contract_with_study()
    contract_id = ctx["contract"]["id"]
    validate_success(
        api.terminate_contract(contract_id, terminate_contract_payload("Descoped"), AO), 200
    )

    resp = api.create_study(
        contract_id, create_study_payload(title="S2", research_question="Q2"), PI
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    resp = api.closeout_contract(contract_id, AO)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    assert get_study(ctx["study"]["id"])["status"] == "TERMINATED"


def test_wave_close_validates_then_link_assigns_linkage_keys(api):
    """PRD §3.6: "Closing — by a `DataManager`, only from `OPEN` (otherwise
    `ERR_WAVE_INVALID_STATE`) — moves the wave to `CLOSED` and moves every
    `RECEIVED` record of the wave to `VALIDATED`."
    PRD §3.6: "moves the wave to `LINKED`, at which point every `VALIDATED`
    record moves to `LINKED` and receives its pseudonymous `linkage_key`;
    pseudonymization happens at linkage and not before."

    Design: Corner/state_machines/wave_close_validates_then_link_assigns_linkage_keys
    """
    ctx = setup_active_site_study()
    p1 = add_participant(ctx["site"]["id"], external_ref="P001", consent=True)
    wave = create_wave(ctx["study"]["id"])
    open_wave(wave["id"])
    rec = add_record(wave["id"], p1["id"], instrument_minutes=30, payload_ref="s1")
    assert rec["linkage_key"] is None

    wave = validate_success(api.close_wave(wave["id"], DM), 200)
    assert wave["status"] == "CLOSED"
    records, _ = validate_paginated(api.list_wave_records(wave["id"], DM))
    assert _find(records, rec["id"])["status"] == "VALIDATED"

    wave = validate_success(api.link_wave(wave["id"], DM), 200)
    assert wave["status"] == "LINKED"
    records, _ = validate_paginated(api.list_wave_records(wave["id"], DM))
    rec = _find(records, rec["id"])
    assert rec["status"] == "LINKED"
    assert rec["linkage_key"], "pseudonymous linkage key assigned at linkage"
    assert rec["linkage_key"] != rec["participant_id"], "key is pseudonymous"


def test_study_auto_transitions_full_lifecycle(api):
    """PRD §3.6: "The first wave of a study to reach `OPEN` advances the study
    from `RECRUITMENT` to `DATA_COLLECTION`."
    PRD §3.6: "When a wave closes and no other wave of the study remains in
    `PLANNED`, `OPEN`, or `SUSPENDED` — every other wave having reached
    `CLOSED`, `LINKED`, or `CANCELLED` — a study still in `DATA_COLLECTION`
    advances to `ANALYSIS`."
    PRD §3.7: "The very first report created under an `ANALYSIS` study advances
    the study to `REPORTING`."
    PRD §3.8: "The first report of a study to reach `PUBLISHED` advances the
    study from `REPORTING` to `DISSEMINATION`."
    PRD §3.8: "A study in `DISSEMINATION` moves to `COMPLETED` automatically
    the moment both of its exit conditions hold: the count of its `PUBLISHED`
    reports with `report_type` `FINAL` has reached the contract's
    `deliverable_report_count`, and at least one of its dissemination
    activities has reached `COMPLETED`."
    PRD §3.8: "Completing the study cascades downward: every `ACTIVE` site of
    the study moves to `COMPLETED`."
    PRD §3.8: "Completing it — a `PrincipalInvestigator` action valid only from
    `PLANNED`, otherwise `ERR_DISSEMINATION_INVALID_STATE`."

    Design: Corner/state_machines/study_auto_transitions_full_lifecycle
    """
    ctx = setup_active_site_study()  # approval auto-locked the plan
    study_id = ctx["study"]["id"]
    assert ctx["plan"]["status"] == "LOCKED"
    assert ctx["study"]["status"] == "RECRUITMENT"  # DESIGN -> RECRUITMENT

    setup_registered_analysis_plan(ctx)
    wave = create_wave(study_id)
    wave = open_wave(wave["id"])
    assert get_study(study_id)["status"] == "DATA_COLLECTION"  # first OPEN wave

    wave = validate_success(api.close_wave(wave["id"], DM), 200)
    assert get_study(study_id)["status"] == "ANALYSIS"  # last wave closed

    report = create_report(study_id)  # FINAL, milestone 30000000
    assert get_study(study_id)["status"] == "REPORTING"  # first report

    validate_success(api.submit_report(report["id"], PI), 200)
    validate_success(api.review_report(report["id"], PEER), 200)
    validate_success(
        api.report_agency_decision(report["id"], report_decision_payload("ACCEPTED"), AO), 200
    )
    report = validate_success(api.publish_report(report["id"], AO), 200)
    assert report["status"] == "PUBLISHED"
    assert get_study(study_id)["status"] == "DISSEMINATION"  # first PUBLISHED

    activity = validate_success(
        api.create_dissemination_activity(
            study_id, create_dissemination_activity_payload(), PI
        ),
        201,
    )
    activity = validate_success(
        api.complete_dissemination_activity(activity["id"], PI), 200
    )
    assert activity["status"] == "COMPLETED"
    study = get_study(study_id)
    assert study["status"] == "COMPLETED", "1 FINAL report meets deliverable_report_count 1"

    sites, _ = validate_paginated(api.list_sites(study_id, SD))
    assert _find(sites, ctx["site"]["id"])["status"] == "COMPLETED", (
        "study completion cascades to ACTIVE sites"
    )

    contract = validate_success(api.closeout_contract(ctx["contract"]["id"], AO), 200)
    assert contract["status"] == "CLOSED"
    assert contract["forfeited_cents"] == 60000000  # 90000000 - 30000000
    assert contract["remaining_cents"] == 0

    resp = api.complete_dissemination_activity(activity["id"], PI)
    validate_error(resp, ApiErrorId.ERR_DISSEMINATION_INVALID_STATE)
