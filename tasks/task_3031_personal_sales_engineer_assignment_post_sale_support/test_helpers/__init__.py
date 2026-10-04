"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success,
    validate_error,
    validate_paginated,
    validate_error_is_one_of,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    run_race,
    build_user_headers,
    NON_EXISTENT_UUID,
)

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import TEST_USERS, make_engineer_headers
from .fixtures import *  # noqa: F401,F403

# Convenience re-exports so tests can import every role constant by name.
from .fixtures import (
    PLATFORM_ADMIN,
    SALES_OPS,
    SETUP_TECH,
    SUPPORT_AGENT,
    SERVICE_DEPT,
    ANONYMOUS,
)

__all__ = [
    # framework
    "validate_success", "validate_error", "validate_paginated",
    "validate_error_is_one_of", "get_success_data",
    "is_valid_uuid", "is_iso8601_timestamp", "assert_cost_precision",
    "assert_version_incremented", "assert_timestamp_format",
    "assert_race_outcome", "assert_exactly_one_succeeds", "assert_at_least_one_succeeds",
    "run_race", "build_user_headers", "NON_EXISTENT_UUID",
    # prd
    "api_client", "ApiClient", "ApiErrorId", "HTTP_STATUS_CODES", "TEST_USERS",
    "PLATFORM_ADMIN", "SALES_OPS", "SETUP_TECH", "SUPPORT_AGENT", "SERVICE_DEPT",
    "ANONYMOUS", "make_engineer_headers",
]