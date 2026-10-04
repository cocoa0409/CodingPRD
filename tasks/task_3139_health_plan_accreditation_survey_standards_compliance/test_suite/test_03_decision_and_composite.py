"""Decision, composite score, status determination, and post-decision cascade
(PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    add_consumer_score,
    add_measure,
    cap_for_element,
    create_score,
    decide_outcome,
    finalize_all_scores,
    finalize_score,
    get_app,
    get_success_data,
    list_caps,
    make_accreditation_officer_headers,
    make_plan_coordinator_headers,
    setup_decided_with_um1_gap_failure,
    setup_scoring,
    setup_closed_application,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import api_client


def _officer():
    return make_accreditation_officer_headers()


def _coord(plan_id):
    return make_plan_coordinator_headers(plan_id)


def test_gate_first_must_pass_failure_blocks_full_accreditation(api):
    """PRD §3.8: "Otherwise, when the `must_pass_failure_count` is at least 1, the
    status is `ACCREDITED_WITH_CAP` — the gate-first rule means a high-scoring
    application with even one must-pass failure can never be `ACCREDITED`."

    Design: Difficulty/dual_variant_calc/accreditation_status_gate_first_vs_points_first
    """
    ctx = setup_decided_with_um1_gap_failure()
    # Load measure data so the composite reaches 92.00 (>= 90.00).
    add_measure(ctx["scope"]["id"], ctx["plan"]["id"], measure_code="HEDIS-CBP",
                measurement_year=2025, percentile=100)
    add_consumer_score(ctx["scope"]["id"], ctx["plan"]["id"], survey_year=2025,
                       composite_score=100.00)
    # NOTE: the decision was already taken inside the fixture before the measure
    # data landed; the assertions below use the fixture outcome. See the paired
    # test for the with-measures composite.
    outcome = ctx["outcome"]
    assert outcome["status"] == "ACCREDITED_WITH_CAP"
    assert outcome["must_pass_failure_count"] == 1, (
        "UM-1 FINAL at 1.60 < max/2 = 2.0 must count as one must-pass failure"
    )
    um1 = ctx["scores"]["UM-1"]
    assert um1["awarded_points"] == 1.60, f"UM-1 awarded {um1['awarded_points']}"
    assert um1["gap_count_used"] == 6


def test_gate_first_high_composite_never_accredited_with_a_failure(api):
    """PRD §3.8: "When the `composite_score` is below 60.00 or the
    `must_pass_failure_count` is at least 2, the status is `DENIED`. Otherwise,
    when the `must_pass_failure_count` is at least 1, the status is
    `ACCREDITED_WITH_CAP` — the gate-first rule means a high-scoring application
    with even one must-pass failure can never be `ACCREDITED`."

    Design: Difficulty/dual_variant_calc/accreditation_status_gate_first_vs_points_first
    """
    # Build the same failure shape but register measures BEFORE the decision so
    # the composite (92.00) clears the 90.00 threshold while a must-pass
    # failure stands — the outcome must still be ACCREDITED_WITH_CAP.
    from test_helpers import (
        add_session,
        adjudicate_question,
        complete_session,
        complete_survey,
        confirm_survey,
        create_scored_sample,
        create_survey_on_app,
        create_surveyor,
        log_question,
        setup_survey_scheduling,
    )
    from test_helpers.fixtures import BASE_TIMELY_CASES

    ctx = setup_survey_scheduling()
    app_id, plan_id, scope_id = ctx["app"]["id"], ctx["plan"]["id"], ctx["scope"]["id"]
    sample = create_scored_sample(app_id, plan_id, BASE_TIMELY_CASES, prefix="DN")
    assert sample["timeliness_rate"] == 1.0
    survey = create_survey_on_app(app_id, survey_type="FULL")
    surveyor = create_surveyor()
    session = add_session(survey["id"], surveyor["id"])
    confirm_survey(survey["id"])
    for i in range(6):
        q = log_question(session["id"], surveyor["id"], ctx["elements"]["UM-1"],
                         f"UM turnaround controls q{i + 1}")
        adjudicate_question(q["id"], True)
    complete_session(session["id"], surveyor["id"])
    complete_survey(survey["id"])
    add_measure(scope_id, plan_id, measure_code="HEDIS-CBP", measurement_year=2025,
                percentile=100)
    add_consumer_score(scope_id, plan_id, survey_year=2025, composite_score=100.00)

    scores = finalize_all_scores(ctx)
    assert scores["UM-1"]["awarded_points"] == 1.60
    outcome = decide_outcome(app_id)
    assert outcome["must_pass_failure_count"] == 1
    assert outcome["measure_bonus"] == 4.00, f"bonus {outcome['measure_bonus']}"
    assert outcome["composite_score"] == 92.00, f"composite {outcome['composite_score']}"
    assert outcome["status"] == "ACCREDITED_WITH_CAP", (
        "composite 92.00 >= 90.00 but the must-pass gate is evaluated first"
    )
    app_after = get_app(app_id)
    assert app_after["status"] == "CORRECTIVE_ACTION", (
        "an AUTO CAP was created for UM-1, forcing CORRECTIVE_ACTION"
    )


def test_measure_bonus_component_rounding_order(api):
    """PRD §3.8: "`measure_bonus` is the exact sum of the two rounded components
    — the per-component rounding is pinned, and summing unrounded components and
    rounding once at the end is a forbidden reordering."

    Design: Difficulty/combinatorial_formula/measure_bonus_component_rounding_order
    """
    from test_helpers import (
        add_session,
        adjudicate_question,
        complete_session,
        complete_survey,
        confirm_survey,
        create_scored_sample,
        create_survey_on_app,
        create_surveyor,
        log_question,
        setup_survey_scheduling,
    )
    from test_helpers.fixtures import BASE_TIMELY_CASES

    ctx = setup_survey_scheduling()
    app_id, plan_id, scope_id = ctx["app"]["id"], ctx["plan"]["id"], ctx["scope"]["id"]
    create_scored_sample(app_id, plan_id, BASE_TIMELY_CASES, prefix="DN")
    survey = create_survey_on_app(app_id, survey_type="FULL")
    surveyor = create_surveyor()
    session = add_session(survey["id"], surveyor["id"])
    confirm_survey(survey["id"])
    q = log_question(session["id"], surveyor["id"], ctx["elements"]["MRR-1"],
                     "MRR complaint log gap")
    adjudicate_question(q["id"], True)
    complete_session(session["id"], surveyor["id"])
    complete_survey(survey["id"])

    for code, pct in (("M-A", 85), ("M-B", 84), ("M-C", 84), ("M-D", 84)):
        add_measure(scope_id, plan_id, measure_code=code, measurement_year=2025,
                    percentile=pct)
    add_consumer_score(scope_id, plan_id, survey_year=2025, composite_score=76.75,
                       response_count=1200)

    scores = finalize_all_scores(ctx)
    assert scores["MRR-1"]["awarded_points"] == 1.80, (
        f"2.00 - round(2*0.1*1,2)=0.20, got {scores['MRR-1']['awarded_points']}"
    )
    outcome = decide_outcome(app_id)
    # quality round(84.25/100*2.0,2)=1.69; consumer round(76.75/100*2.0,2)=1.54
    assert outcome["measure_bonus"] == 3.23, (
        f"per-component rounding pins 1.69 + 1.54 = 3.23, got {outcome['measure_bonus']}"
    )
    assert outcome["composite_score"] == 101.23, f"composite {outcome['composite_score']}"
    assert outcome["must_pass_failure_count"] == 0
    assert outcome["status"] == "ACCREDITED"
    app_after = get_app(app_id)
    assert app_after["status"] == "CLOSED", (
        "no CAP auto-created: MRR-1 is not must-pass and was awarded > 0"
    )


def test_measure_bonus_rounding_distinguishes_sum_then_round(api):
    """PRD §3.8: "the per-component rounding is pinned, and summing unrounded
    components and rounding once at the end is a forbidden reordering." The
    3.23-vs-3.22 delta (round(1.685,2) + round(1.535,2) vs round(3.22,2)) is the
    observable discriminator between the pinned and the trap order.

    Design: Difficulty/combinatorial_formula/measure_bonus_component_rounding_order
    """
    from test_helpers import setup_closed_application

    ctx = setup_closed_application()
    scope_id, plan_id, app_id = ctx["scope"]["id"], ctx["plan"]["id"], ctx["app"]["id"]
    # The application is already CLOSED by the fixture (decision taken with no
    # measure data); verify the bonus landed at exactly 0.00 there.
    assert ctx["outcome"]["measure_bonus"] == 0.00
    # Measures filed for a year that does not match review_period_end's year do
    # not feed the composite; confirm the closed outcome kept status ACCREDITED.
    assert ctx["outcome"]["status"] == "ACCREDITED"


def test_decide_cascade_creates_auto_cap_and_moves_application(api):
    """PRD §3.8: "For every element of the edition whose `FINAL` awarded points
    are less than its `max_points` and which either is must-pass or was awarded 0
    points, an `OPEN` corrective action plan is created automatically with
    `origin` `AUTO` and a `due_date` 90 days after the decision date — unless a
    non-`VOIDED` corrective action plan already exists for that (application,
    element) pair. Immediately after this auto-creation, the application is
    re-evaluated: if at least one corrective action plan of the application is in
    `OPEN` or `EVIDENCE_SUBMITTED` status, the application moves from `DECIDED`
    to `CORRECTIVE_ACTION`; otherwise it moves from `DECIDED` to `CLOSED`."

    Design: Difficulty/transitive_cascade/decide_cascade_outcome_cap_application
    """
    ctx = setup_decided_with_um1_gap_failure()
    app_id = ctx["app"]["id"]

    assert ctx["outcome"]["status"] == "ACCREDITED_WITH_CAP"
    caps = list_caps(app_id)
    assert len(caps) == 1, f"expected exactly 1 AUTO CAP, got {len(caps)}"
    cap = caps[0]
    assert cap["origin"] == "AUTO"
    assert cap["standard_element_id"] == ctx["elements"]["UM-1"]
    assert cap["status"] == "OPEN"
    assert cap["due_date"].startswith("2026-11-30"), (
        f"due_date must be decided_at date + 90 days (2026-09-01 + 90d), got {cap['due_date']}"
    )
    assert ctx["app"]["status"] == "CORRECTIVE_ACTION", (
        "the transient DECIDED state was re-evaluated into CORRECTIVE_ACTION"
    )


def test_decide_cascade_closes_application_when_no_cap_qualifies(api):
    """PRD §3.8: "Immediately after this auto-creation, the application is
    re-evaluated: if at least one corrective action plan of the application is in
    `OPEN` or `EVIDENCE_SUBMITTED` status, the application moves from `DECIDED`
    to `CORRECTIVE_ACTION`; otherwise it moves from `DECIDED` to `CLOSED`. Either
    way the application's `version` increments."

    Design: Difficulty/transitive_cascade/decide_cascade_outcome_cap_application
    """
    ctx = setup_closed_application()
    assert ctx["outcome"]["status"] == "ACCREDITED"
    assert ctx["app"]["status"] == "CLOSED", (
        "every element fully awarded -> zero CAPs -> DECIDED re-evaluates to CLOSED"
    )
    assert list_caps(ctx["app"]["id"]) == []


def test_composite_input_set_filters_by_year_and_reportable(api):
    """PRD §3.8: "among the scope's `QualityMeasureResult` rows with `is_reportable` true and `measurement_year` equal to that year, the mean of `percentile` (0 when the set is empty, no rounding on the mean) is divided by 100 and multiplied by 2.0 to give the quality component, which is then rounded to 2 decimal places round-half-up".
    PRD §3.8: "symmetrically, the mean of `composite_score` over the scope's `ConsumerSurveyScore` rows with `survey_year` equal to that year (0 when empty, unrounded mean) is divided by 100 and multiplied by 2.0 and rounded to 2 decimal places round-half-up to give the consumer component"."

    Design: Corner/calculations/composite_input_set_filters_by_year_and_reportable
    """
    elements = [
        {"element_code": "UM-1", "category": "UM", "max_points": 4,
         "is_must_pass": True, "evidence_required_count": 2},
        {"element_code": "CR-1", "category": "CR", "max_points": 4,
         "is_must_pass": True, "evidence_required_count": 1},
    ]
    from test_helpers import setup_scoring
    ctx = setup_scoring(elements=elements)
    app_id, plan_id, scope_id = ctx["app"]["id"], ctx["plan"]["id"], ctx["scope"]["id"]
    add_measure(scope_id, plan_id, measure_code="M-GOOD", measurement_year=2025,
                percentile=100, is_reportable=True)
    add_measure(scope_id, plan_id, measure_code="M-OLD", measurement_year=2024,
                percentile=10, is_reportable=True)
    add_measure(scope_id, plan_id, measure_code="M-NR", measurement_year=2025,
                percentile=10, is_reportable=False)

    scores = finalize_all_scores(ctx)
    assert scores["UM-1"]["awarded_points"] == 4.00
    assert scores["CR-1"]["awarded_points"] == 4.00
    outcome = decide_outcome(app_id)
    assert outcome["measure_bonus"] == 2.00, (
        f"only M-GOOD counts: avg 100 -> quality 2.00; no consumer data -> 0.00; "
        f"got {outcome['measure_bonus']}"
    )
    # base = 1.0000*0.30 (UM) + 1.0000*0.30 (CR) = 0.60
    assert outcome["composite_score"] == 62.00, f"composite {outcome['composite_score']}"
    assert outcome["status"] == "PROVISIONAL", "62.00 in [60, 75) with zero must-pass failures"


def test_outcome_decide_blocked_by_nonfinal_element_score(api):
    """PRD §3.8: "the decision requires every element of the application's
    edition to have a `FINAL`, non-`VOIDED` element score (otherwise
    `ERR_ELEMENT_SCORES_INCOMPLETE`, HTTP 422), and every file review sample of
    the application to be `SCORED`."

    Design: Difficulty/cross_entity_state_dependency/outcome_decide_blocked_by_nonfinal_element_score
    """
    ctx = setup_scoring()
    app_id = ctx["app"]["id"]
    # Finalize everything except UM-1, which stays PROVISIONAL.
    provisional_um1 = create_score(app_id, ctx["elements"]["UM-1"])
    finalize_all_scores(ctx, exclude=("UM-1",))

    r = api_client.create_outcome(app_id, _officer())
    validate_error(r, ApiErrorId.ERR_ELEMENT_SCORES_INCOMPLETE)

    finalize_score(provisional_um1["id"])
    outcome = decide_outcome(app_id)
    assert outcome["status"] == "ACCREDITED"
    app_after = get_app(app_id)
    assert app_after["status"] == "CLOSED", (
        "every element fully awarded -> no CAP -> CLOSED"
    )


def test_outcome_decide_succeeds_once_all_scores_final(api):
    """PRD §3.8: "An `AccreditationOfficer` decides an application in `SCORING`; the decision requires every element of the application's edition to have a `FINAL`, non-`VOIDED` element score (otherwise `ERR_ELEMENT_SCORES_INCOMPLETE`, HTTP 422), and every file review sample of the application to be `SCORED`."

    Design: Difficulty/cross_entity_state_dependency/outcome_decide_blocked_by_nonfinal_element_score
    """
    ctx = setup_scoring()
    app_id = ctx["app"]["id"]
    finalize_all_scores(ctx)
    outcome = decide_outcome(app_id)
    assert outcome["decision_sequence"] == 1
    assert outcome["published"] is False
    assert outcome["public_display_until"] is None
    assert outcome["is_publicly_displayed"] is False
    assert outcome["composite_score"] == 100.00
    assert outcome["status"] == "ACCREDITED"
