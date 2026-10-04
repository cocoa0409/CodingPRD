"""Payload factories — one per entity, input fields only."""

DEFAULT_POLYGON_GEOJSON = (
    '{"type":"Polygon","coordinates":[[[-97.5,32.5],[-96.5,32.5],'
    '[-96.5,33.5],[-97.5,33.5],[-97.5,32.5]]]}'
)
DEFAULT_HOME_GEO = '{"type":"Point","coordinates":[-97.0,33.0]}'
OUTSIDE_HOME_GEO = '{"type":"Point","coordinates":[-95.0,30.0]}'


def create_market_payload(**overrides) -> dict:
    defaults = {
        "market_code": "DFW-NORTH",
        "display_name": "Dallas Fort Worth North",
        "polygon_geojson": DEFAULT_POLYGON_GEOJSON,
        "response_window_minutes_urgent": 60,
        "response_window_minutes_standard": 240,
    }
    defaults.update(overrides)
    return defaults


def create_payer_contract_payload(market_id: str, **overrides) -> dict:
    defaults = {
        "payer_code": "AETNA",
        "market_id": market_id,
        "urgent_base_rate_cents": 40000,
        "standard_base_rate_cents": 25000,
        "place_of_service_modifier_pct": 0.85,
        "max_claim_cents": 1000000,
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_formulary_entry_payload(**overrides) -> dict:
    defaults = {
        "drug_code": "IVF-NS-1L",
        "max_units_per_visit": 5,
        "requires_physician_preauth": False,
        "unit_price_cents": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Patient",
        "date_of_birth": "1980-01-01",
        "payer_code": "AETNA",
        "member_id": "M100",
        "pcp_name": "Dr. Pcp",
        "pcp_npi": "1234567890",
        "comorbidity_count": 1,
        "home_address_geo": DEFAULT_HOME_GEO,
    }
    defaults.update(overrides)
    return defaults


def create_care_team_payload(market_id: str, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "app_user_id": "app-001",
        "tech_user_id": "tech-001",
        "supervising_physician_user_id": "md-001",
        "skill_tags": ["POCT"],
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_shift_payload(care_team_id: str, market_id: str, **overrides) -> dict:
    defaults = {
        "care_team_id": care_team_id,
        "market_id": market_id,
        "vehicle_plate": "TX-TEST-1",
        "window_start": "2026-09-15T08:00:00Z",
        "window_end": "2026-09-15T20:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_visit_request_payload(patient_id: str, market_id: str, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "market_id": market_id,
        "requestor_role": "PATIENT",
        "chief_complaint": "fever",
    }
    defaults.update(overrides)
    return defaults


def create_triage_assessment_payload(**overrides) -> dict:
    defaults = {
        "heart_rate": 110,
        "systolic_bp": 100,
        "spo2_pct": 94,
        "is_chest_pain": False,
        "is_stroke_signs": False,
        "is_severe_trauma": False,
        "is_altered_mental_status": False,
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_offer_payload(expected_visit_request_version, **overrides) -> dict:
    defaults = {
        "expected_visit_request_version": expected_visit_request_version,
    }
    defaults.update(overrides)
    return defaults


def create_diagnostic_order_payload(**overrides) -> dict:
    defaults = {
        "order_kind": "POCT",
        "code": "POCT-STREP-A",
        "units": 1,
    }
    defaults.update(overrides)
    return defaults


def create_disposition_decision_payload(**overrides) -> dict:
    defaults = {
        "disposition": "DISCHARGE_HOME",
        "rationale": "Patient stable after evaluation; discharged home with precautions.",
    }
    defaults.update(overrides)
    return defaults


def create_follow_up_notice_payload(pcp_npi: str, **overrides) -> dict:
    defaults = {
        "pcp_npi": pcp_npi,
        "payload_summary": (
            "Visit summary for the patient's PCP: patient seen at home, "
            "stable on discharge."
        ),
    }
    defaults.update(overrides)
    return defaults


def create_monitoring_checkin_payload(scheduled_at: str, **overrides) -> dict:
    defaults = {"scheduled_at": scheduled_at}
    defaults.update(overrides)
    return defaults
