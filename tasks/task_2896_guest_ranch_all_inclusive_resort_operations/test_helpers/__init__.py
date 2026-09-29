"""Test helper package for the guest ranch / all-inclusive resort API suite."""

from prd_bench_local_runner.testing import (
    GenericApiClient,
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

from . import assertions, constants, factories, fixtures, test_users, types
from .api_client import ApiClient, api_client, canonical_instant, instants_equal
from .api_errors import HTTP_STATUS_CODES, ApiErrorId

__all__ = [
    # framework generics
    "GenericApiClient",
    "NON_EXISTENT_UUID",
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
    "run_race",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
    # local modules
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
    # local names
    "ApiClient",
    "api_client",
    "canonical_instant",
    "instants_equal",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
]
