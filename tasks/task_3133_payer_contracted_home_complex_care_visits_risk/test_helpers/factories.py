"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PROGRAM_CODE": "LMRK-TX",
    "DISPLAY_NAME": "Landmark TX",
    "GEOGRAPHY_ZIPS": ["75201"],
    "SLA_HOURS": 24,
    "PAYER_NAME": "PlanA",
    "EFFECTIVE": "2026-01-01T00:00:00Z",
    "EXPIRATION": "2027-12-31T23:59:59Z",
    "PMPM_RATE_CENTS": 500000,
    "SS_BASELINE_CENTS": 600000,
    "SS_SPLIT": 0.50,
    "NPI": "1234567890",
    "PCP_NAME": "Dr. Patel",
    "PRACTICE": "DFM",
    "CLINICIAN_NAME": "Nancy NP",
    "HOME_ZIP": "75201",
    "MAX_DAILY_VISITS": 5,
    "MEMBER_EXTERNAL_ID": "M-001",
    "MEMBER_NAME": "Member X",
    "DOB": "1950-01-01T00:00:00Z",
    "CONSENT_DOC": "DOC-1",
}


def create_care_program_payload(**overrides):
    payload = {
        "program_code": DEFAULTS["PROGRAM_CODE"],
        "display_name": DEFAULTS["DISPLAY_NAME"],
        "service_geography_zips": list(DEFAULTS["GEOGRAPHY_ZIPS"]),
        "urgent_response_sla_hours": DEFAULTS["SLA_HOURS"],
    }
    payload.update(overrides)
    return payload


def create_capitated_contract_payload(care_program_id, **overrides):
    payload = {
        "care_program_id": care_program_id,
        "payer_name": DEFAULTS["PAYER_NAME"],
        "contract_effective_date": DEFAULTS["EFFECTIVE"],
        "contract_expiration_date": DEFAULTS["EXPIRATION"],
        "payment_model": "CAPITATED",
        "pmpm_rate_cents": DEFAULTS["PMPM_RATE_CENTS"],
        "quality_withhold_pct": 0.10,
        "min_performance_threshold": 0.80,
    }
    payload.update(overrides)
    return payload


def create_shared_savings_contract_payload(care_program_id, **overrides):
    payload = {
        "care_program_id": care_program_id,
        "payer_name": "PlanSS",
        "contract_effective_date": DEFAULTS["EFFECTIVE"],
        "contract_expiration_date": DEFAULTS["EXPIRATION"],
        "payment_model": "SHARED_SAVINGS",
        "shared_savings_baseline_pmpm_cents": DEFAULTS["SS_BASELINE_CENTS"],
        "shared_savings_split_pct": DEFAULTS["SS_SPLIT"],
        "quality_withhold_pct": 0.10,
        "min_performance_threshold": 0.80,
    }
    payload.update(overrides)
    return payload


def create_pcp_provider_payload(care_program_id, **overrides):
    payload = {
        "care_program_id": care_program_id,
        "npi": DEFAULTS["NPI"],
        "full_name": DEFAULTS["PCP_NAME"],
        "practice_name": DEFAULTS["PRACTICE"],
        "notification_opt_in": True,
    }
    payload.update(overrides)
    return payload


def create_clinician_payload(care_program_id, **overrides):
    payload = {
        "care_program_id": care_program_id,
        "full_name": DEFAULTS["CLINICIAN_NAME"],
        "discipline": "NP",
        "home_zip": DEFAULTS["HOME_ZIP"],
        "max_daily_visits": DEFAULTS["MAX_DAILY_VISITS"],
    }
    payload.update(overrides)
    return payload


def create_member_payload(care_program_id, payer_contract_id, pcp_provider_id, **overrides):
    payload = {
        "care_program_id": care_program_id,
        "payer_contract_id": payer_contract_id,
        "member_external_id": DEFAULTS["MEMBER_EXTERNAL_ID"],
        "full_name": DEFAULTS["MEMBER_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
        "address_zip": DEFAULTS["HOME_ZIP"],
        "pcp_provider_id": pcp_provider_id,
        "chronic_condition_codes": ["CHF"],
        "prior_ed_visits_12mo": 1,
        "prior_inpatient_admits_12mo": 1,
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(expected_member_version, **overrides):
    payload = {
        "outreach_channel": "PHONE",
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


def create_visit_payload(enrollment_id, **overrides):
    payload = {
        "enrollment_id": enrollment_id,
        "visit_type": "ROUTINE_FOLLOWUP",
        "scheduled_start": "2026-09-02T09:00:00Z",
        "scheduled_end": "2026-09-02T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_assessment_payload(**overrides):
    payload = {
        "medication_reconciliation": {
            "medications_reviewed": 5,
            "discrepancies_found": 1,
            "high_risk_med_changes": 0,
        },
        "safety_evaluation": {
            "fall_risk_score": 2,
            "home_hazard_count": 0,
            "adl_impairment_count": 0,
        },
        "social_needs_screening": {
            "food_insecurity": False,
            "housing_instability": False,
            "transportation_barrier": False,
            "social_isolation_score": 1,
        },
        "pcp_coordination_note": "PCP informed.",
    }
    payload.update(overrides)
    return payload


def create_urgent_episode_payload(enrollment_id, **overrides):
    payload = {
        "enrollment_id": enrollment_id,
        "trigger_source": "MEMBER_CALL",
    }
    payload.update(overrides)
    return payload


def create_medical_cost_payload(payer_contract_id, member_id, **overrides):
    payload = {
        "payer_contract_id": payer_contract_id,
        "member_id": member_id,
        "period_index": 0,
        "amount_cents": 450000,
        "incurred_date": "2026-08-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload
