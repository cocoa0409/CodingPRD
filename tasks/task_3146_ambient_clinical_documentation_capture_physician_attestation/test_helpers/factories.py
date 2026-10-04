"""Payload factories — one per registry/entity, input fields only."""

import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(prefix):
    return "{0}-{1}".format(prefix, next(_counter))


def instant(year, month, day, hour=0, minute=0, second=0):
    """Build an ISO 8601 UTC instant for the logical clock."""
    return "{0:04d}-{1:02d}-{2:02d}T{3:02d}:{4:02d}:{5:02d}Z".format(
        year, month, day, hour, minute, second
    )


def create_patient_payload(**overrides):
    defaults = {
        "mrn": _uniq("MRN"),
        "full_name": "Test Patient",
    }
    defaults.update(overrides)
    return defaults


def create_physician_payload(**overrides):
    defaults = {
        "npi": _uniq("NPI"),
        "full_name": "Test Physician",
        "specialty_code": TEST_DEFAULTS["SPECIALTY"],
    }
    defaults.update(overrides)
    return defaults


def create_qa_auditor_payload(**overrides):
    defaults = {
        "employee_code": _uniq("QA"),
        "full_name": "Test Auditor",
        "specialty_codes": [TEST_DEFAULTS["SPECIALTY"]],
    }
    defaults.update(overrides)
    return defaults


def field_spec(key, importance="CRITICAL", required=True):
    return {"key": key, "importance": importance, "required": required}


def create_note_template_payload(**overrides):
    defaults = {
        "specialty_code": TEST_DEFAULTS["SPECIALTY"],
        "template_version": _uniq("tpl"),
        "field_specs": [field_spec("chief_complaint", "CRITICAL", True)],
    }
    defaults.update(overrides)
    return defaults


def create_encounter_payload(patient_id, physician_id, **overrides):
    defaults = {
        "patient_id": patient_id,
        "physician_id": physician_id,
    }
    defaults.update(overrides)
    return defaults


def grant_consent_payload(patient_id, **overrides):
    defaults = {
        "patient_id": patient_id,
        "signage_posted": True,
        "captured_via": TEST_DEFAULTS["CAPTURED_VIA"],
    }
    defaults.update(overrides)
    return defaults


def start_capture_payload(**overrides):
    defaults = {
        "planned_retention_days": TEST_DEFAULTS["PLANNED_RETENTION_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def segment_payload(**overrides):
    defaults = {
        "start_offset_ms": 0,
        "end_offset_ms": 5000,
        "speaker_role": "PHYSICIAN",
        "base_confidence": 0.95,
    }
    defaults.update(overrides)
    return defaults


def create_note_draft_payload(template_id, expected_encounter_version, **overrides):
    defaults = {
        "template_id": template_id,
        "expected_encounter_version": expected_encounter_version,
    }
    defaults.update(overrides)
    return defaults


def field_update(field_key, field_value):
    return {"field_key": field_key, "field_value": field_value}


def patch_note_draft_payload(expected_note_draft_version, field_updates, **overrides):
    defaults = {
        "expected_note_draft_version": expected_note_draft_version,
        "field_updates": field_updates,
    }
    defaults.update(overrides)
    return defaults


def billing_suggestion_payload(code_value, **overrides):
    defaults = {
        "code_type": "BILLING",
        "code_value": code_value,
        "confidence": 1.0,
        "quantity": 1,
        "unit_fee_cents": 1000,
        "adjustment_pct": 1.0,
    }
    defaults.update(overrides)
    return defaults


def diagnosis_suggestion_payload(code_value, **overrides):
    defaults = {
        "code_type": "DIAGNOSIS",
        "code_value": code_value,
        "confidence": 0.9,
    }
    defaults.update(overrides)
    return defaults


def suggestions_batch_payload(suggestions):
    return {"suggestions": suggestions}


def qa_scores_payload(accuracy_score=90, completeness_score=90, timeliness_score=90):
    return {
        "accuracy_score": accuracy_score,
        "completeness_score": completeness_score,
        "timeliness_score": timeliness_score,
    }
