"""Payload factories — one per create operation, input fields only."""

from . import constants as C


def facility_payload(**overrides) -> dict:
    """Create-facility body (PRD §2.5)."""
    payload = {"name": C.FACILITY_NAME, "state_code": C.FACILITY_STATE}
    payload.update(overrides)
    return payload


def bed_payload(**overrides) -> dict:
    """Create-bed body (PRD §2.9)."""
    payload = {
        "unit_name": "North Wing",
        "bed_label": C.BED_LABEL_35,
        "level_of_care": "ASAM_3_5",
        "cleaning_turnaround_hours": C.CLEANING_HOURS_35,
    }
    payload.update(overrides)
    return payload


def service_offering_payload(**overrides) -> dict:
    """Create-service-offering body (PRD §2.5)."""
    payload = {
        "service_code": C.SERVICE_CODE_RES,
        "level_of_care": "ASAM_3_5",
        "required_min_credential_tier": "TIER_3_LICENSED",
        "requires_medical_provider": False,
    }
    payload.update(overrides)
    return payload


def clinician_payload(**overrides) -> dict:
    """Create-clinician body (PRD §2.5)."""
    payload = {
        "full_name": "Dr. Astrid Lindqvist",
        "credential_tier": "TIER_4_INDEPENDENT",
        "is_medical_provider": True,
    }
    payload.update(overrides)
    return payload


def facility_credential_payload(facility_id: str, **overrides) -> dict:
    """Grant-a-facility-credential body (PRD §2.5)."""
    payload = {
        "facility_id": facility_id,
        "effective_at": C.CREDENTIAL_EFFECTIVE_AT,
        "expires_at": C.CREDENTIAL_EXPIRES_AT,
    }
    payload.update(overrides)
    return payload


def payer_payload(**overrides) -> dict:
    """Create-payer body (PRD §2.8)."""
    payload = {
        "name": C.PAYER_NAME,
        "initial_authorized_days_by_loc": dict(C.PAYER_INITIAL_DAYS),
        "step_down_coverage_map": {k: list(v) for k, v in C.PAYER_STEP_DOWN_COVERAGE.items()},
        "concurrent_review_interval_days": C.PAYER_REVIEW_INTERVAL_DAYS,
        "credential_min_tier_by_loc": dict(C.PAYER_CREDENTIAL_FLOORS),
    }
    payload.update(overrides)
    return payload


def accreditation_payload(**overrides) -> dict:
    """Record-an-accreditation body (PRD §2.5, §3.9)."""
    payload = {
        "accreditation_class": "ACCREDITATION_BODY",
        "granting_body": "CARF",
        "effective_at": C.CREDENTIAL_EFFECTIVE_AT,
        "expires_at": C.CREDENTIAL_EXPIRES_AT,
    }
    payload.update(overrides)
    return payload


def state_license_payload(**overrides) -> dict:
    """Record a STATE_LICENSE accreditation permitting ASAM_3_5 (PRD §2.5)."""
    payload = accreditation_payload(
        accreditation_class="STATE_LICENSE",
        granting_body="MN-DHS",
        license_level_max="ASAM_3_5",
        credential_tier_min="TIER_3_LICENSED",
    )
    payload.update(overrides)
    return payload


def episode_payload(**overrides) -> dict:
    """Open-an-episode body (PRD §3.1). ``assigned_level`` is optional and unset by default."""
    payload = {"patient_ref": C.PATIENT_REF}
    payload.update(overrides)
    return payload


def assessment_payload(assessor_clinician_id: str, **overrides) -> dict:
    """Begin-an-assessment body (PRD §3.1). ``placement_basis`` stays absent unless supplied."""
    payload = {
        "assessor_clinician_id": assessor_clinician_id,
        "dimension_scores": dict(C.SCORES_ASAM_3_5),
    }
    payload.update(overrides)
    return payload


def authorization_payload(payer_id: str, requested_level: str = "ASAM_3_5", **overrides) -> dict:
    """Request-an-authorization body (PRD §3.2)."""
    payload = {"payer_id": payer_id, "requested_level": requested_level}
    payload.update(overrides)
    return payload


def clearance_payload(clearance_type: str = "MEDICAL", **overrides) -> dict:
    """Order-a-clearance body (PRD §3.3)."""
    payload = {"clearance_type": clearance_type}
    payload.update(overrides)
    return payload


def withdrawal_management_payload(**overrides) -> dict:
    """Author-a-withdrawal-management-record body (PRD §3.3)."""
    payload = {
        "protocol": "ALCOHOL_TAPER",
        "ciwa_score": 12,
        "dose_records": [],
    }
    payload.update(overrides)
    return payload


def treatment_plan_payload(
    author_clinician_id: str, expected_treatment_episode_version: int, **overrides
) -> dict:
    """Draft-a-treatment-plan body (PRD §3.4)."""
    payload = {
        "author_clinician_id": author_clinician_id,
        "cosign_rationale_code": "ASAM-PLAN-V1",
        "expected_treatment_episode_version": expected_treatment_episode_version,
    }
    payload.update(overrides)
    return payload


def session_payload(
    service_id: str, clinician_id: str, scheduled_at: str, **overrides
) -> dict:
    """Schedule-a-session body (PRD §3.4)."""
    payload = {
        "service_id": service_id,
        "clinician_id": clinician_id,
        "scheduled_at": scheduled_at,
        "duration_minutes": 60,
    }
    payload.update(overrides)
    return payload


def level_of_care_change_payload(
    authorization_id: str,
    to_level: str,
    effective_at: str,
    expected_treatment_episode_version: int,
    **overrides,
) -> dict:
    """Appoint-a-level-of-care-change body (PRD §3.6)."""
    payload = {
        "authorization_id": authorization_id,
        "to_level": to_level,
        "effective_at": effective_at,
        "expected_treatment_episode_version": expected_treatment_episode_version,
    }
    payload.update(overrides)
    return payload


def continuing_care_plan_payload(
    authorizing_clinician_id: str,
    expected_treatment_episode_version: int,
    **overrides,
) -> dict:
    """Draft-a-continuing-care-plan body (PRD §3.8)."""
    payload = {
        "housing_selection_basis": "RANKED_AUTO",
        "housing_window_start": "2026-09-07T00:00:00Z",
        "housing_window_end": "2026-10-07T00:00:00Z",
        "alumni_contact_interval_days": 7,
        "alumni_contacts_required": 2,
        "authorizing_clinician_id": authorizing_clinician_id,
        "shelter_class": "RESIDENTIAL",
        "wants_recovery_only_house": True,
        "expected_treatment_episode_version": expected_treatment_episode_version,
    }
    payload.update(overrides)
    return payload


def recovery_housing_payload(**overrides) -> dict:
    """Create-a-recovery-housing-row body (PRD §2.9)."""
    payload = {
        "house_name": "Cedar House",
        "proximity_rank": 1,
        "day_rate_cents": 1000,
        "capacity_beds": 4,
    }
    payload.update(overrides)
    return payload


def alumni_contact_payload(scheduled_for: str, attempt_number: int, **overrides) -> dict:
    """File-an-ad-hoc-alumni-contact body (PRD §3.8)."""
    payload = {"scheduled_for": scheduled_for, "attempt_number": attempt_number}
    payload.update(overrides)
    return payload
