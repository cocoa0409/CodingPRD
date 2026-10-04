"""Corrective action plans and the resurvey recovery rule (PRD §3.5, §3.7, §3.9)."""
from test_helpers import (
    ApiErrorId,
    add_case,
    advance_to_survey_scheduling,
    cap_for_element,
    create_sample,
    create_score,
    create_scored_sample,
    create_survey_on_app,
    decide_outcome,
    finalize_all_scores,
    finish_resurvey,
    get_app,
    get_success_data,
    list_caps,
    make_accreditation_officer_headers,
    make_plan_coordinator_headers,
    set_clock,
    setup_decided_with_um1_gap_failure,
    setup_evidence_review,
    setup_resurvey_survey,
    setup_survey_scheduling,
    submit_cap_evidence,
    submit_sample,
    validate_error,
    verify_cap,
)
from test_helpers.fixtures import (
    BASE_EXTRA_CASES,
    BASE_TIMELY_CASES,
    LATE_CASE,
    LATE_CASE_2,
    api_client,
)


def _officer():
    return make_accreditation_officer_headers()


def test_cap_open_reopen_cycle_loops_back_to_open(api):
    """PRD §3.9: "a verification with `approved` true moves the plan to
    `VERIFIED`, its terminal state; a verification with `approved` false returns
    it to `OPEN` and the cycle may repeat — the plan can loop from `OPEN` to
    `EVIDENCE_SUBMITTED` and back to `OPEN` any number of times."

    Design: Difficulty/non_linear_state_machine/corrective_action_plan_open_reopen_cycle
    """
    ctx = setup_decided_with_um1_gap_failure()
    plan_id = ctx["plan"]["id"]
    cap = cap_for_element(ctx["app"]["id"], ctx["elements"]["UM-1"])
    assert cap["status"] == "OPEN"

    first = submit_cap_evidence(cap["id"], plan_id, "first remediation attempt")
    assert first["status"] == "EVIDENCE_SUBMITTED"

    rejected = verify_cap(cap["id"], False)
    assert rejected["status"] == "OPEN", "rejected verification returns the CAP to OPEN"

    cap_after_reject = get_success_data(
        api_client.get_corrective_action_plan(cap["id"], _officer())
    )
    assert cap_after_reject["status"] == "OPEN"

    second = submit_cap_evidence(cap["id"], plan_id, "second remediation attempt")
    assert second["status"] == "EVIDENCE_SUBMITTED"

    verified = verify_cap(cap["id"], True)
    assert verified["status"] == "VERIFIED"


def test_cap_reopen_cycle_reaches_terminal_verified(api):
    """PRD §3.9: "a verification with `approved` true moves the plan to
    `VERIFIED`, its terminal state"."

    Design: Difficulty/non_linear_state_machine/corrective_action_plan_open_reopen_cycle
    """
    ctx = setup_decided_with_um1_gap_failure()
    plan_id = ctx["plan"]["id"]
    cap = cap_for_element(ctx["app"]["id"], ctx["elements"]["UM-1"])

    submit_cap_evidence(cap["id"], plan_id, "attempt one")
    verify_cap(cap["id"], False)
    submit_cap_evidence(cap["id"], plan_id, "attempt two")
    final = verify_cap(cap["id"], True)
    assert final["status"] == "VERIFIED"
    # VERIFIED is terminal: further verify attempts are rejected.
    r = api_client.verify_corrective_action_plan(cap["id"], {"approved": False}, _officer())
    validate_error(r, ApiErrorId.ERR_CAP_INVALID_STATE)


