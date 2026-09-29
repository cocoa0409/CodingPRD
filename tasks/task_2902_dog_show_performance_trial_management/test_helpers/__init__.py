"""Test infrastructure for the Dog Show Trials API.

Importing this package registers the error-id to HTTP-status map with the
framework's validators, so `validate_error` cross-checks the status code of
every rejection without each test having to restate it.
"""

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

from . import assertions, constants, factories, fixtures, types
from .api_client import ApiClient, PREFIX, api_client, canonical_timestamp, timestamps_equal
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .test_users import (
    REGISTRY_OFFICER_BETA_ID,
    REGISTRY_OFFICER_ID,
    SANCTION_OFFICER_BETA_ID,
    SANCTION_OFFICER_ID,
    SHOW_SECRETARY_ID,
    TEST_USERS,
    headers_with_blank_role,
    headers_with_blank_user_id,
    headers_without_role,
    headers_without_user_id,
    make_club_officer_headers,
    make_handler_headers,
    make_headers,
    make_judge_headers,
    make_registry_officer_headers,
    make_sanction_officer_headers,
    make_show_secretary_headers,
)
from .types import ALL_ROLES, UserRole

__all__ = [
    # framework re-exports
    "GenericApiClient",
    "validate_success",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "get_success_data",
    "build_user_headers",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "assert_timestamp_format",
    "assert_cost_precision",
    "assert_version_incremented",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "run_race",
    "NON_EXISTENT_UUID",
    # local modules
    "types",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    # client
    "ApiClient",
    "api_client",
    "PREFIX",
    "canonical_timestamp",
    "timestamps_equal",
    # errors
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    # users
    "TEST_USERS",
    "SANCTION_OFFICER_ID",
    "SANCTION_OFFICER_BETA_ID",
    "SHOW_SECRETARY_ID",
    "REGISTRY_OFFICER_ID",
    "REGISTRY_OFFICER_BETA_ID",
    "make_headers",
    "make_club_officer_headers",
    "make_judge_headers",
    "make_handler_headers",
    "make_sanction_officer_headers",
    "make_show_secretary_headers",
    "make_registry_officer_headers",
    "headers_with_blank_user_id",
    "headers_with_blank_role",
    "headers_without_user_id",
    "headers_without_role",
    # roles
    "UserRole",
    "ALL_ROLES",
]
