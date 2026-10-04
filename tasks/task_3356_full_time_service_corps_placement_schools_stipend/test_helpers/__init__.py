"""Test infrastructure for the Service Corps Placement API.

Re-exports the framework's generic validators and the PRD-specific pieces test
modules reach for most often: the endpoint client, the error catalog, domain
constants, entity assertions, payload factories, role headers and the
composite fixtures.
"""

# Framework generics (re-exported for convenience).
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    assert_at_least_one_succeeds,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assert_timestamp_format,
    assert_version_incremented,
    build_user_headers,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

# PRD-specific code.
from . import fixtures
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_application,
    assert_cash_conserved,
    assert_corps_member,
    assert_evaluation_report,
    assert_hour_entry,
    assert_posture_matches_headroom,
    assert_school,
    assert_site,
    assert_stipend_payment,
    assert_student,
    assert_team,
    assert_team_assignment,
)
from .constants import (
    ANNUAL_STIPEND_CENTS,
    BACKFILL_DEADLINE,
    BACKFILL_LIMIT,
    BASE_CLOCK,
    CASELOAD_LIMIT,
    DAILY_HOUR_CAP,
    EDUCATION_AWARD_FULL_CENTS,
    FULL_TERM_HOURS,
    MIN_PARTIAL_AWARD_HOURS,
    NON_EXISTENT_ID,
    PROJECTED_DAILY_HOURS,
    REPORT_WINDOW_DAYS,
    SERVICE_YEAR_END,
    SERVICE_YEAR_START,
    SCHOOL_COST_SHARE_CENTS,
    SCHOOL_TEAM_SIZE,
    STIPEND_PERIOD_DAYS,
    STIPEND_PERIODS_PER_YEAR,
    TEST_DEFAULTS,
    THRESHOLDS,
    TIGHT_HEADROOM_CENTS,
    VERIFICATION_WINDOW_DAYS,
)
from .factories import (
    application_payload,
    assignment_payload,
    clock_payload,
    evaluation_report_payload,
    hour_entry_payload,
    school_payload,
    site_payload,
    stipend_payment_payload,
    student_payload,
    team_payload,
)
from .test_users import (
    PROGRAM_MANAGER_HEADERS,
    SITE_DIRECTOR_HEADERS,
    STIPEND_ADMIN_1_HEADERS,
    STIPEND_ADMIN_2_HEADERS,
    TEST_USERS,
    make_applicant_headers,
    make_corps_member_headers,
    make_school_liaison_headers,
)
from .types import (
    AgreementStatus,
    ApplicationStatus,
    AssignmentStatus,
    AwardStatus,
    CaseloadStatus,
    CitizenshipStatus,
    DataSharingStatus,
    EducationLevel,
    EnrollmentStatus,
    ExitType,
    FundingPosture,
    FundingType,
    HourCategory,
    HourEntryStatus,
    PaymentStatus,
    ReportStatus,
    ServiceScope,
    ServiceStatus,
    SiteStatus,
    StipendStatus,
    TeamStatus,
    UserRole,
)

__all__ = [name for name in dir() if not name.startswith("_")]
