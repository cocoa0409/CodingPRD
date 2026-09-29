"""Test infrastructure for the Essential Air Service Subsidy API.

Re-exports the domain client, factories, assertions, constants, error
identifiers, identity headers and composite state builders, alongside the
generic validators supplied by the runner framework.
"""

from prd_bench_local_runner.testing import (  # noqa: F401
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

from . import assertions, constants, factories, fixtures, test_users, types  # noqa: F401
from .api_client import ApiClient, canonical_instant  # noqa: F401
from .api_errors import ERROR_HTTP_STATUS  # noqa: F401

__all__ = [
    # framework
    "validate_success",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "get_success_data",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "assert_timestamp_format",
    "assert_cost_precision",
    "assert_version_incremented",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "run_race",
    "build_user_headers",
    "NON_EXISTENT_UUID",
    # domain
    "ApiClient",
    "canonical_instant",
    "ERROR_HTTP_STATUS",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
