"""Barrel export: framework generics + Watch Warning Issuance PRD-specific code.

Tests import everything from ``test_helpers`` -- one import source.
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

# PRD-specific infrastructure
from .types import *  # noqa: F401,F403
from .types import __all__ as _types_all
from .api_client import ALERTS, ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .assertions import __all__ as _assertions_all
from .factories import *  # noqa: F401,F403
from .factories import __all__ as _factories_all
from .constants import *  # noqa: F401,F403
from .constants import __all__ as _constants_all
from .test_users import *  # noqa: F401,F403
from .test_users import TEST_USERS
from .test_users import __all__ as _test_users_all
from .fixtures import *  # noqa: F401,F403
from .fixtures import __all__ as _fixtures_all

__all__ = (
    [
        # framework
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
        # PRD-specific
        "ALERTS",
        "ApiClient",
        "api_client",
        "ApiErrorId",
        "HTTP_STATUS_CODES",
        "TEST_USERS",
    ]
    + list(_types_all)
    + list(_assertions_all)
    + list(_factories_all)
    + list(_constants_all)
    + list(_test_users_all)
    + list(_fixtures_all)
)
