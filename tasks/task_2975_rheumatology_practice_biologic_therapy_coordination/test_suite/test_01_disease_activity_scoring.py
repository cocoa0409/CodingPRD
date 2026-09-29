"""Disease activity scoring: the two instruments and the CDAI category ladder.

Sources: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8 rules `dual_variant_calc` and
`boundary_precision_check`.
"""
from prd_bench_local_runner.testing import get_success_data

from test_helpers import api_client
from test_helpers.assertions import assert_two_decimal_places, assert_visit
from test_helpers.constants import CLOCK_DEFAULT, instant
from test_helpers.fixtures import (
    ADMIN,
    bootstrap_reference,
    checked_in_visit,
    register_patient,
    score_visit,
    set_clock,
)
from test_helpers.factories import score_visit_cdai_payload, score_visit_das28_payload


def _two_patient_practice():
    """One rheumatologist, one nurse and two patients, each with one
    `CHECKED_IN` `FOLLOW_UP` visit booked with that same rheumatologist and no
    therapy episode of any kind on file."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    scenario = bootstrap_reference()
    pat1 = register_patient(scenario)
    visit1 = checked_in_visit(scenario, instant(2026, 8, 3, 14, 0, 0))
    pat2 = register_patient(scenario)
    visit2 = checked_in_visit(scenario, instant(2026, 8, 4, 14, 0, 0))
    return scenario, pat1, visit1, pat2, visit2


def _patient(patient_id):
    return get_success_data(api_client.get_patient(patient_id, ADMIN))


# ---------------------------------------------------------------------------
# dual_variant_calc / visit_instrument_variant_divergence_cdai_vs_das28
# ---------------------------------------------------------------------------
def test_cdai_variant_sums_four_components_and_lands_low_and_at_target():
    """The `CDAI` variant is a plain four-component sum.

    PRD §3.2: "Under `CDAI`, the score is the plain sum of four components:
    `tender_joint_count` plus `swollen_joint_count` plus
    `patient_global_assessment` plus `physician_global_assessment`, rounded half
    up to two decimal places."

    PRD §3.2: "The resulting `activity_category` is `REMISSION` when the score
    is at most 2.80, `LOW` when it is greater than 2.80 and at most 10.00,
    `MODERATE` when it is greater than 10.00 and at most 22.00, and `HIGH` when
    it exceeds 22.00."

    Design: Difficulty/dual_variant_calc/visit_instrument_variant_divergence_cdai_vs_das28
    """
    scenario, pat1, visit1, _pat2, _visit2 = _two_patient_practice()

    scored = score_visit(
        scenario,
        score_visit_cdai_payload(
            tender_joint_count=2,
            swollen_joint_count=1,
            patient_global_assessment=3.0,
            physician_global_assessment=3.0,
        ),
        visit1["id"],
    )

    assert_visit(scored)
    assert scored["status"] == "SCORED"
    assert_two_decimal_places(scored["activity_score"], "activity_score")
    assert scored["activity_score"] == 9.00, (
        f"2 + 1 + 3.0 + 3.0 must score 9.00, got {scored['activity_score']}"
    )
    assert scored["activity_category"] == "LOW"
    assert scored["escalation_recommendation"] == "CONTINUE"

    patient = _patient(pat1["id"])
    assert patient["latest_activity_score"] == 9.00
    assert patient["latest_activity_category"] == "LOW"
    assert patient["target_status"] == "AT_TARGET"


def test_das28_crp_variant_uses_the_five_term_formula_and_lands_moderate():
    """The `DAS28_CRP` variant is a five-term logarithmic formula.

    PRD §3.2: "The raw score is the sum of five terms, computed at full
    precision: 0.56 multiplied by the square root of `tender_joint_count`; plus
    0.28 multiplied by the square root of `swollen_joint_count`; plus 0.36
    multiplied by the natural logarithm of the quantity obtained by multiplying
    `crp_mg_dl` by ten and then adding one; plus 0.014 multiplied by the quantity
    obtained by multiplying `patient_global_assessment` by ten; plus an intercept
    of 0.96."

    PRD §3.2: "The resulting `activity_category` is `REMISSION` when the score is
    **strictly less than** 2.60, `LOW` when it is at least 2.60 and at most 3.20,
    `MODERATE` when it is greater than 3.20 and at most 5.10, and `HIGH` when it
    exceeds 5.10."

    Design: Difficulty/dual_variant_calc/visit_instrument_variant_divergence_cdai_vs_das28
    """
    scenario, _pat1, _visit1, pat2, visit2 = _two_patient_practice()

    scored = score_visit(
        scenario,
        score_visit_das28_payload(
            tender_joint_count=2,
            swollen_joint_count=1,
            patient_global_assessment=3.0,
            crp_mg_dl=2.5,
        ),
        visit2["id"],
    )

    assert_visit(scored)
    assert scored["status"] == "SCORED"
    assert_two_decimal_places(scored["activity_score"], "activity_score")
    assert scored["activity_score"] == 3.62, (
        "0.56*sqrt(2) + 0.28*sqrt(1) + 0.36*ln(26) + 0.014*30 + 0.96 rounds to "
        f"3.62, got {scored['activity_score']}"
    )
    assert scored["activity_category"] == "MODERATE"
    assert scored["escalation_recommendation"] == "OPTIMIZE_CURRENT"

    patient = _patient(pat2["id"])
    assert patient["latest_activity_score"] == 3.62
    assert patient["latest_activity_category"] == "MODERATE"
    assert patient["target_status"] == "NOT_AT_TARGET"


def test_the_two_instruments_diverge_on_identical_joint_counts():
    """The same joints put two patients in two different categories.

    PRD §3.2: "The two instruments produce **different** numbers from the same
    joints, and may land the same patient in different categories, so the choice
    of instrument is a clinical decision with contractual consequences."

    Design: Difficulty/dual_variant_calc/visit_instrument_variant_divergence_cdai_vs_das28
    """
    scenario, pat1, visit1, pat2, visit2 = _two_patient_practice()

    cdai = score_visit(
        scenario,
        score_visit_cdai_payload(
            tender_joint_count=2,
            swollen_joint_count=1,
            patient_global_assessment=3.0,
            physician_global_assessment=3.0,
        ),
        visit1["id"],
    )
    das28 = score_visit(
        scenario,
        score_visit_das28_payload(
            tender_joint_count=2,
            swollen_joint_count=1,
            patient_global_assessment=3.0,
            crp_mg_dl=2.5,
        ),
        visit2["id"],
    )

    assert cdai["activity_score"] == 9.00
    assert das28["activity_score"] == 3.62
    assert cdai["activity_score"] != das28["activity_score"], (
        "the two instruments must not produce the same number from the same joints"
    )
    assert cdai["activity_category"] == "LOW"
    assert das28["activity_category"] == "MODERATE"
    assert cdai["activity_category"] != das28["activity_category"]
    assert cdai["escalation_recommendation"] == "CONTINUE"
    assert das28["escalation_recommendation"] == "OPTIMIZE_CURRENT"

    assert _patient(pat1["id"])["target_status"] == "AT_TARGET"
    assert _patient(pat2["id"])["target_status"] == "NOT_AT_TARGET"


def _three_patient_practice():
    """Three patients, one `CHECKED_IN` `FOLLOW_UP` visit each, placed on three
    different days so the two-concurrent-visit clinician cap cannot fire, and no
    therapy episode anywhere so the `MODERATE` dwell test finds nothing."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    scenario = bootstrap_reference()
    rows = []
    for day in (3, 4, 5):
        patient = register_patient(scenario)
        visit = checked_in_visit(scenario, instant(2026, 8, day, 14, 0, 0))
        rows.append((patient, visit))
    return scenario, rows


