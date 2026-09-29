"""Test infrastructure for the Community Risk Reduction & Smoke Alarm Program API.

Everything here is derived from the PRD contract only: the response envelope, the
role/identity headers, the endpoint surface, the error catalogue, the derived-field
formulae and the composite setup chains the tests need.
"""

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

from .api_client import CrrApiClient
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .test_users import (
    ADMIN,
    ANALYST,
    COORDINATOR,
    NO_AUTH_HEADERS,
    OFFICER,
    TEST_USERS,
    make_canvass_coordinator_headers,
    make_crr_technician_headers,
    make_grant_officer_headers,
    make_partner_liaison_headers,
    make_program_admin_headers,
    make_risk_analyst_headers,
)

# Backwards-compatible alias used by the conftest bridge.
ApiClient = CrrApiClient

__all__ = [
    "NON_EXISTENT_UUID",
    "ApiClient",
    "ApiErrorId",
    "CrrApiClient",
    "HTTP_STATUS_CODES",
    "TEST_USERS",
    "ADMIN",
    "ANALYST",
    "COORDINATOR",
    "OFFICER",
    "NO_AUTH_HEADERS",
    "assert_at_least_one_succeeds",
    "assert_cost_precision",
    "assert_exactly_one_succeeds",
    "assert_race_outcome",
    "assert_timestamp_format",
    "assert_version_incremented",
    "build_user_headers",
    "get_success_data",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "make_canvass_coordinator_headers",
    "make_crr_technician_headers",
    "make_grant_officer_headers",
    "make_partner_liaison_headers",
    "make_program_admin_headers",
    "make_risk_analyst_headers",
    "run_race",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
]