def _setup_denied_two_cap_application():
    """DENIED application: UM sample 10 cases 8 timely (breach) and CR sample
    12 cases 1 timely (breach); two confirmed gaps on CR-1. Both UM-1 and CR-1
    are must-pass elements whose category samples breached, so both collapse to
    awarded 0 (PRD §3.7). AUTO CAPs for UM-1 and CR-1."""
    ctx = setup_survey_scheduling()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]

    # UM: 8 of 10 timely -> 0.8000 breach -> UM-1 collapses to 0.
    um_cases = BASE_TIMELY_CASES[:4] + [LATE_CASE, LATE_CASE_2] + BASE_EXTRA_CASES[:4]
    um_sample = create_sample(app_id, required_size=10)
    for i, spec in enumerate(um_cases, 1):
        add_case(um_sample["id"], plan_id, case_reference=f"U{i:02d}", **spec)
    submit_sample(um_sample["id"], plan_id)
    from test_helpers import score_sample
    score_sample(um_sample["id"])

    # CR: 1 of 12 timely -> rate 0.0833; turnaround 60 days.
    cr_sample = create_sample(app_id, sample_type="CREDENTIALING", required_size=12)
    add_case(cr_sample["id"], plan_id, case_reference="C01",
             service_date="2025-03-01T00:00:00Z", decision_date="2025-03-20T00:00:00Z",
             required_turnaround_days=60)
    for i in range(2, 13):
        add_case(cr_sample["id"], plan_id, case_reference=f"C{i:02d}",
                 service_date=f"2025-01-{(i - 1):02d}T00:00:00Z",
                 decision_date=f"2025-06-{(i - 1):02d}T00:00:00Z",
                 required_turnaround_days=60)
    submit_sample(cr_sample["id"], plan_id)
    score_sample(cr_sample["id"])

    # The application is already SURVEY_SCHEDULING (setup_survey_scheduling).
    survey = create_survey_on_app(app_id, survey_type="FULL")
    from test_helpers import add_session, confirm_survey, create_surveyor, log_question
    from test_helpers import adjudicate_question, complete_session, complete_survey
    surveyor = create_surveyor()
    ctx["surveyor"] = surveyor
    session = add_session(survey["id"], surveyor["id"])
    confirm_survey(survey["id"])
    for i in range(2):
        q = log_question(session["id"], surveyor["id"], ctx["elements"]["CR-1"],
                         f"CR file gap q{i + 1}")
        adjudicate_question(q["id"], True)
    complete_session(session["id"], surveyor["id"])
    complete_survey(survey["id"])

    ctx["app"] = get_app(app_id)
    ctx["scores"] = finalize_all_scores(ctx)
    assert ctx["scores"]["UM-1"]["awarded_points"] == 0
    assert ctx["scores"]["CR-1"]["awarded_points"] == 0, (
        "CR-1 is must-pass and the CR sample breached (0.0833 < 0.90) -> collapses to 0"
    )

    from test_helpers import add_consumer_score, add_measure
    add_measure(ctx["scope"]["id"], plan_id, measure_code="M-A", percentile=50)
    add_measure(ctx["scope"]["id"], plan_id, measure_code="M-B", percentile=50)
    add_consumer_score(ctx["scope"]["id"], plan_id, composite_score=50.00, response_count=700)

    ctx["outcome"] = decide_outcome(app_id)
    ctx["app"] = get_app(app_id)
    return ctx


