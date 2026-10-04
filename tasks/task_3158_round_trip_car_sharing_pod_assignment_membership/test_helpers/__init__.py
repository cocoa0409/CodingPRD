"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
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
from .types import *
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .constants import *
from .assertions import *
from .factories import *
from .test_users import TEST_USERS, make_account_admin_headers, make_member_headers
from .fixtures import *

__all__ = [
    # framework
    "GenericApiClient", "validate_success", "validate_error", "validate_paginated",
    "validate_error_is_one_of", "get_success_data", "is_valid_uuid", "is_iso8601_timestamp",
    "assert_cost_precision", "assert_version_incremented", "assert_timestamp_format",
    "assert_race_outcome", "assert_exactly_one_succeeds", "assert_at_least_one_succeeds",
    "run_race", "build_user_headers", "NON_EXISTENT_UUID",
    # PRD-specific
    "ApiClient", "api_client", "ApiErrorId", "HTTP_STATUS_CODES",
    "TEST_USERS", "make_member_headers", "make_account_admin_headers",
]