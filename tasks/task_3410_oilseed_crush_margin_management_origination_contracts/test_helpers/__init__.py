"""Barrel export: framework generics + PRD-specific helpers.

Tests import everything from test_helpers — one import source.
"""
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
from .types import *
from .types import __all__ as _types_all
from .api_client import ApiClient, ENDPOINT_SUCCESS_STATUS, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .assertions import __all__ as _assertions_all
from .factories import *
from .factories import __all__ as _factories_all
from .constants import *
from .constants import __all__ as _constants_all
from .test_users import *
from .test_users import __all__ as _test_users_all
from .fixtures import *
from .fixtures import __all__ as _fixtures_all

__all__ = (
    [
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
        "ApiClient",
        "api_client",
        "ENDPOINT_SUCCESS_STATUS",
        "ApiErrorId",
        "HTTP_STATUS_CODES",
    ]
    + list(_types_all)
    + list(_assertions_all)
    + list(_factories_all)
    + list(_constants_all)
    + list(_test_users_all)
    + list(_fixtures_all)
)