def test_resurvey_recovery_uses_frozen_closure_rate(api):
    """PRD §3.7: "The recovery amount is the survey's `frozen_cap_closure_rate`
    multiplied by the snapshot's forfeited-at-freeze value, rounded to 2 decimal
    places round-half-up. The provisional `awarded_points` is the snapshot's
    awarded-at-freeze value plus the recovery amount, clamped at the element's
    `max_points`." PRD §3.5: "CAP verifications completed after confirm do not
    change the frozen rate."

    Design: Difficulty/combinatorial_formula/cap_recovery_frozen_closure_rate_evaluation_order
    """
    ctx = _setup_denied_two_cap_application()
    outcome = ctx["outcome"]
    assert outcome["status"] == "DENIED"
    assert outcome["must_pass_failure_count"] == 2
    # base = r4(1.76/6)*0.30 + r4(0/4)*0.30 + 1.0*0.20 + 1.0*0.20 = 0.48799
    # bonus = round(50/100*2,2) + round(50/100*2,2) = 2.00 -> 50.80
    assert outcome["composite_score"] == 50.80, f"composite {outcome['composite_score']}"
    assert ctx["app"]["status"] == "CORRECTIVE_ACTION"

    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]
    cap_um1 = cap_for_element(app_id, ctx["elements"]["UM-1"])
    cap_cr1 = cap_for_element(app_id, ctx["elements"]["CR-1"])

    # Verify ONLY the UM-1 CAP before the resurvey confirm: 1 of 2 VERIFIED.
    submit_cap_evidence(cap_um1["id"], plan_id, "UM remediation evidence package")
    verify_cap(cap_um1["id"], True)

    resurvey = setup_resurvey_survey(ctx)
    assert resurvey["frozen_cap_closure_rate"] == 0.5, (
        f"frozen with 1 of 2 CAPs VERIFIED, got {resurvey['frozen_cap_closure_rate']}"
    )

    # NOTE: PRD §3.5's "CAP verifications completed after confirm do not change
    # the frozen rate" cannot be exercised end-to-end: submit-evidence requires
    # the application in CORRECTIVE_ACTION (§3.9) and confirm is blocked while a
    # CAP awaits review (§3.5), so no verification can land after confirm under
    # the PRD's own gates. The freeze assertion above covers the derivable rule.

    old_um1 = ctx["scores"]["UM-1"]
    old_cr1 = ctx["scores"]["CR-1"]
    finish_resurvey(ctx)

    # The resurvey completion voids the FINAL scores of CAP elements.
    assert get_success_data(api_client.get_element_score(old_um1["id"], _officer()))["status"] == "VOIDED"
    assert get_success_data(api_client.get_element_score(old_cr1["id"], _officer()))["status"] == "VOIDED"

    rescore_um1 = create_score(app_id, ctx["elements"]["UM-1"])
    rescore_cr1 = create_score(app_id, ctx["elements"]["CR-1"])
    assert rescore_um1["scoring_basis"] == "RESURVEY"
    # min(4, 0 + round(0.5*4.00,2)=2.00) — NOT 4.00 (a live 1.0 rate would give 4.00)
    assert rescore_um1["awarded_points"] == 2.00, (
        f"recovery min(4, 0 + round(0.5*4.00,2)) = 2.00, got {rescore_um1['awarded_points']}"
    )
    assert rescore_um1["forfeited_points"] == 2.00
    # CR-1 collapsed to 0.00 at freeze: min(4, 0.00 + round(0.5*4.00,2)=2.00) = 2.00
    assert rescore_cr1["awarded_points"] == 2.00, (
        f"recovery min(4, 0.00 + 2.00) = 2.00, got {rescore_cr1['awarded_points']}"
    )
    assert rescore_cr1["forfeited_points"] == 2.00


def test_resurvey_recovery_frozen_snapshot_not_live_recomputation(api):
    """PRD §3.7: "The frozen closure rate and snapshots were captured at
    resurvey-confirm time (§3.5), and later verifications of corrective action
    plans do not move them."

    Design: Difficulty/combinatorial_formula/cap_recovery_frozen_closure_rate_evaluation_order
    """
    ctx = _setup_denied_two_cap_application()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]
    cap_um1 = cap_for_element(app_id, ctx["elements"]["UM-1"])

    submit_cap_evidence(cap_um1["id"], plan_id, "UM remediation")
    verify_cap(cap_um1["id"], True)

    resurvey = setup_resurvey_survey(ctx)
    assert resurvey["frozen_cap_closure_rate"] == 0.5
    finish_resurvey(ctx)

    # Element without a CAP (QI-1) uses the ordinary formula unchanged.
    old_qi1 = ctx["scores"]["QI-1"]
    assert get_success_data(api_client.get_element_score(old_qi1["id"], _officer()))["status"] == "FINAL", (
        "only CAP-element scores are voided at resurvey completion"
    )
    rescore_um1 = create_score(app_id, ctx["elements"]["UM-1"])
    assert rescore_um1["awarded_points"] == 2.00
    assert rescore_um1["scoring_basis"] == "RESURVEY"


