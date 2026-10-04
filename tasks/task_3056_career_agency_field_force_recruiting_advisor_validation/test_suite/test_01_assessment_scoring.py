"""Selection-assessment scoring: weight tables, bands and the pinned
round-then-sum evaluation order."""
import pytest

from test_helpers import (
    api_client,
    assert_scored_against_weight_table,
    candidate_to_assessment_pending,
    get_success_data,
    new_office,
    ro_headers,
    set_clock,
)

COMPETENCIES_DIVERGENT = {
    "MARKET_KNOWLEDGE": 4,
    "RELATIONSHIP": 10,
    "RESILIENCE": 10,
    "ETHICS": 8,
}
COMPETENCIES_ROUNDING = {
    "MARKET_KNOWLEDGE": 9,
    "RELATIONSHIP": 9,
    "RESILIENCE": 8,
    "ETHICS": 9,
}


def test_same_competency_vector_diverges_across_v1_and_v2_tables():
    """PRD §3.2: "the same competency profile of 4, 10, 10, and 8 yields a
    `weighted_score` of 8.29 and a `PASS` under `V1`, but a `weighted_score` of
    7.69 and a `CONDITIONAL` under `V2`."

    Design: Difficulty/dual_variant_calc/selection_assessment_v1_vs_v2_weight_tables
    """
    set_clock()
    office = new_office()
    # V1 arm
    cand_v1, asm_v1 = candidate_to_assessment_pending(office["id"], name="Alicia V1",
                                                      channel="CAMPUS", campus_name="UW Madison",
                                                      assessment_version="V1")
    # V2 arm
    cand_v2, asm_v2 = candidate_to_assessment_pending(office["id"], name="Blair V2",
                                                      assessment_version="V2")

    scored_v1 = get_success_data(api_client.score_assessment(
        asm_v1["id"], {"raw_score": 78, "competency_scores": COMPETENCIES_DIVERGENT}, ro_headers))
    scored_v2 = get_success_data(api_client.score_assessment(
        asm_v2["id"], {"raw_score": 78, "competency_scores": COMPETENCIES_DIVERGENT}, ro_headers))

    assert scored_v1["weighted_score"] == pytest.approx(8.29, abs=0.005)
    assert scored_v1["outcome"] == "PASS"
    assert scored_v2["weighted_score"] == pytest.approx(7.69, abs=0.005)
    assert scored_v2["outcome"] == "CONDITIONAL"


def test_locked_weights_freeze_the_selected_table():
    """PRD §3.2: "The `locked_weights` field records the weight table actually
    applied, frozen at scoring time, so a later change to what the instrument
    version means cannot retroactively move a scored result."

    Design: Difficulty/dual_variant_calc/selection_assessment_v1_vs_v2_weight_tables
    """
    set_clock()
    office = new_office()
    _, asm_v1 = candidate_to_assessment_pending(office["id"], name="Alicia Lock",
                                                assessment_version="V1")
    _, asm_v2 = candidate_to_assessment_pending(office["id"], name="Blair Lock",
                                                assessment_version="V2")

    scored_v1 = get_success_data(api_client.score_assessment(
        asm_v1["id"], {"raw_score": 78, "competency_scores": COMPETENCIES_DIVERGENT}, ro_headers))
    scored_v2 = get_success_data(api_client.score_assessment(
        asm_v2["id"], {"raw_score": 78, "competency_scores": COMPETENCIES_DIVERGENT}, ro_headers))

    assert scored_v1["locked_weights"]["MARKET_KNOWLEDGE"] == pytest.approx(0.175)
    assert scored_v1["locked_weights"]["ETHICS"] == pytest.approx(0.30)
    assert scored_v2["locked_weights"]["MARKET_KNOWLEDGE"] == pytest.approx(0.30)
    assert scored_v2["locked_weights"]["RELATIONSHIP"] == pytest.approx(0.15)


