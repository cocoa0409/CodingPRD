"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CENTER_NAME": "Harbor Center",
    "NEIGHBORHOOD_CODE": "CHI-HARBOR-02",
    "OPENED_ON": "2026-09-01",
    "TEAM_LABEL": "Team Blue",
    "PANEL_CAP": 300,
    "PHYSICIAN_COUNT": 2,
    "CHW_COUNT": 2,
    "BEHAVIORAL_COUNT": 1,
    "ROOM_LABEL": "R1",
    "PLATE": "IL-1234",
    "SEAT_CAPACITY": 4,
    "EVENT_LABEL": "Health Fair",
    "SCHEDULED_ON": "2026-09-20",
    "EXPECTED_ATTENDANCE": 25,
    "FULL_NAME": "Della Roe",
    "DATE_OF_BIRTH": "1955-04-12",
    "ZIP_CODE": "60607",
    "RISK_SCORE": 1.00,
    "PLAN_NAME": "MA Gold",
    "CONTRACT_TYPE": "FULL_RISK",
    "BASE_PMPM_CENTS": 90000,
    "RISK_ADJUST_FACTOR": 1.00,
    "REVENUE_SHARE_PCT": 1.00,
    "EFFECTIVE_MONTH": "2026-09",
    "DURATION_MINUTES": 40,
    "APPT_KIND": "PRIMARY",
    "CHANNEL": "AFTER_HOURS_LINE",
    "SEVERITY": "LOW",
    "CLAIM_CATEGORY": "ED_VISIT",
    "AMOUNT_CENTS": 5000,
    "PERIOD_MONTH": "2026-09",
}


def create_center_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CENTER_NAME"],
        "neighborhood_code": DEFAULTS["NEIGHBORHOOD_CODE"],
        "opened_on": DEFAULTS["OPENED_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_care_team_payload(**overrides) -> dict:
    defaults = {
        "team_label": DEFAULTS["TEAM_LABEL"],
        "panel_cap": DEFAULTS["PANEL_CAP"],
        "physician_count": DEFAULTS["PHYSICIAN_COUNT"],
        "chw_count": DEFAULTS["CHW_COUNT"],
        "behavioral_count": DEFAULTS["BEHAVIORAL_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {"room_label": DEFAULTS["ROOM_LABEL"]}
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "plate": DEFAULTS["PLATE"],
        "seat_capacity": DEFAULTS["SEAT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_outreach_event_payload(**overrides) -> dict:
    defaults = {
        "event_label": DEFAULTS["EVENT_LABEL"],
        "scheduled_on": DEFAULTS["SCHEDULED_ON"],
        "expected_attendance": DEFAULTS["EXPECTED_ATTENDANCE"],
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["FULL_NAME"],
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
        "zip_code": DEFAULTS["ZIP_CODE"],
        "risk_score": DEFAULTS["RISK_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_health_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_name": DEFAULTS["PLAN_NAME"],
        "contract_type": DEFAULTS["CONTRACT_TYPE"],
        "base_pmpm_cents": DEFAULTS["BASE_PMPM_CENTS"],
        "risk_adjust_factor": DEFAULTS["RISK_ADJUST_FACTOR"],
        "revenue_share_pct": DEFAULTS["REVENUE_SHARE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_attribution_payload(patient_id, health_plan_id, care_team_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "health_plan_id": health_plan_id,
        "care_team_id": care_team_id,
        "effective_month": DEFAULTS["EFFECTIVE_MONTH"],
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(care_team_id, patient_id, room_id, **overrides) -> dict:
    defaults = {
        "care_team_id": care_team_id,
        "patient_id": patient_id,
        "room_id": room_id,
        "start_utc": "2026-09-10T14:00:00Z",
        "duration_minutes": DEFAULTS["DURATION_MINUTES"],
        "kind": DEFAULTS["APPT_KIND"],
    }
    defaults.update(overrides)
    return defaults


def create_triage_case_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "channel": DEFAULTS["CHANNEL"],
        "severity": DEFAULTS["SEVERITY"],
    }
    defaults.update(overrides)
    return defaults


def create_cost_claim_payload(center_id, patient_id, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "patient_id": patient_id,
        "service_month": DEFAULTS["PERIOD_MONTH"],
        "category": DEFAULTS["CLAIM_CATEGORY"],
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_monthly_settlement_payload(center_id, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "period_month": DEFAULTS["PERIOD_MONTH"],
    }
    defaults.update(overrides)
    return defaults