def _ceiling_payload(patient_global):
    return score_visit_cdai_payload(
        tender_joint_count=8,
        swollen_joint_count=6,
        patient_global_assessment=patient_global,
        physician_global_assessment=4.0,
    )


# ---------------------------------------------------------------------------
# boundary_precision_check / cdai_exactly_at_moderate_ceiling_scores_moderate_not_high
# ---------------------------------------------------------------------------
def test_cdai_just_below_the_moderate_ceiling_is_moderate():
    """21.90 sits inside the `MODERATE` band.

    PRD §3.2: "The resulting `activity_category` is `REMISSION` when the score is
    at most 2.80, `LOW` when it is greater than 2.80 and at most 10.00,
    `MODERATE` when it is greater than 10.00 and at most 22.00, and `HIGH` when
    it exceeds 22.00."

    Design: Difficulty/boundary_precision_check/cdai_exactly_at_moderate_ceiling_scores_moderate_not_high
    """
    scenario, rows = _three_patient_practice()
    patient, visit = rows[0]

    scored = score_visit(scenario, _ceiling_payload(3.9), visit["id"])

    assert scored["activity_score"] == 21.90, (
        f"8 + 6 + 3.9 + 4.0 must score 21.90, got {scored['activity_score']}"
    )
    assert scored["activity_category"] == "MODERATE"
    assert scored["escalation_recommendation"] == "OPTIMIZE_CURRENT"
    assert scored["status"] == "SCORED"
    assert _patient(patient["id"])["target_status"] == "NOT_AT_TARGET"


