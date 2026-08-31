"""Payload factories - one per resource, client-supplied input fields only."""

from .constants import ALL_WORK_TYPES, TEST_DEFAULTS


def land_manager_payload(**overrides) -> dict:
    """Full-policy agency used by most fixtures (PRD section 3.1)."""
    payload = {
        "agency_name": TEST_DEFAULTS["AGENCY_NAME"],
        "jurisdiction_code": TEST_DEFAULTS["JURISDICTION_CODE"],
        "permit_required": True,
        "permit_lead_days": 14,
        "max_party_size": 20,
        "wet_threshold_index": 0.65,
        "requires_engineering_review": True,
        "requires_certified_sawyer": True,
    }
    payload.update(overrides)
    return payload


def minimal_land_manager_payload(**overrides) -> dict:
    """Only the two required inputs, so every optional field falls to its default."""
    payload = {
        "agency_name": "Coast Range State Park",
        "jurisdiction_code": "ORSP-COAST",
    }
    payload.update(overrides)
    return payload


def volunteer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Petra Novak",
        "email": "petra@example.org",
        "waiver_signed_on": "2026-07-01",
        "certifications": [],
    }
    payload.update(overrides)
    return payload


def crew_leader_volunteer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Rae Lindqvist",
        "email": "rae@example.org",
        "waiver_signed_on": "2026-07-01",
        "certifications": ["CERT_CREW_LEADER", "CERT_TRAIL_SKILLS", "CERT_FIRST_AID"],
        "first_aid_expires_on": "2027-06-30",
    }
    payload.update(overrides)
    return payload


def sawyer_volunteer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Milo Okonkwo",
        "email": "milo@example.org",
        "waiver_signed_on": "2026-07-01",
        "certifications": ["CERT_SAWYER_B", "CERT_FIRST_AID"],
        "first_aid_expires_on": "2027-06-30",
    }
    payload.update(overrides)
    return payload


def first_aider_volunteer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Nadia Farooq",
        "email": "nadia@example.org",
        "waiver_signed_on": "2026-07-01",
        "certifications": ["CERT_FIRST_AID"],
        "first_aid_expires_on": "2027-06-30",
    }
    payload.update(overrides)
    return payload


def trail_segment_payload(land_manager_id, **overrides) -> dict:
    payload = {
        "land_manager_id": land_manager_id,
        "name": TEST_DEFAULTS["SEGMENT_NAME"],
        "length_miles": TEST_DEFAULTS["SEGMENT_LENGTH_MILES"],
        "surface_class": "NATIVE_SOIL",
        "traffic_class": "MODERATE",
    }
    payload.update(overrides)
    return payload


def adoption_agreement_payload(trail_segment_id, crew_leader_volunteer_id, **overrides) -> dict:
    payload = {
        "trail_segment_id": trail_segment_id,
        "crew_leader_volunteer_id": crew_leader_volunteer_id,
        "term_start_date": TEST_DEFAULTS["TERM_START_DATE"],
        "term_end_date": TEST_DEFAULTS["TERM_END_DATE"],
    }
    payload.update(overrides)
    return payload


def work_plan_payload(adoption_agreement_id, **overrides) -> dict:
    payload = {
        "adoption_agreement_id": adoption_agreement_id,
        "season_year": TEST_DEFAULTS["SEASON_YEAR"],
        "requested_budget_cents": TEST_DEFAULTS["PLAN_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def condition_report_payload(trail_segment_id, reported_by_volunteer_id, **overrides) -> dict:
    payload = {
        "trail_segment_id": trail_segment_id,
        "reported_by_volunteer_id": reported_by_volunteer_id,
        "hazard_type": "TREAD_EROSION",
        "severity_class": "MODERATE",
        "description": "Rutting below the switchback.",
    }
    payload.update(overrides)
    return payload


def work_permit_payload(work_plan_id, trail_segment_id, **overrides) -> dict:
    payload = {
        "work_plan_id": work_plan_id,
        "trail_segment_id": trail_segment_id,
        "window_start_date": TEST_DEFAULTS["PERMIT_WINDOW_START"],
        "window_end_date": TEST_DEFAULTS["PERMIT_WINDOW_END"],
        "requested_work_types": list(ALL_WORK_TYPES),
    }
    payload.update(overrides)
    return payload


def permit_issue_payload(**overrides) -> dict:
    payload = {
        "decision": "ISSUE",
        "allowed_work_types": list(ALL_WORK_TYPES),
        "max_party_size": 12,
    }
    payload.update(overrides)
    return payload


def work_party_payload(work_plan_id, trail_segment_id, work_permit_id=None, **overrides) -> dict:
    payload = {
        "work_plan_id": work_plan_id,
        "trail_segment_id": trail_segment_id,
        "start_at": TEST_DEFAULTS["PARTY_START_AT"],
        "end_at": TEST_DEFAULTS["PARTY_END_AT"],
        "work_type": "TREAD_WORK",
        "max_participants": 8,
        "travel_allowance_minutes": 45,
    }
    if work_permit_id is not None:
        payload["work_permit_id"] = work_permit_id
    payload.update(overrides)
    return payload


def briefing_payload(**overrides) -> dict:
    payload = {"tool_checklist_complete": True, "first_aid_kit_count": 2}
    payload.update(overrides)
    return payload


def shift_registration_payload(volunteer_id, expected_work_party_version, **overrides) -> dict:
    payload = {
        "volunteer_id": volunteer_id,
        "expected_work_party_version": expected_work_party_version,
        "role_on_crew": "CREW_MEMBER",
    }
    payload.update(overrides)
    return payload


def material_order_payload(work_plan_id, expected_work_plan_version, **overrides) -> dict:
    payload = {
        "work_plan_id": work_plan_id,
        "category": "SIGNAGE",
        "lines": [{"sku": "SIGN_POST", "unit_price_cents": 41000, "quantity": 5}],
        "expected_work_plan_version": expected_work_plan_version,
    }
    payload.update(overrides)
    return payload


def incident_payload(work_party_id, **overrides) -> dict:
    payload = {
        "work_party_id": work_party_id,
        "severity_class": "MINOR",
        "first_aid_rendered": False,
        "narrative": "Blister, self-treated.",
        "occurred_at": TEST_DEFAULTS["PARTY_START_AT"],
    }
    payload.update(overrides)
    return payload


def weather_observation_payload(trail_segment_id, soil_moisture_index, observed_at, **overrides) -> dict:
    payload = {
        "trail_segment_id": trail_segment_id,
        "soil_moisture_index": soil_moisture_index,
        "observed_at": observed_at,
    }
    payload.update(overrides)
    return payload