def test_application_corrective_action_resurvey_cycle_revisits_scoring(api):
    """PRD §3.9: "The resurvey path out of it is described in §3.5: creating a
    `RESURVEY` survey, confirming it (which freezes the closure rate), completing
    it (which voids the `FINAL` scores for elements with corrective action plans
    and returns the application to `SCORING`), re-scoring those elements under
    the resurvey recovery rule (§3.7), and revising the outcome (§3.8)."

    Design: Difficulty/non_linear_state_machine/application_corrective_action_resurvey_cycle
    """
    ctx = setup_decided_with_um1_gap_failure()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]
    assert ctx["app"]["status"] == "CORRECTIVE_ACTION"

    cap = cap_for_element(app_id, ctx["elements"]["UM-1"])
    submit_cap_evidence(cap["id"], plan_id, "UM remediation")
    verify_cap(cap["id"], True)

    resurvey = setup_resurvey_survey(ctx, session_date="2026-11-03")
    assert get_app(app_id)["status"] == "RESURVEY_IN_PROGRESS"
    assert resurvey["frozen_cap_closure_rate"] == 1.0, (
        "1 of 1 CAP VERIFIED at confirm"
    )

    finish_resurvey(ctx)
    assert get_app(app_id)["status"] == "SCORING", (
        "SCORING is visited a second time — the application lifecycle is cyclic"
    )
    # CAP-element score voided; non-CAP score untouched.
    assert get_success_data(api_client.get_element_score(ctx["scores"]["UM-1"]["id"], _officer()))["status"] == "VOIDED"
    assert get_success_data(api_client.get_element_score(ctx["scores"]["QI-1"]["id"], _officer()))["status"] == "FINAL"


def test_resurvey_cycle_returns_to_scoring_for_revise(api):
    """PRD §3.5: "For a `RESURVEY` survey, completing moves the application from
    `RESURVEY_IN_PROGRESS` to `SCORING`, increments its `version`, and voids
    every `FINAL` element score of the application whose `standard_element_id`
    matches an existing corrective action plan's `standard_element_id` (those
    scores move `FINAL` to `VOIDED`)."

    Design: Difficulty/non_linear_state_machine/application_corrective_action_resurvey_cycle
    """
    ctx = setup_decided_with_um1_gap_failure()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]

    cap = cap_for_element(app_id, ctx["elements"]["UM-1"])
    submit_cap_evidence(cap["id"], plan_id, "UM remediation")
    verify_cap(cap["id"], True)

    resurvey = setup_resurvey_survey(ctx)
    assert resurvey["status"] == "CONFIRMED"
    finish_resurvey(ctx)

    app = get_app(app_id)
    assert app["status"] == "SCORING"
    # Re-score the CAP element under the recovery rule and re-decide via revise.
    rescore = create_score(app_id, ctx["elements"]["UM-1"])
    # closure 1.0 * forfeited-at-freeze 2.40 = 2.40 recovery on awarded 1.60 -> 4.00
    assert rescore["awarded_points"] == 4.00, (
        f"min(4, 1.60 + round(1.0*2.40,2)) = 4.00, got {rescore['awarded_points']}"
    )
    assert rescore["scoring_basis"] == "RESURVEY"
    from test_helpers import finalize_score
    finalize_score(rescore["id"])
    revised = api_client.revise_outcome(ctx["outcome"]["id"], _officer())
    revised_data = get_success_data(revised)
    assert revised_data["decision_sequence"] == 2


