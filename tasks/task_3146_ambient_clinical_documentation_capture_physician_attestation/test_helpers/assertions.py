"""Entity shape assertions built on the framework's generic validators."""

from prd_bench_local_runner.testing import (
    get_success_data,  # re-exported for fixture convenience
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def _assert_common_fields(data, with_version=True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            "updated_at must be ISO 8601"
        )
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_patient(data):
    _assert_common_fields(data)
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["default_ambient_opt_in"], bool)


def assert_physician(data):
    _assert_common_fields(data)
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["specialty_code"], str) and data["specialty_code"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_qa_auditor(data):
    _assert_common_fields(data)
    assert isinstance(data["employee_code"], str) and data["employee_code"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["specialty_codes"], list) and data["specialty_codes"]
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_note_template(data):
    _assert_common_fields(data)
    assert isinstance(data["specialty_code"], str) and data["specialty_code"]
    assert isinstance(data["template_version"], str) and data["template_version"]
    assert isinstance(data["field_specs"], list) and len(data["field_specs"]) >= 1
    for spec in data["field_specs"]:
        assert spec["importance"] in ("CRITICAL", "MAJOR", "MINOR")
        assert isinstance(spec["required"], bool)
    assert isinstance(data["active"], bool)


def assert_encounter(data):
    _assert_common_fields(data)
    assert data["encounter_status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data["audio_status"] in ("NOT_RECORDING", "RECORDING_ACTIVE", "AUDIO_STOPPED")
    assert data["documentation_status"] in (
        "NOT_STARTED",
        "DRAFTING",
        "IN_REVIEW",
        "ATTESTED",
        "AMENDED",
    )
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["physician_id"])


def assert_consent(data):
    _assert_common_fields(data)
    assert data["status"] in ("GRANTED", "OPTED_OUT", "REVOKED", "EXPIRED")
    assert data["captured_via"] in ("ROOM_SIGNAGE", "VERBAL", "PORTAL")
    assert isinstance(data["signage_posted"], bool)
    if data["status"] == "GRANTED":
        assert data.get("end_reason") is None
    else:
        assert data["end_reason"] in ("OPT_OUT", "REVOKE", "EXPIRE")


def assert_audio_capture(data):
    _assert_common_fields(data)
    assert data["status"] in (
        "RECORDING",
        "PAUSED",
        "CAPTURED",
        "TRANSCRIBED",
        "PURGED",
        "RETENTION_EXPIRED",
    )
    assert isinstance(data["planned_retention_days"], int)
    assert isinstance(data["recorded_seconds"], int)
    assert isinstance(data["legal_hold"], bool)


def assert_segment(data):
    _assert_common_fields(data)
    assert data["speaker_role"] in ("PHYSICIAN", "PATIENT", "CAREGIVER", "OTHER")
    assert data["end_offset_ms"] > data["start_offset_ms"]
    assert isinstance(data["reassignment_count"], int)
    assert isinstance(data["effective_confidence"], (int, float))


def assert_note_draft(data):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT",
        "IN_REVIEW",
        "EDITED",
        "ATTESTED",
        "AMENDED",
        "VOID",
    )
    assert isinstance(data["completeness_score"], int)
    assert 0 <= data["completeness_score"] <= 100
    assert isinstance(data["billing_provisional_cents"], int)
    assert isinstance(data["billing_final_cents"], int)
    assert isinstance(data["regeneration_count"], int)
    assert isinstance(data["amendment_count"], int)


def assert_note_field(data):
    _assert_common_fields(data)
    assert isinstance(data["field_key"], str) and data["field_key"]
    assert data["importance"] in ("CRITICAL", "MAJOR", "MINOR")
    assert isinstance(data["required"], bool)
    assert data["source"] in ("SYSTEM", "AUDIO", "MANUAL")
    assert isinstance(data["validated"], bool)


def assert_attestation(data):
    # Append-only legal record: id + created_at only from the common set.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Attestation must not carry updated_at"
    assert "version" not in data, "Attestation must not carry version"
    assert data["attestation_type"] in ("INITIAL", "AMENDMENT")
    assert isinstance(data["completeness_at_attestation"], int)


def assert_code_suggestion(data):
    _assert_common_fields(data)
    assert data["code_type"] in ("DIAGNOSIS", "ORDER", "BILLING")
    assert isinstance(data["code_value"], str) and data["code_value"]
    assert data["status"] in ("SUGGESTED", "MODIFIED", "CONFIRMED", "REJECTED", "EXPIRED")
    assert isinstance(data["rank"], int) and data["rank"] >= 1
    assert isinstance(data["line_total_cents"], int)


def assert_qa_sample(data):
    _assert_common_fields(data)
    assert data["status"] in (
        "QUEUED",
        "ASSIGNED",
        "SCORED",
        "APPEALED",
        "RESCORED",
        "CLOSED",
    )
    assert data["sampling_reason"] in ("LOW_CONFIDENCE", "MANUAL")
    assert isinstance(data["appeal_count"], int)


def assert_documentation_metric(data):
    _assert_common_fields(data)
    assert data["status"] in ("PROVISIONAL", "FINAL")
    for key in ("notes_attested", "provisional_minutes", "final_minutes", "after_hours_minutes"):
        assert isinstance(data[key], int), "{0} must be an integer".format(key)