def test_both_scored_assessments_advance_their_candidates_to_assessed():
    """PRD §3.2: "Scoring it is the joint work of two state machines: the
    assessment moves from `SCHEDULED` to `SCORED` and, in the same operation,
    its owning candidate moves from `ASSESSMENT_PENDING` to `ASSESSED`."

    Design: Difficulty/dual_variant_calc/selection_assessment_v1_vs_v2_weight_tables
    """
    set_clock()
    office = new_office()
    cand_v1, asm_v1 = candidate_to_assessment_pending(office["id"], name="Alicia Stage",
                                                      channel="CAMPUS", campus_name="UW Madison",
                                                      assessment_version="V1")
    cand_v2, asm_v2 = candidate_to_assessment_pending(office["id"], name="Blair Stage",
                                                      assessment_version="V2")

    get_success_data(api_client.score_assessment(
        asm_v1["id"], {"raw_score": 78, "competency_scores": COMPETENCIES_DIVERGENT}, ro_headers))
    get_success_data(api_client.score_assessment(
        asm_v2["id"], {"raw_score": 78, "competency_scores": COMPETENCIES_DIVERGENT}, ro_headers))

    assert get_success_data(api_client.get_candidate(cand_v1["id"], ro_headers))["stage"] == "ASSESSED"
    assert get_success_data(api_client.get_candidate(cand_v2["id"], ro_headers))["stage"] == "ASSESSED"


def test_intermediate_rounding_order_is_round_then_sum():
    """PRD §3.2: "The two intermediate products are rounded *before* they are
    added; adding first and rounding afterwards is a different, incorrect
    reading that shifts results by a cent — for competency values of 9, 9, 8,
    and 9 under the `V1` table the pinned order yields a `weighted_score` of
    8.88, while the sum-then-round order yields 8.87."

    Design: Difficulty/combinatorial_formula/assessment_intermediate_rounding_order_pinned
    """
    set_clock()
    office = new_office()
    _, assessment = candidate_to_assessment_pending(
        office["id"], name="Casey Rounding", channel="CAMPUS",
        campus_name="Marquette University", assessment_version="V1")

    scored = get_success_data(api_client.score_assessment(
        assessment["id"],
        {"raw_score": 88, "competency_scores": COMPETENCIES_ROUNDING}, ro_headers))

    assert scored["weighted_score"] == pytest.approx(8.88, abs=0.005)
    assert scored["weighted_score"] != pytest.approx(8.87, abs=0.005)


def test_the_raw_score_never_enters_the_weighted_score():
    """PRD §3.2: "The `raw_score` is stored on the record but never enters the
    weighted score."

    Design: Difficulty/combinatorial_formula/assessment_intermediate_rounding_order_pinned
    """
    set_clock()
    office = new_office()
    _, assessment = candidate_to_assessment_pending(
        office["id"], name="Casey Raw", assessment_version="V1")

    scored = get_success_data(api_client.score_assessment(
        assessment["id"],
        {"raw_score": 88, "competency_scores": COMPETENCIES_ROUNDING}, ro_headers))

    assert scored["raw_score"] == 88
    assert scored["weighted_score"] != pytest.approx(8.80, abs=0.005)


def test_rounding_case_outcome_is_pass_and_locked_table_is_v1():
    """PRD §3.2: "`PASS` when the `weighted_score` is at least 8.00" and "Under
    `V1` the weights are `MARKET_KNOWLEDGE` 0.175, `RELATIONSHIP` 0.275,
    `RESILIENCE` 0.25, and `ETHICS` 0.30."

    Design: Difficulty/combinatorial_formula/assessment_intermediate_rounding_order_pinned
    """
    set_clock()
    office = new_office()
    _, assessment = candidate_to_assessment_pending(
        office["id"], name="Casey Band", assessment_version="V1")

    scored = get_success_data(api_client.score_assessment(
        assessment["id"],
        {"raw_score": 88, "competency_scores": COMPETENCIES_ROUNDING}, ro_headers))

    assert scored["outcome"] == "PASS"
    assert scored["locked_weights"] == pytest.approx({
        "MARKET_KNOWLEDGE": 0.175, "RELATIONSHIP": 0.275,
        "RESILIENCE": 0.25, "ETHICS": 0.30})
    assert_scored_against_weight_table(scored)