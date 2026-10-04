"""Barrel export: framework generics + PRD-specific helpers."""
# Framework generics (re-exported for convenience)
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

# PRD-specific — domain types
from .types import (
    Agreement,
    AgreementStatus,
    ApplicationState,
    Cohort,
    CohortStatus,
    ConversionOutcome,
    CreditGrant,
    CreditGrantStatus,
    EducationStatus,
    EmploymentStatus,
    FeeTier,
    Industry,
    InternshipPlacement,
    InterviewOutcome,
    InterviewRound,
    Invoice,
    InvoiceStatus,
    OutcomeCheckpoint,
    Partner,
    PartnerStatus,
    PlacementState,
    ProgramPhase,
    RosterStatus,
    SatisfactionRecord,
    StipendPhase,
    StipendStatement,
    StipendStatus,
    Student,
    TrackCode,
    UserRole,
)

# PRD-specific — infrastructure
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_agreement,
    assert_cohort,
    assert_common_fields,
    assert_credit_grant,
    assert_instant_eq,
    assert_interview_round,
    assert_invoice,
    assert_outcome_checkpoint,
    assert_partner,
    assert_partner_billing_zeroed,
    assert_placement,
    assert_satisfaction_record,
    assert_stipend_statement,
    assert_student,
    parse_instant,
)
from .constants import *
from .factories import *
from .fixtures import *
from .scenarios import *
from .test_users import TEST_USERS, make_partner_headers, make_student_headers
