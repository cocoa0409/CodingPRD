"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "ORG_LEGAL_NAME": "IntegCo",
    "ORG_BRAND_SPECIALIZATION": "FANUC",
    "ORG_RETENTION_RATE_BPS": 1000,
    "ORG_DEFAULT_PL_TARGET": "PLd",
    "SITE_NAME": "Plant A",
    "SITE_PLANT_TZ": "UTC",
    "SITE_SHIFT_WINDOWS": 2,
    "PROJECT_CODE": "P-100",
    "CONTRACTED_CYCLE_TIME_S": 10.0,
    "CONTRACT_VALUE_CENTS": 1_000_000,
    "GUARANTEED_OEE_PCT": 80.0,
    "SIM_CYCLE_TIME_S": 9.0,
    "SIM_CONFIDENCE_PCT": 100.0,
    "RISK_SCORE": 200,
    "PL_TARGET": "PLd",
    "FENCING_LENGTH_M": 40.0,
    "LIGHT_CURTAIN_ZONES": 4,
    "MUTING_REQUIRED": False,
    "ROBOT_MODEL": "FANUC M-710iC/50",
    "ROBOT_BRAND": "FANUC",
    "RATED_PAYLOAD_KG": 50.0,
    "END_EFFECTOR_WEIGHT_KG": 6.0,
    "PART_WEIGHT_KG": 4.0,
    "WRIST_INERTIA_KGM2": 10.0,
    "WRIST_INERTIA_LIMIT_KGM2": 12.0,
    "PROGRAM_NAME": "MAIN",
    "MEASURED_CYCLE_TIME_S": 9.0,
    "MEASURED_OEE_PCT": 85.0,
    "DEFECTS_OBSERVED": 0,
    "MEASURED_SIM_CYCLE_TIME_S": 9.5,
    "PACKAGE_CODE": "SPP-1",
    "LIST_PRICE_CENTS": 100_000,
    "RECOMMENDED_COVERAGE_MONTHS": 12,
    "INTERVAL_OPERATING_HOURS": 2000,
    "FIRST_DUE_AT_HOURS": 2000,
    "ATTENDEE_COUNT": 6,
}


def create_integrator_org_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["ORG_LEGAL_NAME"],
        "brand_specialization": DEFAULTS["ORG_BRAND_SPECIALIZATION"],
        "retention_rate_bps": DEFAULTS["ORG_RETENTION_RATE_BPS"],
        "default_pl_category_target": DEFAULTS["ORG_DEFAULT_PL_TARGET"],
    }
    payload.update(overrides)
    return payload


def create_integrator_user_payload(display_name, user_role, **overrides) -> dict:
    payload = {
        "display_name": display_name,
        "user_role": user_role,
    }
    payload.update(overrides)
    return payload


def create_customer_site_payload(**overrides) -> dict:
    payload = {
        "site_name": DEFAULTS["SITE_NAME"],
        "plant_tz": DEFAULTS["SITE_PLANT_TZ"],
        "shift_windows_per_day": DEFAULTS["SITE_SHIFT_WINDOWS"],
    }
    payload.update(overrides)
    return payload


def create_cell_project_payload(**overrides) -> dict:
    payload = {
        "project_code": DEFAULTS["PROJECT_CODE"],
        "contracted_cycle_time_s": DEFAULTS["CONTRACTED_CYCLE_TIME_S"],
        "contract_value_cents": DEFAULTS["CONTRACT_VALUE_CENTS"],
        "guaranteed_oee_pct": DEFAULTS["GUARANTEED_OEE_PCT"],
    }
    payload.update(overrides)
    return payload


def create_application_study_payload(expected_project_version, **overrides) -> dict:
    payload = {
        "expected_project_version": expected_project_version,
        "sim_cycle_time_s": DEFAULTS["SIM_CYCLE_TIME_S"],
        "sim_confidence_pct": DEFAULTS["SIM_CONFIDENCE_PCT"],
    }
    payload.update(overrides)
    return payload