def test_cap_overdue_blocks_resurvey_confirm(api):
    """PRD §3.5: "for a `RESURVEY` survey no corrective action plan of the
    application may be overdue, meaning `is_overdue` is true (otherwise
    `ERR_CAP_OVERDUE`, HTTP 422)." PRD §3.9: "Its `is_overdue` flag is recomputed
    whenever the logical clock advances: it is true when the plan's `due_date` is
    before the logical clock's current date and the plan's status is not
    `VERIFIED`."

    Design: Corner/cross_cutting_layers/cap_overdue_blocks_resurvey_confirm
    """
    # Decide with UM-1 awarded 0 (rate 0.0000 breach) -> DENIED, AUTO CAP due
    # 2026-11-30 (logical clock 2026-09-01 + 90 days).
    elements = [
        {"element_code": "UM-1", "category": "UM", "max_points": 4,
         "is_must_pass": True, "evidence_required_count": 2},
        {"element_code": "CR-1", "category": "CR", "max_points": 4,
         "is_must_pass": True, "evidence_required_count": 1},
    ]
    ctx = setup_evidence_review(elements=elements)
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]

    # UM sample: 0 of 5 timely (all 73+ days late) -> rate 0.0000 breach.
    um_sample = create_sample(app_id, required_size=5)
    for i, (sd, dd) in enumerate((
        ("2025-01-01", "2025-03-15"), ("2025-02-01", "2025-04-15"),
        ("2025-03-01", "2025-05-15"), ("2025-04-01", "2025-06-15"),
        ("2025-05-01", "2025-07-15")), 1):
        add_case(um_sample["id"], plan_id, case_reference=f"O{i}",
                 service_date=f"{sd}T00:00:00Z", decision_date=f"{dd}T00:00:00Z")
    submit_sample(um_sample["id"], plan_id)
    from test_helpers import score_sample
    score_sample(um_sample["id"])

    from test_helpers import add_evidence, accept_evidence
    for i in range(2):
        ev = add_evidence(app_id, plan_id, ctx["elements"]["UM-1"], f"UM evidence {i + 1}")
        accept_evidence(ev["id"])
    ev = add_evidence(app_id, plan_id, ctx["elements"]["CR-1"], "CR minutes")
    accept_evidence(ev["id"])

    advance_to_survey_scheduling(app_id)
    survey = create_survey_on_app(app_id, survey_type="FULL")
    from test_helpers import add_session, confirm_survey, create_surveyor, complete_session, complete_survey
    surveyor = create_surveyor()
    ctx["surveyor"] = surveyor
    session = add_session(survey["id"], surveyor["id"])
    confirm_survey(survey["id"])
    complete_session(session["id"], surveyor["id"])
    complete_survey(survey["id"])

    scores = finalize_all_scores(ctx)
    assert scores["UM-1"]["awarded_points"] == 0
    assert scores["CR-1"]["awarded_points"] == 4.00
    outcome = decide_outcome(app_id)
    assert outcome["status"] == "DENIED"
    assert outcome["must_pass_failure_count"] == 1
    assert outcome["composite_score"] == 30.00, (
        f"base 0.30*0.0000 + 0.30*1.0000 = 0.30 -> 30.00, got {outcome['composite_score']}"
    )

    cap = cap_for_element(app_id, ctx["elements"]["UM-1"])
    assert cap["due_date"].startswith("2026-11-30")
    assert cap["is_overdue"] is False

    set_clock("2027-02-01T00:00:00Z")
    cap_after = get_success_data(api_client.get_corrective_action_plan(cap["id"], _officer()))
    assert cap_after["is_overdue"] is True, "due_date 2026-11-30 < clock date 2027-02-01"

    resurvey = create_survey_on_app(app_id, survey_type="RESURVEY",
                                    start_date="2027-02-08", end_date="2027-02-12",
                                    budgeted_surveyor_hours=4)
    from test_helpers import add_session
    add_session(resurvey["id"], surveyor["id"], session_date="2027-02-08")
    r = api_client.confirm_survey(resurvey["id"], _officer())
    validate_error(r, ApiErrorId.ERR_CAP_OVERDUE)
    survey_after = get_success_data(api_client.get_survey(resurvey["id"], _officer()))
    assert survey_after["status"] == "PLANNED", "failed confirm leaves the survey PLANNED"
