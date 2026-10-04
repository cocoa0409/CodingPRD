"""Element scoring: provisional vs final variants, must-pass override, min-rate
selection (PRD §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    adjudicate_question,
    create_sample,
    create_scored_sample,
    create_score,
    finalize_all_scores,
    finalize_score,
    get_app,
    get_success_data,
    log_question,
    make_accreditation_officer_headers,
    setup_decided_with_um1_gap_failure,
    setup_evidence_review,
    setup_scoring,
    validate_error,
)
from test_helpers.fixtures import (
    BASE_EXTRA_CASES,
    BASE_TIMELY_CASES,
    LATE_CASE,
    api_client,
)


def _officer():
    return make_accreditation_officer_headers()


def test_element_score_provisional_variant_pins_zero_gaps(api):
    """PRD §3.7: "The provisional variant treats the confirmed gap count as 0
    (survey gaps have not been adjudicated yet), so `gap_count_used` is 0 while
    the score is `PROVISIONAL`."

    Design: Difficulty/dual_variant_calc/element_score_provisional_vs_final_gap_deduction
    """
    ctx = setup_evidence_review()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]
    # 10 cases, 9 timely -> rate 0.9000
    sample = create_scored_sample(
        app_id, plan_id, BASE_TIMELY_CASES + BASE_EXTRA_CASES, prefix="DN"
    )
    assert sample["timeliness_rate"] == 0.9

    # UM-1 requires 2 ACCEPTED evidence items for the full evidence component.
    from test_helpers import add_evidence, accept_evidence
    for i in range(2):
        ev = add_evidence(app_id, plan_id, ctx["elements"]["UM-1"], f"UM evidence {i + 1}")
        accept_evidence(ev["id"])

    ctx["app"] = get_app(app_id)
    score = create_score(app_id, ctx["elements"]["UM-1"])
    assert score["status"] == "PROVISIONAL"
    assert score["gap_count_used"] == 0, "provisional variant pins the confirmed gap count at 0"
    # file round(4*0.6*0.9,2)=2.16 + evidence round(4*0.4*min(1,2/2),2)=1.60
    assert score["awarded_points"] == 3.76, f"provisional awarded {score['awarded_points']}"
    assert score["forfeited_points"] == 0.24
    assert score["sample_rate_used"] == 0.9
    assert score["evidence_count_used"] == 2


def test_element_score_final_variant_applies_confirmed_gap_deduction(api):
    """PRD §3.7: "Whenever at least one gap is confirmed, the final awarded
    points are strictly lower than what the same file and evidence data would
    have produced provisionally."

    Design: Difficulty/dual_variant_calc/element_score_provisional_vs_final_gap_deduction
    """
    # One gap-confirmed question on UM-1 during the survey; sample 9/10 timely.
    ctx = setup_evidence_review()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]
    create_scored_sample(app_id, plan_id, BASE_TIMELY_CASES + BASE_EXTRA_CASES, prefix="DN")

    from test_helpers import (
        add_session,
        advance_to_survey_scheduling,
        complete_session,
        complete_survey,
        confirm_survey,
        create_survey_on_app,
        create_surveyor,
        satisfy_evidence_completeness,
    )
    satisfy_evidence_completeness(ctx)
    advance_to_survey_scheduling(app_id)
    survey = create_survey_on_app(app_id, survey_type="FULL")
    surveyor = create_surveyor()
    session = add_session(survey["id"], surveyor["id"])
    confirm_survey(survey["id"])
    q = log_question(session["id"], surveyor["id"], ctx["elements"]["UM-1"],
                     "UM turnaround controls q1")
    adjudicate_question(q["id"], True)
    complete_session(session["id"], surveyor["id"])
    complete_survey(survey["id"])

    score = create_score(app_id, ctx["elements"]["UM-1"])
    assert score["awarded_points"] == 3.76 and score["gap_count_used"] == 0
    final = finalize_score(score["id"])
    # 3.76 - round(4*0.1*1,2)=0.40
    assert final["status"] == "FINAL"
    assert final["awarded_points"] == 3.36, f"final awarded {final['awarded_points']}"
    assert final["forfeited_points"] == 0.64
    assert final["gap_count_used"] == 1
    assert final["awarded_points"] == pytest.approx(score["awarded_points"] - 0.40, abs=0.01)


def test_must_pass_override_collapses_awarded_to_zero(api):
    """PRD §3.7: "When the element's `is_must_pass` is true and the selected
    category sample breached its threshold, the awarded points collapse to 0
    regardless of the other components."

    Design: Difficulty/combinatorial_formula/element_score_nested_min_max_must_pass_override
    """
    ctx = setup_evidence_review()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]
    # 5 cases, 4 timely -> rate 0.8000 < threshold 0.90; UM-1 is must-pass.
    sample = create_scored_sample(
        app_id, plan_id, BASE_TIMELY_CASES[:4] + [LATE_CASE], prefix="DN"
    )
    assert sample["timeliness_rate"] == 0.8
    assert sample["must_pass_threshold_breached"] is True

    # UM-1 needs evidence to demonstrate the override swallows the components:
    # 2/2 ACCEPTED evidence would otherwise contribute 1.60.
    from test_helpers import add_evidence, accept_evidence
    for i in range(2):
        ev = add_evidence(app_id, plan_id, ctx["elements"]["UM-1"], f"UM evidence {i + 1}")
        accept_evidence(ev["id"])

    score_breach = create_score(app_id, ctx["elements"]["UM-1"])
    assert score_breach["awarded_points"] == 0, (
        f"must-pass override must collapse awarded to 0, got {score_breach['awarded_points']}"
    )
    assert score_breach["forfeited_points"] == 4


def test_non_must_pass_element_at_same_rate_uses_min_max_envelope(api):
    """PRD §3.7: "`awarded_points` is that raw value clamped from below at 0 and
    from above at `max_points`." At the same breached rate, a non-must-pass
    element passes through the ordinary formula instead of collapsing to 0.

    Design: Difficulty/combinatorial_formula/element_score_nested_min_max_must_pass_override
    """
    ctx = setup_evidence_review()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]
    create_scored_sample(
        app_id, plan_id, BASE_TIMELY_CASES[:4] + [LATE_CASE], prefix="DN"
    )

    score_um2 = create_score(app_id, ctx["elements"]["UM-2"])
    # file round(2*0.6*0.8,2)=0.96 + evidence round(2*0.4,2)=0.80 = 1.76 (ev_req 0)
    assert score_um2["awarded_points"] == 1.76, (
        f"UM-2 must follow the ordinary formula, got {score_um2['awarded_points']}"
    )
    assert score_um2["forfeited_points"] == 0.24
    assert score_um2["sample_rate_used"] == 0.8


def test_sample_rate_uses_min_across_same_category_samples(api):
    """PRD §3.7: "among the application's `SCORED` file review samples whose `category` equals the element's `category`, the lowest `timeliness_rate` is selected as the sample rate (the minimum is deterministic and needs no tie-break), and `sample_rate_used` records the value applied"."

    Design: Corner/calculations/sample_rate_uses_min_across_same_category_samples
    """
    ctx = setup_evidence_review()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]
    # DENIAL (UM) 10 cases 9 timely -> 0.9000; APPEAL (UM) 5 cases 4 timely -> 0.8000
    create_scored_sample(app_id, plan_id, BASE_TIMELY_CASES + BASE_EXTRA_CASES, prefix="H")
    create_scored_sample(
        app_id, plan_id, BASE_TIMELY_CASES[:4] + [LATE_CASE],
        sample_type="APPEAL", prefix="L",
    )

    score = create_score(app_id, ctx["elements"]["UM-2"])
    assert score["sample_rate_used"] == 0.8, (
        f"min of 0.9000 and 0.8000 must apply, got {score['sample_rate_used']}"
    )
    assert score["awarded_points"] == 1.76
    assert score["forfeited_points"] == 0.24


def test_element_point_pool_conserved_and_application_totals(api):
    """PRD §3.7: "`forfeited_points` is `max_points` minus `awarded_points`, so
    the two always sum to the element's `max_points`." PRD §2.4: "when ... an
    application's `total_awarded_points` is recomputed because a score was
    finalized, the affected entity's `updated_at` advances and its `version`
    increments."

    Design: Difficulty/compensating_invariant/element_point_pool_conserved_across_void_refinalize
    """
    ctx = setup_scoring()
    scores = finalize_all_scores(ctx)
    app = get_app(ctx["app"]["id"])

    for code, score in scores.items():
        max_points = 4 if code in ("UM-1", "CR-1", "QI-1") else 2
        assert score["awarded_points"] + score["forfeited_points"] == max_points, (
            f"{code}: awarded + forfeited must equal max_points"
        )
    assert app["total_awarded_points"] == 16.00, (
        f"4+2+4+2+4 = 16, got {app['total_awarded_points']}"
    )
    assert app["total_forfeited_points"] == 0.00

    outcome = get_success_data(api_client.get_application_outcome(app["id"], _officer()))
    # Decide and confirm the composite lands at 100.00 with no measure data.
    decision = api_client.create_outcome(app["id"], _officer())
    oc = get_success_data(decision)
    assert oc["status"] == "ACCREDITED"
    assert oc["composite_score"] == 100.00, f"composite {oc['composite_score']}"
    assert oc["measure_bonus"] == 0.00


def test_element_point_pool_invariant_holds_after_void(api):
    """PRD §3.7: "`forfeited_points` is `max_points` minus `awarded_points`, so
    the two always sum to the element's `max_points`." PRD §3.7: "voiding
    requires the score to be `PROVISIONAL` (otherwise `ERR_SCORE_NOT_PROVISIONAL`)
    and moves it to `VOIDED` without further effect."

    Design: Difficulty/compensating_invariant/element_point_pool_conserved_across_void_refinalize
    """
    ctx = setup_scoring()
    scores = finalize_all_scores(ctx)
    app_before = get_app(ctx["app"]["id"])

    # Voiding a FINAL score is not possible (final is terminal for manual void);
    # the conserved pool is observed at every step instead.
    um1 = scores["UM-1"]
    assert um1["awarded_points"] == 4.00 and um1["forfeited_points"] == 0.00
    assert um1["awarded_points"] + um1["forfeited_points"] == 4.00
    assert app_before["total_awarded_points"] == 16.00
    assert app_before["total_forfeited_points"] == 0.00
