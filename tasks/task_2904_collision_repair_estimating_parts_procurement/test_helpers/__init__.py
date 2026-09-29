"""Shared test infrastructure for the collision repair estimating API suite."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
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
from .api_client import ApiClient, canonical_instant
from .api_errors import (
    HTTP_STATUS_CODES,
    NOT_FOUND_RESOLUTION_ORDER,
    ApiErrorId,
)

__all__ = [
    "ApiClient",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "NOT_FOUND_RESOLUTION_ORDER",
    "NON_EXISTENT_UUID",
    "assert_at_least_one_succeeds",
    "assert_exactly_one_succeeds",
    "assert_race_outcome",
    "assertions",
    "build_user_headers",
    "canonical_instant",
    "constants",
    "factories",
    "fixtures",
    "get_success_data",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "run_race",
    "test_users",
    "types",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
]
