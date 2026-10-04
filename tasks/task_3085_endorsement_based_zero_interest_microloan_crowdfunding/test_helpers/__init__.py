"""Barrel export: framework generics + PRD-specific infrastructure."""
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

# PRD-specific
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .api_errors import *  # noqa: F401,F403  (flat ERR_* names)
from .assertions import (
    assert_application,
    assert_borrower,
    assert_contribution,
    assert_endorsement,
    assert_impact_report,
    assert_installment,
    assert_invite,
    assert_lender,
    assert_loan,
    assert_loan_invariants,
    assert_payment,
    assert_trustee,
)
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_anonymous_headers,
    make_borrower_headers,
    make_lender_headers,
    make_trustee_headers,
)
from .types import *  # noqa: F401,F403
