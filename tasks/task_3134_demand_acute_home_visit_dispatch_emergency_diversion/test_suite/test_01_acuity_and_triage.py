"""Acuity scoring, band assignment, and emergency-diversion triage rules."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_market_payload,
    create_patient_payload,
    create_triage_assessment_payload,
    create_visit_request_payload,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
NURSE = TEST_USERS["triage_nurse_headers"]


def _market_and_patient(**patient_overrides):
    set_clock()
    market = get_success_data(api_client.create_market(create_market_payload(), ADMIN))
    patient = get_success_data(
        api_client.create_patient(create_patient_payload(**patient_overrides), NURSE)
    )
    return market, patient


def _visit_with_triage(market_id, patient_id, vitals, chief_complaint="fever"):
    vr = get_success_data(
        api_client.create_visit_request(
            create_visit_request_payload(
                patient_id, market_id, chief_complaint=chief_complaint
            ),
            NURSE,
        )
    )
    trg = get_success_data(
        api_client.create_triage_assessment(
            vr["id"], create_triage_assessment_payload(**vitals), NURSE
        )
    )
    return vr, trg


class TestAcuityScoreCombinatorics:
    def test_score_40_elderly_comorbid_yields_standard_band(self, api):
        """PRD §3.3: "Age contributes 10 points for a patient aged at least 75, 5
        points for at least 65 but under 75, and nothing younger; age in whole
        years is the floor of the elapsed days between the patient's
        `date_of_birth` and the logical-clock date divided by 365.25.
        Comorbidity burden contributes three points per documented condition,
        capped at 15 points."
        PRD §3.3: "at least 30 but below 50 is `STANDARD`".

        Design: Difficulty/combinatorial_formula/acuity_score_combinatorial_inputs_with_state_branches
        """
        market, patient = _market_and_patient(
            full_name="P1 Elderly",
            date_of_birth="1950-01-01",
            comorbidity_count=5,
        )
        vr, trg = _visit_with_triage(
            market["id"], patient["id"],
            {"heart_rate": 110, "systolic_bp": 100, "spo2_pct": 93,
             "is_chest_pain": False, "is_stroke_signs": False,
             "is_severe_trauma": False, "is_altered_mental_status": False},
            chief_complaint="weakness",
        )
        submitted = validate_success(
            api.submit_triage_assessment(trg["id"], {"outcome": "APPROPRIATE"}, NURSE)
        )
        # 10 age (76) + 15 comorbidity (5*3 capped) + 7 hr (|110-80|//4)
        # + 4 bp (|100-120|//5) + 4 spo2 ((95-93)*2) = 40
        assert submitted["acuity_score"] == 40
        vr_after = validate_success(api.get_visit_request(vr["id"], NURSE))
        assert vr_after["acuity_band"] == "STANDARD"

    def test_red_flag_plus_score_60_yields_emergent_override(self, api):
        """PRD §3.3: "Red-flag symptoms contribute 20 points each, so four true
        flags contribute 80 points before any vital is considered."
        PRD §3.3: "If any red-flag symptom is true, the band is `EMERGENT`
        regardless of the numeric score".

        Design: Difficulty/combinatorial_formula/acuity_score_combinatorial_inputs_with_state_branches
        """
        market, patient = _market_and_patient(
            full_name="P2 Elderly Chest",
            date_of_birth="1950-01-01",
            comorbidity_count=5,
        )
        vr, trg = _visit_with_triage(
            market["id"], patient["id"],
            {"heart_rate": 110, "systolic_bp": 100, "spo2_pct": 93,
             "is_chest_pain": True, "is_stroke_signs": False,
             "is_severe_trauma": False, "is_altered_mental_status": False},
            chief_complaint="chest pressure",
        )
        submitted = validate_success(
            api.submit_triage_assessment(
                trg["id"], {"outcome": "EMERGENCY_DIVERTED"}, NURSE
            )
        )
        assert submitted["acuity_score"] == 60  # 40 + 20 red-flag
        vr_after = validate_success(api.get_visit_request(vr["id"], NURSE))
        assert vr_after["acuity_band"] == "EMERGENT"

    def test_zero_score_young_healthy_yields_non_acute(self, api):
        """PRD §3.3: "below 30 is `NON_ACUTE`".
        PRD §3.3: "The raw sum of all six components is clamped into the 0–100
        range to yield the final `acuity_score`."

        Design: Difficulty/combinatorial_formula/acuity_score_combinatorial_inputs_with_state_branches
        """
        market, patient = _market_and_patient(
            full_name="P3 Young Healthy",
            date_of_birth="1990-01-01",
            comorbidity_count=0,
        )
        vr, trg = _visit_with_triage(
            market["id"], patient["id"],
            {"heart_rate": 80, "systolic_bp": 120, "spo2_pct": 99,
             "is_chest_pain": False, "is_stroke_signs": False,
             "is_severe_trauma": False, "is_altered_mental_status": False},
            chief_complaint="mild cold",
        )
        submitted = validate_success(
            api.submit_triage_assessment(
                trg["id"], {"outcome": "INAPPROPRIATE"}, NURSE
            )
        )
        assert submitted["acuity_score"] == 0
        vr_after = validate_success(api.get_visit_request(vr["id"], NURSE))
        assert vr_after["acuity_band"] == "NON_ACUTE"


class TestRedFlagOverrideVsNumericBand:
    def test_low_score_with_chest_pain_diverts_to_ems(self, api):
        """PRD §3.3: "If any red-flag symptom is true, the band is `EMERGENT`
        regardless of the numeric score — even a score below 80 cannot soften
        a red flag."
        PRD §3.3: "An `EMERGENCY_DIVERTED` submission sets the visit's band to
        `EMERGENT`, moves the visit to the terminal `EMS_DIVERTED` state,
        decrements the market's `open_visit_count` by one, and creates an
        **EmsHandoff** row".

        Design: Difficulty/dual_variant_calc/acuity_score_red_flag_override_vs_numeric_band
        """
        market, patient = _market_and_patient(
            full_name="Bob Baker", date_of_birth="1990-01-15", comorbidity_count=0
        )
        vr, trg = _visit_with_triage(
            market["id"], patient["id"],
            {"heart_rate": 80, "systolic_bp": 120, "spo2_pct": 98,
             "is_chest_pain": True, "is_stroke_signs": False,
             "is_severe_trauma": False, "is_altered_mental_status": False},
            chief_complaint="mild chest discomfort",
        )
        submitted = validate_success(
            api.submit_triage_assessment(
                trg["id"], {"outcome": "EMERGENCY_DIVERTED"}, NURSE
            )
        )
        assert submitted["acuity_score"] == 20  # red-flag points only
        vr_after = validate_success(api.get_visit_request(vr["id"], NURSE))
        assert vr_after["acuity_band"] == "EMERGENT"
        assert vr_after["status"] == "EMS_DIVERTED"
        handoffs = validate_success(api.list_visit_ems_handoffs(vr["id"], NURSE))
        assert len(handoffs) == 1

    def test_identical_vitals_without_red_flag_declines_as_non_acute(self, api):
        """PRD §3.3: "An `INAPPROPRIATE` submission sets the band to
        `NON_ACUTE`, moves the visit to the terminal `DECLINED` state, and
        decrements the market's `open_visit_count` by one."

        Design: Difficulty/dual_variant_calc/acuity_score_red_flag_override_vs_numeric_band
        """
        market, patient = _market_and_patient(
            full_name="Bob Baker Twin", date_of_birth="1990-01-15",
            comorbidity_count=0,
        )
        vr, trg = _visit_with_triage(
            market["id"], patient["id"],
            {"heart_rate": 80, "systolic_bp": 120, "spo2_pct": 98,
             "is_chest_pain": False, "is_stroke_signs": False,
             "is_severe_trauma": False, "is_altered_mental_status": False},
            chief_complaint="general malaise",
        )
        submitted = validate_success(
            api.submit_triage_assessment(
                trg["id"], {"outcome": "INAPPROPRIATE"}, NURSE
            )
        )
        assert submitted["acuity_score"] == 0
        vr_after = validate_success(api.get_visit_request(vr["id"], NURSE))
        assert vr_after["acuity_band"] == "NON_ACUTE"
        assert vr_after["status"] == "DECLINED"
        handoffs = validate_success(api.list_visit_ems_handoffs(vr["id"], NURSE))
        assert handoffs == []


class TestTriageViolations:
    def test_appropriate_with_red_flag_rejected(self, api):
        """PRD §3.3: "Declaring `APPROPRIATE` while any red-flag symptom is
        true is rejected with `ERR_RED_FLAG_REQUIRES_EMS` (HTTP 422)."

        Design: Corner/validations/red_flag_requires_ems_error
        """
        market, patient = _market_and_patient(
            full_name="Ana A", comorbidity_count=0, pcp_npi="1111111112"
        )
        vr, trg = _visit_with_triage(
            market["id"], patient["id"],
            {"heart_rate": 100, "systolic_bp": 140, "spo2_pct": 96,
             "is_chest_pain": False, "is_stroke_signs": True,
             "is_severe_trauma": False, "is_altered_mental_status": False},
            chief_complaint="slurred speech",
        )
        resp = api.submit_triage_assessment(trg["id"], {"outcome": "APPROPRIATE"}, NURSE)
        validate_error(resp, ApiErrorId.ERR_RED_FLAG_REQUIRES_EMS)
        trg_after = validate_success(api.get_triage_assessment(trg["id"], NURSE))
        assert trg_after["outcome"] == "DRAFT"

    def test_out_of_coverage_patient_rejected(self, api):
        """PRD §3.2: "the patient's `home_address_geo` must lie inside that
        market's `polygon_geojson` boundary (else `ERR_OUT_OF_COVERAGE`,
        HTTP 422)."

        Design: Corner/validations/out_of_coverage_patient_rejected
        """
        set_clock()
        market = get_success_data(api.create_market(create_market_payload(), ADMIN))
        patient = get_success_data(
            api.create_patient(
                create_patient_payload(
                    full_name="Ben B",
                    pcp_npi="2222222223",
                    home_address_geo='{"type":"Point","coordinates":[-95.0,30.0]}',
                ),
                NURSE,
            )
        )
        resp = api.create_visit_request(
            create_visit_request_payload(patient["id"], market["id"]), NURSE
        )
        validate_error(resp, ApiErrorId.ERR_OUT_OF_COVERAGE)

    def test_second_triage_submit_rejected_not_draft(self, api):
        """PRD §3.3: "Submitting an assessment whose outcome is no longer
        `DRAFT` is rejected with `ERR_TRIAGE_NOT_DRAFT` (HTTP 409)."

        Design: Corner/state_machines/triage_submit_twice_returns_invalid_state
        """
        market, patient = _market_and_patient(
            full_name="Vic V", comorbidity_count=0, pcp_npi="9999999995"
        )
        vr, trg = _visit_with_triage(
            market["id"], patient["id"],
            {"heart_rate": 100, "systolic_bp": 120, "spo2_pct": 97,
             "is_chest_pain": False, "is_stroke_signs": False,
             "is_severe_trauma": False, "is_altered_mental_status": False},
        )
        validate_success(
            api.submit_triage_assessment(trg["id"], {"outcome": "APPROPRIATE"}, NURSE)
        )
        resp = api.submit_triage_assessment(trg["id"], {"outcome": "APPROPRIATE"}, NURSE)
        validate_error(resp, ApiErrorId.ERR_TRIAGE_NOT_DRAFT)
        trg_after = validate_success(api.get_triage_assessment(trg["id"], NURSE))
        assert trg_after["outcome"] == "APPROPRIATE"
