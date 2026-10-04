"""Barrel export: framework generics + PRD-specific helpers."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)

# PRD-specific
from .types import (
    UserRole, EducationStatus, ExperienceStatus, ExamStatus, RecordStanding,
    PathType, EvaluationStatus, ReviewDecision, PracticeArea, WorkSetting,
    ReportStatus, LicenseStatus, DivisionCode, DivisionStatus, ExamResult,
    SupplementalStatus, CertificateStatus, TransmittalStatus,
    TransmittalOutcome, DisciplinaryStatus, ResolveOutcome, AuthorizationStatus,
    Candidate, Jurisdiction, Supervisor, EducationEvaluation, ExperienceReport,
    ExamAuthorization, ExamDivisionProgress, SupplementalExam, Certificate,
    CEEntry, Transmittal, DisciplinaryReport,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_candidate, assert_jurisdiction, assert_supervisor,
    assert_education_evaluation, assert_experience_report,
    assert_exam_authorization, assert_exam_division_progress,
    assert_supplemental_exam, assert_certificate, assert_ce_entry,
    assert_transmittal, assert_disciplinary_report,
)
from .factories import (
    create_jurisdiction_payload, create_candidate_payload,
    create_supervisor_payload, create_education_evaluation_payload,
    create_experience_report_payload, create_ce_entry_payload,
    create_supplemental_exam_payload, create_transmittal_payload,
    create_disciplinary_report_payload,
)
from .constants import (
    LOGICAL_CLOCK_START_ISO, LOGICAL_CLOCK_START_DATE,
    PAGINATION_DEFAULT_LIMIT,
    DEFAULT_MIN_TOTAL_EXPERIENCE_HOURS, DEFAULT_CE_HOURS_REQUIRED,
    DEFAULT_CE_HSW_HOURS_REQUIRED, ALTERNATIVE_PATH_MIN_CREDITS,
    FULL_CREDIT_PCT, HALF_CREDIT_PCT,
    MIN_HOURS_PER_REPORT, MAX_HOURS_PER_REPORT,
    AREA_MIN_HOURS, NATIONAL_TOTAL_HOURS_REQUIRED, DIVISION_CODES_ASC,
    MAX_CE_ENTRY_HOURS,
)
from .test_users import (
    TEST_USERS, make_candidate_headers, make_supervisor_headers,
    make_board_admin_headers, make_ncarb_admin_headers,
)
from .fixtures import (
    SIX_AREA_PERIODS, SIX_DIVISION_SITTINGS,
    set_clock, run_expiry_sweep,
    create_jurisdiction, create_candidate, create_active_supervisor,
    setup_registry, satisfy_education,
    create_draft_report, submit_report, verify_report,
    create_submitted_report, create_verified_report,
    verify_six_area_minima, authorize_exams,
    schedule_division, report_score, pass_division, fail_division,
    pass_all_six_divisions, setup_eligible_candidate,
    setup_certificate_holder, log_ce_entry, file_disciplinary_report,
)