def create_safety_risk_assessment_payload(**overrides) -> dict:
    payload = {
        "risk_score_pre_mitigation": DEFAULTS["RISK_SCORE"],
        "pl_target": DEFAULTS["PL_TARGET"],
        "fencing_length_m": DEFAULTS["FENCING_LENGTH_M"],
        "light_curtain_zones": DEFAULTS["LIGHT_CURTAIN_ZONES"],
        "muting_required": DEFAULTS["MUTING_REQUIRED"],
    }
    payload.update(overrides)
    return payload


def create_robot_selection_payload(**overrides) -> dict:
    payload = {
        "robot_model": DEFAULTS["ROBOT_MODEL"],
        "brand": DEFAULTS["ROBOT_BRAND"],
        "rated_payload_kg": DEFAULTS["RATED_PAYLOAD_KG"],
        "end_effector_weight_kg": DEFAULTS["END_EFFECTOR_WEIGHT_KG"],
        "part_weight_kg": DEFAULTS["PART_WEIGHT_KG"],
        "wrist_inertia_kgm2": DEFAULTS["WRIST_INERTIA_KGM2"],
        "wrist_inertia_limit_kgm2": DEFAULTS["WRIST_INERTIA_LIMIT_KGM2"],
    }
    payload.update(overrides)
    return payload


def create_robot_program_payload(**overrides) -> dict:
    payload = {
        "program_name": DEFAULTS["PROGRAM_NAME"],
    }
    payload.update(overrides)
    return payload


def create_acceptance_test_payload(phase, **overrides) -> dict:
    payload = {
        "phase": phase,
        "measured_cycle_time_s": DEFAULTS["MEASURED_CYCLE_TIME_S"],
        "measured_oee_pct": DEFAULTS["MEASURED_OEE_PCT"],
        "defects_observed": DEFAULTS["DEFECTS_OBSERVED"],
    }
    payload.update(overrides)
    return payload


def create_spare_parts_package_payload(**overrides) -> dict:
    payload = {
        "package_code": DEFAULTS["PACKAGE_CODE"],
        "list_price_cents": DEFAULTS["LIST_PRICE_CENTS"],
        "recommended_coverage_months": DEFAULTS["RECOMMENDED_COVERAGE_MONTHS"],
    }
    payload.update(overrides)
    return payload


def create_maintenance_plan_payload(**overrides) -> dict:
    payload = {
        "interval_operating_hours": DEFAULTS["INTERVAL_OPERATING_HOURS"],
        "first_due_at_hours": DEFAULTS["FIRST_DUE_AT_HOURS"],
    }
    payload.update(overrides)
    return payload


def create_training_session_payload(
    audience, scheduled_start_utc, scheduled_end_utc, trainer_user_id, **overrides
) -> dict:
    payload = {
        "audience": audience,
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
        "trainer_user_id": trainer_user_id,
        "attendee_count": DEFAULTS["ATTENDEE_COUNT"],
    }
    payload.update(overrides)
    return payload


def record_simulation_payload(measured_sim_cycle_time_s=None, **overrides) -> dict:
    payload = {
        "measured_sim_cycle_time_s": (
            measured_sim_cycle_time_s
            if measured_sim_cycle_time_s is not None
            else DEFAULTS["MEASURED_SIM_CYCLE_TIME_S"]
        ),
    }
    payload.update(overrides)
    return payload


def close_guarantee_payload(outcome, observed_cycle_time_s, observed_uptime_pct) -> dict:
    return {
        "outcome": outcome,
        "observed_cycle_time_s": observed_cycle_time_s,
        "observed_uptime_pct": observed_uptime_pct,
    }


def waive_guarantee_payload(waiver_reference) -> dict:
    return {"waiver_reference": waiver_reference}


def retention_ledger_entry_payload(
    expected_project_version, entry_type, amount_cents, milestone_ref="MANUAL"
) -> dict:
    return {
        "expected_project_version": expected_project_version,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "milestone_ref": milestone_ref,
    }
