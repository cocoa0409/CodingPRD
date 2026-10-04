"""Barrel export: shared framework utilities plus this task's PRD-specific code."""
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)

from .types import *
from .api_client import api_client, ApiClient, PREFIX
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .assertions import assert_instant_equals
from .factories import *
from .constants import *
from .test_users import TEST_USERS, make_lender_headers, make_servicer_headers
from . import fixtures
from .fixtures import (
    ADMIN, UNDERWRITER, BORROWER,
    set_clock, create_book, add_rate_card, add_treaty, add_servicer, add_lender,
    submit_application, approve_delegated, underwrite_and_approve,
    approve_non_delegated, issue_loan, issue_delegated_loan, setup_loan,
    setup_loan_with_treaty, setup_two_loans, setup_bpm_and_lpm_loans,
    setup_loan_with_filed_claim, file_claim, begin_claim_review, approve_claim,
    setup_loan_with_approved_claim, setup_loan_with_claim_in_review,
    refresh_loan, settle_claim, setup_settled_claim,
    setup_loan_with_treaty_and_approved_claim, file_delinquency_report,
    setup_loan_with_deficient_reports, setup_loan_with_cancellation,
    setup_normalized_loan_with_confirmed_delinquency, setup_dispute,
    setup_two_loans_with_one_exposure_cap, setup_canonical_exposure_book,
    setup_cancelled_loan, setup_guaranteed_relief_loan,
    amortize, amortize_into_at80, AT80_UPB_CENTS, AT80_MAX_REFUND_CENTS,
    setup_loan_at_milestone, file_borrower_cancellation, file_servicer_cancellation,
    setup_cancelled_via_servicer, compensate_clock, reconcile_exposure,
    issue_treaty_loan, setup_approved_claim_for_loan,
)