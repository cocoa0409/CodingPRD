"""Barrel export: framework generics + PRD-specific helpers."""
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)

from .types import (
    TermStatus, AuthorizationStatus, StaffType, CompensationPlan,
    ApplicantStatus, ApplicationStatus, TceStatus, EnrollmentStatus,
    EnrollmentIntensity, SectionStatus, PackageStatus, ScheduleEntryStatus,
    AlertTriggerType, AlertSeverity, AlertStatus, OutreachStatus, UserRole,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_term, assert_program, assert_state_authorization, assert_staff,
    assert_applicant, assert_application, assert_tce, assert_enrollment,
    assert_section, assert_section_seat_invariant, assert_aid_package,
    assert_early_alert, assert_retention_outreach,
)
from .factories import (
    create_term_payload, create_program_payload,
    create_state_authorization_payload, create_staff_payload,
    create_applicant_payload, create_application_payload,
    create_tce_payload, create_enrollment_payload, create_section_payload,
)
from .constants import (
    CLOCK_START_ISO, PELL_MAX_CENTS, COA_FULL_TIME_CENTS, COA_HALF_TIME_CENTS,
    COA_LESS_THAN_HALF_TIME_CENTS, COA_BY_INTENSITY, R2T4_EARNED_CLIFF,
    INST_HALF_REFUND_WINDOW_DAYS, MAX_CONTACTS_PER_7D, CADENCE_WINDOW_HOURS,
    ADJUNCT_SECTION_SIZE, TRANSFER_CAP_NUM, TRANSFER_CAP_DEN,
    MIN_DAYS_BETWEEN_OUTREACH, TERM_FIXTURE, TERM_CENSUS_DATE,
    TERM_MIDPOINT_DATE, TERM_OPEN_CLOCK, TERM_START_CLOCK, TERM_CENSUS_CLOCK,
    TEST_DEFAULTS,
)
from .test_users import (
    TEST_USERS, make_counselor_headers, make_advisor_headers,
    make_applicant_headers, make_fao_headers,
)
from .fixtures import (
    set_clock, create_program, authorize_state, create_term, open_term,
    create_advisor, create_counselor, create_applicant,
    create_submitted_application, admit_application, create_completed_tce,
    create_enrollment, setup_open_term_scenario, setup_registered_enrollment,
    setup_certified_package, setup_in_session_disbursing, create_aid_package,
    certify_aid_package, create_section, open_section_with_gap,
    open_zero_gap_section,
)