def test_cdai_exactly_at_the_moderate_ceiling_is_moderate_not_high():
    """The 22.00 upper bound of `MODERATE` is inclusive.

    PRD §3.2: "The resulting `activity_category` is `REMISSION` when the score is
    at most 2.80, `LOW` when it is greater than 2.80 and at most 10.00,
    `MODERATE` when it is greater than 10.00 and at most 22.00, and `HIGH` when
    it exceeds 22.00."

    Design: Difficulty/boundary_precision_check/cdai_exactly_at_moderate_ceiling_scores_moderate_not_high
    """
    scenario, rows = _three_patient_practice()
    patient, visit = rows[1]

    scored = score_visit(scenario, _ceiling_payload(4.0), visit["id"])

    assert scored["activity_score"] == 22.00, (
        f"8 + 6 + 4.0 + 4.0 must score 22.00, got {scored['activity_score']}"
    )
    assert scored["activity_category"] == "MODERATE", (
        "22.00 is at most 22.00, so the inclusive ceiling keeps it in MODERATE"
    )
    assert scored["activity_category"] != "HIGH"
    assert scored["escalation_recommendation"] == "OPTIMIZE_CURRENT"
    assert scored["escalation_recommendation"] != "ESCALATE"

    denormalized = _patient(patient["id"])
    assert denormalized["latest_activity_score"] == 22.00
    assert denormalized["latest_activity_category"] == "MODERATE"
    assert denormalized["target_status"] == "NOT_AT_TARGET"


def test_cdai_just_above_the_moderate_ceiling_is_high_and_escalates():
    """22.10 exceeds 22.00 and crosses into `HIGH`.

    PRD §3.2: "A `HIGH` category yields `ESCALATE` unconditionally."

    Design: Difficulty/boundary_precision_check/cdai_exactly_at_moderate_ceiling_scores_moderate_not_high
    """
    scenario, rows = _three_patient_practice()
    patient, visit = rows[2]

    scored = score_visit(scenario, _ceiling_payload(4.1), visit["id"])

    assert scored["activity_score"] == 22.10, (
        f"8 + 6 + 4.1 + 4.0 must score 22.10, got {scored['activity_score']}"
    )
    assert scored["activity_category"] == "HIGH"
    assert scored["escalation_recommendation"] == "ESCALATE"
    assert scored["status"] == "SCORED"

    denormalized = _patient(patient["id"])
    assert denormalized["latest_activity_category"] == "HIGH"
    assert denormalized["target_status"] == "NOT_AT_TARGET"


def test_the_moderate_ceiling_separates_only_the_score_above_it():
    """All three scores in one practice: only 22.10 leaves `MODERATE`.

    PRD §3.2: "Once the category is known, the treat-to-target advice in
    `escalation_recommendation` follows immediately."

    Design: Difficulty/boundary_precision_check/cdai_exactly_at_moderate_ceiling_scores_moderate_not_high
    """
    scenario, rows = _three_patient_practice()

    scored = [
        score_visit(scenario, _ceiling_payload(pga), visit["id"])
        for (pga, (_patient_row, visit)) in zip((3.9, 4.0, 4.1), rows)
    ]

    assert [row["activity_score"] for row in scored] == [21.90, 22.00, 22.10]
    assert [row["activity_category"] for row in scored] == ["MODERATE", "MODERATE", "HIGH"]
    assert [row["escalation_recommendation"] for row in scored] == [
        "OPTIMIZE_CURRENT",
        "OPTIMIZE_CURRENT",
        "ESCALATE",
    ]
    assert all(row["status"] == "SCORED" for row in scored)
