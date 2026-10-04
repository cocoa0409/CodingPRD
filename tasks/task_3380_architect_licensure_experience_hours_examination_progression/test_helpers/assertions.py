"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    EducationStatus, ExperienceStatus, ExamStatus, RecordStanding,
    PathType, EvaluationStatus, PracticeArea, WorkSetting, ReportStatus,
    LicenseStatus, DivisionCode, DivisionStatus, ExamResult,
    SupplementalStatus, CertificateStatus, TransmittalStatus,
    DisciplinaryStatus, AuthorizationStatus,
)


def _assert_common(data: dict):
    """PRD §2.5: server-minted bare-UUID id, ISO 8601 timestamps, integer
    version on every resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer: {data.get('version')!r}"
    )


def _enum_values(enum_cls):
    return [e.value for e in enum_cls]


def assert_candidate(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert "password" not in data, "password is stored but never returned (PRD §3.1)"
    assert isinstance(data["home_jurisdiction_code"], str)
    assert data["education_status"] in _enum_values(EducationStatus)
    assert data["experience_status"] in _enum_values(ExperienceStatus)
    assert data["exam_status"] in _enum_values(ExamStatus)
    assert isinstance(data["certificate_eligible"], bool)
    assert data["record_standing"] in _enum_values(RecordStanding)


def assert_jurisdiction(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["requires_supplemental_exam"], bool)
    assert isinstance(data["min_total_experience_hours"], int)
    assert isinstance(data["ce_hours_required"], int)
    assert isinstance(data["ce_hsw_hours_required"], int)
    assert isinstance(data["ce_carry_over_allowed"], bool)


def assert_supervisor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["jurisdiction_code"], str)
    assert data["license_status"] in _enum_values(LicenseStatus)


def assert_education_evaluation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["candidate_id"])
    assert data["path_type"] in _enum_values(PathType)
    assert isinstance(data["institution_name"], str)
    assert isinstance(data["semester_credit_hours"], int)
    assert data["status"] in _enum_values(EvaluationStatus)
    assert data["deficiency_notes"] is None or isinstance(data["deficiency_notes"], str)
    assert isinstance(data["review_count"], int)


def assert_experience_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["supervisor_id"])
    assert data["practice_area"] in _enum_values(PracticeArea)
    assert isinstance(data["hours"], (int, float))
    assert isinstance(data["work_period_start"], str)
    assert isinstance(data["work_period_end"], str)
    assert data["work_setting"] in _enum_values(WorkSetting)
    assert data["status"] in _enum_values(ReportStatus)
    assert data["submitted_at"] is None or isinstance(data["submitted_at"], str)
    assert isinstance(data["credit_pct"], int)
    assert isinstance(data["credited_hours"], int)
    assert data["return_reason"] is None or isinstance(data["return_reason"], str)


def assert_exam_authorization(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["candidate_id"])
    assert isinstance(data["jurisdiction_code"], str)
    assert data["status"] in _enum_values(AuthorizationStatus)


def assert_exam_division_progress(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["candidate_id"])
    assert isinstance(data["authorization_id"], str)
    assert data["division_code"] in _enum_values(DivisionCode)
    assert data["status"] in _enum_values(DivisionStatus)
    assert data["scheduled_date"] is None or isinstance(data["scheduled_date"], str)
    assert isinstance(data["attempt_count"], int)
    assert isinstance(data["attempt_dates"], list)
    assert data["last_failed_at"] is None or isinstance(data["last_failed_at"], str)
    assert data["passed_at"] is None or isinstance(data["passed_at"], str)
    assert data["expires_at"] is None or isinstance(data["expires_at"], str)
    assert data["result"] is None or data["result"] in _enum_values(ExamResult)
    assert data["scaled_score"] is None or isinstance(data["scaled_score"], int)


def assert_supplemental_exam(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["candidate_id"])
    assert isinstance(data["jurisdiction_code"], str)
    assert isinstance(data["exam_date"], str)
    assert data["status"] in _enum_values(SupplementalStatus)
    assert data["result"] is None or data["result"] in _enum_values(ExamResult)


def assert_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["candidate_id"])
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["home_jurisdiction_code"], str)
    assert isinstance(data["ce_hours_required"], int)
    assert isinstance(data["ce_hsw_hours_required"], int)
    assert data["status"] in _enum_values(CertificateStatus)
    assert isinstance(data["issued_at"], str)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["renewal_count"], int)
    assert isinstance(data["ce_hours_current_period"], int)
    assert isinstance(data["ce_hsw_current_period"], int)
    assert isinstance(data["lifetime_ce_hours"], int)


def assert_ce_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["certificate_id"])
    assert isinstance(data["hours"], int)
    assert isinstance(data["hsw"], bool)
    assert isinstance(data["completed_date"], str)
    assert isinstance(data["provider"], str)
    assert isinstance(data["voided"], bool)


def assert_transmittal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["certificate_id"])
    assert isinstance(data["jurisdiction_code"], str)
    assert data["status"] in _enum_values(TransmittalStatus)
    assert data["denial_reason"] is None or isinstance(data["denial_reason"], str)


def assert_disciplinary_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["candidate_id"])
    assert isinstance(data["jurisdiction_code"], str)
    assert isinstance(data["allegation"], str) and data["allegation"]
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]
    assert data["status"] in _enum_values(DisciplinaryStatus)
    assert data["resolution_notes"] is None or isinstance(data["resolution_notes"], str)
