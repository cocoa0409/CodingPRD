"""Per-entity response assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _uuid(data, field="id"):
    assert is_valid_uuid(data.get(field, "")), f"{field} must be a valid UUID"


def _ts(data, field):
    value = data.get(field)
    assert is_iso8601_timestamp(value), f"{field} must be an ISO 8601 UTC timestamp, got {value!r}"


def _opt_ts(data, field):
    value = data.get(field)
    if value is not None:
        assert is_iso8601_timestamp(value), f"{field} must be ISO 8601 or null, got {value!r}"


def _common(data):
    """id + created_at + updated_at + version — carried by every resource."""
    _uuid(data)
    _ts(data, "created_at")
    _ts(data, "updated_at")
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_facility(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["facility_type"] in ["HOSPITAL", "IMAGING_CENTER", "MOBILE_UNIT"]
    assert data["facility_status"] in ["PENDING", "ENROLLED", "DEFERRED", "SUSPENDED"]
    assert data["accreditation_currency"] in ["PROVISIONAL", "CURRENT", "LAPSED", "SUSPENDED"]
    assert data["payer_participation_status"] in ["ACTIVE", "AT_RISK", "REVOKED"]
    assert data["roster_disposition"] in ["CLEAR", "HOLD", "HALT"]
    for counter in (
        "registry_credit_cents",
        "enrolled_unit_count",
        "deferred_unit_count",
        "current_cycle_index",
        "rejected_survey_count",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"


def assert_facility_invariants(data: dict):
    """Invariants that hold after any operation."""
    assert data["registry_credit_cents"] >= 0, "registry_credit_cents can never be negative"
    assert data["enrolled_unit_count"] >= 0
    assert data["deferred_unit_count"] >= 0
    assert data["rejected_survey_count"] >= 0


def assert_modality_unit(data: dict):
    _common(data)
    _uuid(data, "facility_id")
    assert data["modality_code"] in ["MRI", "CT", "MAMM", "PET", "US"]
    assert isinstance(data["unit_label"], str) and data["unit_label"]
    assert data["unit_status"] in ["ENROLLED", "DEFERRED", "WITHDRAWN"]
    _opt_ts(data, "clinical_deadline_at")
    _opt_ts(data, "testing_deadline_at")
    _opt_ts(data, "last_survey_at")
    for counter in ("phantom_attempt_count", "phantom_failure_count", "deficiency_open_count"):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
    assert data["last_phantom_score"] is None or isinstance(data["last_phantom_score"], (int, float))


def assert_equipment_item(data: dict):
    _common(data)
    _uuid(data, "unit_id")
    assert isinstance(data["manufacturer"], str) and data["manufacturer"]
    assert isinstance(data["model_number"], str) and data["model_number"]
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["modality_code"] in ["MRI", "CT", "MAMM", "PET", "US"]
    _ts(data, "installed_on")
    assert data["equipment_status"] in ["ACTIVE", "OUT_OF_SERVICE", "RETIRED"]
    assert data["performance_verdict"] in ["PASS", "FAIL", "PENDING"]


def assert_clinical_image_submission(data: dict):
    _common(data)
    _uuid(data, "unit_id")
    assert data["image_type"] in ["CLINICAL", "PHANTOM_REFERENCE"]
    _ts(data, "submitted_at")
    assert isinstance(data["reviewer_note_code"], str)
    assert isinstance(data["required_view_count"], int)
    assert isinstance(data["accepted_view_count"], int)
    assert data["review_status"] in [
        "PENDING_REVIEW", "ACCEPTED", "DEFICIENCY", "FAILED", "RESUBMITTED",
    ]
    assert data["deficiency_code"] in ["NONE", "IMAGE_QUALITY", "POSITIONING", "ARTIFACT", "DOSE"]
    _opt_ts(data, "deficiency_issued_at")
    _opt_ts(data, "deficiency_deadline_at")
    assert isinstance(data["resubmission_round"], int)


def assert_phantom_test(data: dict):
    _common(data)
    _uuid(data, "unit_id")
    assert isinstance(data["phantom_serial_code"], str) and data["phantom_serial_code"]
    _ts(data, "acquired_at")
    assert isinstance(data["duration_minutes"], int)
    assert data["result_status"] in ["ACQUIRED", "SCORED", "PASS", "FAIL", "VOIDED"]
    _opt_ts(data, "scored_at")
    assert data["phantom_total_score"] is None or isinstance(data["phantom_total_score"], (int, float))


def assert_physicist_survey(data: dict):
    _common(data)
    _uuid(data, "facility_id")
    _uuid(data, "physicist_qualification_id")
    assert data["survey_type"] in ["ANNUAL", "INITIAL", "POST_REPAIR"]
    _ts(data, "scheduled_at")
    _opt_ts(data, "performed_at")
    assert isinstance(data["reference_entrance_dose_mgy"], (int, float))
    assert data["survey_status"] in [
        "SCHEDULED", "SUBMITTED", "ACCEPTED", "REJECTED",
        "CORRECTIVE_REQUIRED", "RESUBMITTED",
    ]
    assert data["rejection_code"] in [
        "NONE", "CREDENTIAL_LAPSED", "DOSE_OUT_OF_RANGE", "SHIELDING_FAILED",
        "DOCUMENTATION_INCOMPLETE",
    ]


def assert_personnel_qualification(data: dict):
    _common(data)
    _uuid(data, "facility_id")
    assert isinstance(data["person_name"], str) and data["person_name"]
    assert data["personnel_role"] in [
        "INTERPRETING_PHYSICIAN", "TECHNOLOGIST", "MEDICAL_PHYSICIST",
    ]
    assert isinstance(data["credential_number"], str) and data["credential_number"]
    assert isinstance(data["ce_credit_hours"], (int, float))
    assert isinstance(data["required_ce_hours"], (int, float))
    _ts(data, "credential_expires_on")
    assert data["credential_status"] in ["PENDING", "VERIFIED", "LAPSED", "REVOKED"]
    _opt_ts(data, "qualification_verified_at")
    assert isinstance(data["survey_count"], int)


def assert_corrective_action_plan(data: dict):
    _common(data)
    _uuid(data, "facility_id")
    _uuid(data, "source_submission_id")
    assert data["deficiency_code"] in ["IMAGE_QUALITY", "POSITIONING", "ARTIFACT", "DOSE"]
    assert data["plan_status"] in ["OPEN", "SUBMITTED", "ACCEPTED", "REJECTED", "EXPIRED"]
    assert data["deadline_status"] in ["ON_TRACK", "DUE_SOON", "OVERDUE"]
    _ts(data, "due_at")
    _ts(data, "resubmission_deadline_at")
    assert isinstance(data["resubmission_attempts"], int)


def assert_accreditation_cycle(data: dict):
    _common(data)
    _uuid(data, "facility_id")
    assert isinstance(data["cycle_index"], int)
    _ts(data, "cycle_started_at")
    _ts(data, "cycle_expires_at")
    assert data["cycle_status"] in ["PENDING", "ACTIVE", "RENEWAL_DUE", "RENEWED", "LAPSED"]
    assert data["benchmark_submission_status"] in [
        "NOT_STARTED", "PARTIAL", "COMPLETE", "OVERDUE",
    ]
    assert data["audit_selection_status"] in ["NOT_APPLICABLE", "SELECTED", "WAIVED"]
    assert data["audit_outcome"] in ["PENDING", "PASS", "FAIL"]


def assert_dose_registry_record(data: dict):
    _common(data)
    _uuid(data, "unit_id")
    assert data["exam_category_code"] in [
        "CT_HEAD", "CT_ABDOMEN", "MAMM_SCREEN", "PET_TORSO",
    ]
    _ts(data, "exam_month")
    assert isinstance(data["dose_index_value"], (int, float))
    assert data["benchmark_status"] in [
        "NOT_EVALUATED", "WITHIN_BENCHMARK", "ABOVE_BENCHMARK", "CRITICAL",
    ]
    assert data["submission_status"] in ["STAGED", "SUBMITTED", "REJECTED"]
    _opt_ts(data, "submitted_at")
    assert isinstance(data["registry_fee_cents"], int)


def assert_deadline_status(plan: dict, expected: str, current_clock: str):
    """Assert a plan's deadline_status equals the band implied by its due_at."""
    assert plan["deadline_status"] == expected, (
        f"Expected deadline_status {expected} at clock {current_clock}, "
        f"got {plan['deadline_status']} (due_at {plan['due_at']})"
    )


def assert_registry_balance_conserved(after: int, before: int):
    assert after == before, f"registry_credit_cents drifted: {before} -> {after}"