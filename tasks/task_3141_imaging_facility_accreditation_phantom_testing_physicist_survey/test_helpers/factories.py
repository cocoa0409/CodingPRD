"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

DEFAULTS = TEST_DEFAULTS


def create_facility_payload(**overrides) -> dict:
    """Payload for POST /accreditation/facilities."""
    payload = {
        "name": DEFAULTS["FACILITY_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "facility_type": DEFAULTS["FACILITY_TYPE"],
    }
    payload.update(overrides)
    return payload


def create_modality_unit_payload(facility_id, expected_facility_version, **overrides) -> dict:
    """Payload for POST /accreditation/modality-units."""
    payload = {
        "facility_id": facility_id,
        "modality_code": DEFAULTS["MODALITY_CODE"],
        "unit_label": DEFAULTS["UNIT_LABEL"],
        "expected_facility_version": expected_facility_version,
    }
    payload.update(overrides)
    return payload


def create_equipment_payload(unit_id, **overrides) -> dict:
    """Payload for POST /accreditation/equipment."""
    payload = {
        "unit_id": unit_id,
        "manufacturer": DEFAULTS["MANUFACTURER"],
        "model_number": DEFAULTS["MODEL_NUMBER"],
        "serial_number": DEFAULTS["SERIAL_NUMBER"],
        "modality_code": DEFAULTS["MODALITY_CODE"],
        "installed_on": DEFAULTS["INSTALLED_ON"],
    }
    payload.update(overrides)
    return payload


def create_clinical_image_submission_payload(unit_id, expected_unit_version, **overrides) -> dict:
    """Payload for POST /accreditation/clinical-image-submissions."""
    payload = {
        "unit_id": unit_id,
        "image_type": "CLINICAL",
        "submitted_at": "2026-09-12T00:00:00Z",
        "reviewer_note_code": "NOTE-1",
        "required_view_count": 10,
        "accepted_view_count": 10,
        "expected_unit_version": expected_unit_version,
    }
    payload.update(overrides)
    return payload


def create_clinical_resubmission_payload(expected_unit_version, **overrides) -> dict:
    """Payload for POST /accreditation/clinical-image-submissions/{id}/resubmit."""
    payload = {
        "submitted_at": "2026-09-14T00:00:00Z",
        "reviewer_note_code": "NOTE-2",
        "accepted_view_count": 10,
        "expected_unit_version": expected_unit_version,
    }
    payload.update(overrides)
    return payload


def create_phantom_test_payload(unit_id, **overrides) -> dict:
    """Payload for POST /accreditation/phantom-tests."""
    payload = {
        "unit_id": unit_id,
        "phantom_serial_code": DEFAULTS["PHANTOM_SERIAL_CODE"],
        "acquired_at": DEFAULTS["PHANTOM_ACQUIRED_AT"],
        "duration_minutes": DEFAULTS["PHANTOM_DURATION_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_phantom_score_payload(**overrides) -> dict:
    """Payload for POST /accreditation/phantom-tests/{id}/score."""
    payload = {
        "spatial_resolution_score": 9,
        "contrast_score": 9,
        "artifact_score": 9,
        "scored_at": "2026-09-13T01:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_physicist_survey_payload(facility_id, physicist_qualification_id, **overrides) -> dict:
    """Payload for POST /accreditation/physicist-surveys."""
    payload = {
        "facility_id": facility_id,
        "physicist_qualification_id": physicist_qualification_id,
        "survey_type": "ANNUAL",
        "scheduled_at": DEFAULTS["SURVEY_SCHEDULED_AT"],
        "reference_entrance_dose_mgy": DEFAULTS["REFERENCE_DOSE_MGY"],
    }
    payload.update(overrides)
    return payload


def create_survey_submission_payload(**overrides) -> dict:
    """Payload for POST /accreditation/physicist-surveys/{id}/submit."""
    payload = {
        "performed_at": DEFAULTS["SURVEY_PERFORMED_AT"],
        "measured_entrance_dose_mgy": DEFAULTS["MEASURED_DOSE_MGY"],
        "shielding_verdict": "PASS",
    }
    payload.update(overrides)
    return payload


def create_survey_resubmission_payload(**overrides) -> dict:
    """Payload for POST /accreditation/physicist-surveys/{id}/resubmit."""
    payload = {
        "measured_entrance_dose_mgy": DEFAULTS["MEASURED_DOSE_MGY"],
        "shielding_verdict": "PASS",
    }
    payload.update(overrides)
    return payload


def create_qualification_payload(facility_id, **overrides) -> dict:
    """Payload for POST /accreditation/qualifications."""
    payload = {
        "facility_id": facility_id,
        "person_name": DEFAULTS["TECH_NAME"],
        "personnel_role": "TECHNOLOGIST",
        "credential_number": DEFAULTS["TECH_CREDENTIAL_NUMBER"],
        "ce_credit_hours": 24.0,
        "required_ce_hours": 24.0,
        "credential_expires_on": DEFAULTS["TECH_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def create_physicist_qualification_payload(facility_id, **overrides) -> dict:
    """Payload for a MEDICAL_PHYSICIST qualification."""
    payload = create_qualification_payload(
        facility_id,
        person_name=DEFAULTS["PHYSICIST_NAME"],
        personnel_role="MEDICAL_PHYSICIST",
        credential_number=DEFAULTS["PHYSICIST_CREDENTIAL_NUMBER"],
        ce_credit_hours=50.0,
        required_ce_hours=50.0,
        credential_expires_on=DEFAULTS["PHYSICIST_EXPIRES_ON"],
    )
    payload.update(overrides)
    return payload


def create_verify_payload(**overrides) -> dict:
    """Payload for POST /accreditation/qualifications/{id}/verify."""
    payload = {"verified_at": DEFAULTS["VERIFIED_AT"]}
    payload.update(overrides)
    return payload


def create_accreditation_cycle_payload(facility_id, **overrides) -> dict:
    """Payload for POST /accreditation/cycles."""
    payload = {
        "facility_id": facility_id,
        "cycle_index": 1,
        "cycle_started_at": DEFAULTS["CYCLE_STARTED_AT"],
    }
    payload.update(overrides)
    return payload


def create_registry_credit_payload(expected_facility_version, **overrides) -> dict:
    """Payload for POST /accreditation/facilities/{id}/registry-credit."""
    payload = {
        "amount_cents": DEFAULTS["REGISTRY_CREDIT_TOPUP"],
        "expected_facility_version": expected_facility_version,
    }
    payload.update(overrides)
    return payload


def create_dose_registry_record_payload(unit_id, **overrides) -> dict:
    """Payload for POST /accreditation/dose-registry-records."""
    payload = {
        "unit_id": unit_id,
        "exam_category_code": "CT_HEAD",
        "exam_month": "2026-07-01T00:00:00Z",
        "dose_index_value": 2.3,
    }
    payload.update(overrides)
    return payload


def create_clock_payload(current_utc, **overrides) -> dict:
    """Payload for POST /_clock/set_current_utc."""
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


def create_review_payload(review_outcome, **overrides) -> dict:
    """Payload for POST /accreditation/clinical-image-submissions/{id}/review."""
    payload = {"review_outcome": review_outcome}
    payload.update(overrides)
    return payload


def create_version_payload(parent_version, field="expected_facility_version", **overrides) -> dict:
    """A single-field OCC echo body."""
    payload = {field: parent_version}
    payload.update(overrides)
    return payload


def create_versionless_payload(**overrides) -> dict:
    """An empty action body (e.g. accept/reject/void/activate)."""
    payload = {}
    payload.update(overrides)
    return payload