"""Test infrastructure for the Comprehensive Plan Update API compliance suite.

Re-exports the framework primitives alongside the domain-specific client, error
catalogue, assertions, payload factories and composite setup helpers, so a test
module needs a single import block.
"""

from prd_bench_local_runner.testing import (  # noqa: F401
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

from . import assertions, constants, factories, fixtures, test_users  # noqa: F401
from .api_client import PlanningApiClient, canonical_instant, canonicalise  # noqa: F401
from .api_errors import ERROR_HTTP_STATUS, PATH_NOT_FOUND_CODES  # noqa: F401

__all__ = [
    "NON_EXISTENT_UUID",
    "GenericApiClient",
    "PlanningApiClient",
    "canonical_instant",
    "canonicalise",
    "ERROR_HTTP_STATUS",
    "PATH_NOT_FOUND_CODES",
    "validate_success",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "get_success_data",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "assert_cost_precision",
    "assert_version_incremented",
    "assert_timestamp_format",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "run_race",
    "build_user_headers",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
]
