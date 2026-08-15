"""Barrel export: framework generics + PRD-specific test infrastructure."""
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
from .assertions import *
from .constants import *
from .factories import *
from .fixtures import *
from .test_users import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    make_audit_analyst_headers,
    make_carrier_rep_headers,
    make_client_viewer_headers,
    make_fap_admin_headers,
    make_finance_controller_headers,
    make_treasury_approver_headers,
)
from .types import *
