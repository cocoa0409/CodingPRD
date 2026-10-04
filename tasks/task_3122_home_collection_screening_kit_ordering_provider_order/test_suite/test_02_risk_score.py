"""Advisory weighted risk screen score."""
from test_helpers import (
    TEST_USERS,
    create_patient,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]


def test_risk_score_weighted_recent_symptoms_vs_family_history(api):
    """PRD §3.2: "The score adds 5 points if `recent_symptoms` is true, 3
    points if `comorbidity` is true, and 2 points if `family_history` is true
    — each flag contributing its weight when set and zero otherwise,
    producing a whole-number `score` between 0 and 10."

    Design: Difficulty/dual_variant_calc/risk_score_weighted_vs_unweighted_channel_flip
    """
    pa = create_patient(external_ref="p-risk-a", recent_symptoms=True,
                        comorbidity=False, family_history=False)
    pb = create_patient(external_ref="p-risk-b", recent_symptoms=False,
                        comorbidity=False, family_history=True)

    score_a = validate_success(api.get_patient_risk_score(pa["id"], PA))
    score_b = validate_success(api.get_patient_risk_score(pb["id"], PA))
    assert score_a["score"] == 5
    assert score_b["score"] == 2
    assert score_a["score"] != score_b["score"]


def test_risk_score_equal_flag_count_both_home_kit_ok(api):
    """PRD §3.2: "When the score is 6 or higher, the response's
    `recommended_channel` is `CLINIC`, an advisory that a home kit is not the
    recommended modality; a score of 5 or lower yields `HOME_KIT_OK`."

    Design: Difficulty/dual_variant_calc/risk_score_weighted_vs_unweighted_channel_flip
    """
    pa = create_patient(external_ref="p-risk-a2", recent_symptoms=True)
    pb = create_patient(external_ref="p-risk-b2", family_history=True)

    score_a = validate_success(api.get_patient_risk_score(pa["id"], PA))
    score_b = validate_success(api.get_patient_risk_score(pb["id"], PA))
    assert score_a["recommended_channel"] == "HOME_KIT_OK"
    assert score_b["recommended_channel"] == "HOME_KIT_OK"


def test_risk_score_clinic_threshold_crossing(api):
    """PRD §3.2: "When the score is 6 or higher, the response's
    `recommended_channel` is `CLINIC`, an advisory that a home kit is not the
    recommended modality; a score of 5 or lower yields `HOME_KIT_OK`."

    Design: Corner/calculations/risk_score_clinic_threshold_exact
    """
    pa = create_patient(external_ref="p-thr-a", comorbidity=True, family_history=True)
    pb = create_patient(external_ref="p-thr-b", recent_symptoms=True, comorbidity=True)

    score_a = validate_success(api.get_patient_risk_score(pa["id"], PA))
    score_b = validate_success(api.get_patient_risk_score(pb["id"], PA))
    assert score_a["score"] == 5
    assert score_a["recommended_channel"] == "HOME_KIT_OK"
    assert score_b["score"] == 8
    assert score_b["recommended_channel"] == "CLINIC"
