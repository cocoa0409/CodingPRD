"""Corner queue — error catalogue claims (1 of 2): feasibility gate, burden
cap, participant eligibility, study/state gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_participant,
    amend_analysis_plan_payload,
    create_analysis_plan_payload,
    create_design_plan,
    create_irb_protocol_payload,
    create_record_payload,
    create_wave,
    create_wave_payload,
    get_participant,
    irb_decision_payload,
    open_wave,
    setup_active_site_study,
    setup_contract_with_study,
    setup_participant_at_burden_cap,
    validate_error,
    validate_paginated,
    validate_success,
)

PI = TEST_USERS["principal_investigator_headers"]
DM = TEST_USERS["data_manager_headers"]
IRB = TEST_USERS["irb_reviewer_headers"]


def test_design_submit_insufficient_power_rejected(api):
    """PRD §3.2: "A `PrincipalInvestigator` submits a plan only from `DRAFT` —
    submission from any other state is rejected with
    `ERR_DESIGN_PLAN_INVALID_STATE` — and only when the study's
    `pipeline_projected_n` (the optimistic recruitment projection of §3.4) is
    at least the plan's `required_total_n`; a shortfall is rejected with
    `ERR_INSUFFICIENT_POWER` (HTTP 422)."

    Design: Corner/errors/design_submit_insufficient_power_rejected
    """
    ctx = setup_contract_with_study()  # no sites: pipeline_projected_n 0 < 214
    plan = create_design_plan(ctx["study"]["id"])
    assert plan["required_total_n"] == 214

    resp = api.submit_design_plan(plan["id"], PI)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POWER)
    plans, _ = validate_paginated(api.list_design_plans(ctx["study"]["id"], PI))
    assert next(p for p in plans if p["id"] == plan["id"])["status"] == "DRAFT"


def test_burden_cap_exceeded_at_481(api):
    """PRD §3.6: "A record whose billed minutes would push the participant's
    total above the burden ceiling `MAX_TOTAL_BURDEN_MINUTES` of 480 is
    rejected with `ERR_BURDEN_CAP_EXCEEDED` (HTTP 422); a total landing at
    exactly 480 is allowed."

    Design: Corner/errors/burden_cap_exceeded_at_481
    """
    ctx = setup_participant_at_burden_cap()
    p1 = ctx["participant"]
    wave = ctx["wave_visit"]
    assert ctx["record"]["billed_minutes"] == 480, (
        "round_half_up(384 * 1.25) = 480 — exactly at the cap, allowed"
    )
    assert p1["burden_total_minutes"] == 480

    # One more SITE_VISIT minute bills 1 -> 481 > 480.
    resp = api.create_record(
        wave["id"],
        create_record_payload(p1["id"], instrument_minutes=1, payload_ref="v2"),
        DM,
    )
    validate_error(resp, ApiErrorId.ERR_BURDEN_CAP_EXCEEDED)

    assert get_participant(p1["id"])["burden_total_minutes"] == 480
    records, _ = validate_paginated(api.list_wave_records(wave["id"], DM))
    assert len(records) == 1, "the rejected record was not persisted"


def test_record_for_unconsented_participant_rejected(api):
    """PRD §3.6: "The participant must be in `CONSENTED`,
    `RANDOMIZED_TREATMENT`, or `RANDOMIZED_CONTROL` and therefore not
    `WITHDRAWN`; an ineligible participant is rejected with
    `ERR_PARTICIPANT_NOT_CONSENTED`."

    Design: Corner/errors/record_for_unconsented_participant_rejected
    """
    ctx = setup_active_site_study()
    p1 = add_participant(ctx["site"]["id"], external_ref="P001")  # IDENTIFIED
    wave = create_wave(ctx["study"]["id"])
    open_wave(wave["id"])

    resp = api.create_record(
        wave["id"],
        create_record_payload(p1["id"], instrument_minutes=30, payload_ref="s1"),
        DM,
    )
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_CONSENTED)
    records, _ = validate_paginated(api.list_wave_records(wave["id"], DM))
    assert len(records) == 0


def test_wave_create_while_study_design_rejected(api):
    """PRD §3.6: "A `DataManager` plans a **DataCollectionWave** for a study in
    `RECRUITMENT` or `DATA_COLLECTION` — at any other study stage the creation
    is rejected with `ERR_STUDY_INVALID_STATE`."

    Design: Corner/errors/wave_create_while_study_design_rejected
    """
    ctx = setup_contract_with_study()  # study stays DESIGN (no plan locked)
    resp = api.create_wave(
        ctx["study"]["id"],
        create_wave_payload(
            wave_type="SURVEY",
            open_at="2026-10-01T00:00:00Z", close_at="2026-11-01T00:00:00Z",
        ),
        DM,
    )
    validate_error(resp, ApiErrorId.ERR_STUDY_INVALID_STATE)


def test_irb_decision_on_draft_rejected(api):
    """PRD §3.3: "A `PrincipalInvestigator` submits the protocol to the IRB
    from `DRAFT`, from `MODIFICATIONS_REQUIRED`, or from `EXPIRED` — resubmission
    after required modifications and re-submission after expiry both follow the
    same path — and submission from any other state is rejected with
    `ERR_IRB_INVALID_STATE`."
    PRD §2.8: "The target entity must be in a valid from-state for the
    requested transition, and each child-creating operation must find its
    parent in a state that accepts children." (The decision flow of §3.3 is
    defined on the `SUBMITTED` protocol; a `DRAFT` protocol is not a valid
    from-state for it, and `ERR_IRB_INVALID_STATE` is its state-stage error.)

    Design: Corner/errors/irb_decision_on_draft_rejected
    """
    ctx = setup_contract_with_study()
    irb = validate_success(
        api.create_irb_protocol(ctx["study"]["id"], create_irb_protocol_payload(), PI),
        201,
    )
    resp = api.irb_decision(
        irb["id"],
        irb_decision_payload(
            "APPROVED",
            approval_start="2026-09-01T00:00:00Z",
            approval_end="2027-09-01T00:00:00Z",
        ),
        IRB,
    )
    validate_error(resp, ApiErrorId.ERR_IRB_INVALID_STATE)
    protocols, _ = validate_paginated(api.list_irb_protocols(ctx["study"]["id"], PI))
    assert next(p for p in protocols if p["id"] == irb["id"])["status"] == "DRAFT"


def test_analysis_amend_on_draft_rejected(api):
    """PRD §3.7: "a `PrincipalInvestigator` amends a `PREREGISTERED` plan —
    from `DRAFT` the call is rejected with
    `ERR_ANALYSIS_PLAN_INVALID_STATE`."

    Design: Corner/errors/analysis_amend_on_draft_rejected
    """
    ctx = setup_contract_with_study()
    aplan = validate_success(
        api.create_analysis_plan(
            ctx["study"]["id"],
            create_analysis_plan_payload(primary_outcomes=["employment_q4"]),
            PI,
        ),
        201,
    )
    assert aplan["amendment_count"] == 0

    resp = api.amend_analysis_plan(
        aplan["id"], amend_analysis_plan_payload(secondary_outcomes=["job_retention"]), PI
    )
    validate_error(resp, ApiErrorId.ERR_ANALYSIS_PLAN_INVALID_STATE)
    plans, _ = validate_paginated(api.list_analysis_plans(ctx["study"]["id"], PI))
    assert next(p for p in plans if p["id"] == aplan["id"])["amendment_count"] == 0
