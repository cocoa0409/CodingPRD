"""Payload factories — one per entity, input fields only."""

CENTER_DEFAULTS = {
    "center_code": "CSL-DAL-014",
    "legal_name": "CSL Plasma Dallas 014",
    "state_code": "TX",
    "screening_lanes": 2,
    "donor_floor_beds": 2,
    "observation_chairs": 2,
}

DONOR_DEFAULTS = {
    "external_donor_ref": "DL-TX-000001",
    "legal_first_name": "Jane",
    "legal_last_name": "Doe",
    "date_of_birth": "1990-04-12",
    "weight_kg": 72.5,
}

SCHEDULE_DEFAULTS = {
    "effective_from": "2026-08-01T00:00:00Z",
    "effective_to": "2026-12-01T00:00:00Z",
    "base_cents_first_donation": 3000,
    "base_cents_second_donation": 2500,
    "base_cents_subsequent_donation": 2000,
}

PASS_PHYSICAL_EXAM = {
    "weight_kg": 72.5,
    "pulse_bpm": 72,
    "systolic_mmhg": 118,
    "diastolic_mmhg": 76,
    "temperature_c": 36.7,
    "hematocrit_pct": 43.0,
    "total_protein_g_dl": 7.2,
}

PASS_VIRAL_MARKER = {
    "hiv_ag_ab": "NON_REACTIVE",
    "hbv_surface_ag": "NON_REACTIVE",
    "hcv_ab": "NON_REACTIVE",
}

PASS_IDENTITY = {"document_number": "TXDL-883491"}
PASS_HEALTH_HISTORY = {"risk_flags": []}


def create_center_payload(**overrides) -> dict:
    payload = dict(CENTER_DEFAULTS)
    payload.update(overrides)
    return payload


def create_donor_payload(home_center_id, **overrides) -> dict:
    payload = dict(DONOR_DEFAULTS)
    payload["home_center_id"] = home_center_id
    payload.update(overrides)
    return payload


def create_schedule_payload(expected_center_version, **overrides) -> dict:
    payload = dict(SCHEDULE_DEFAULTS)
    payload["expected_center_version"] = expected_center_version
    payload.update(overrides)
    return payload


def create_screening_payload(center_id, scheduled_for) -> dict:
    return {"center_id": center_id, "scheduled_for": scheduled_for}


def create_donation_payload(center_id, screening_visit_id, scheduled_for) -> dict:
    return {
        "center_id": center_id,
        "screening_visit_id": screening_visit_id,
        "scheduled_for": scheduled_for,
    }


def physical_exam_payload(**overrides) -> dict:
    payload = dict(PASS_PHYSICAL_EXAM)
    payload.update(overrides)
    return payload


def viral_marker_payload(**overrides) -> dict:
    payload = dict(PASS_VIRAL_MARKER)
    payload.update(overrides)
    return payload
