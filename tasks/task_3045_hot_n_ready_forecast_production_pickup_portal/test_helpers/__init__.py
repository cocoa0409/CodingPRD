"""Shared test infrastructure for the Hot-N-Ready production and pickup portal API."""

# Framework generics (re-exported for convenience)
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

from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import HotReadyApiClient  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    TEST_USERS,
    headers_without_identity,
    make_crew_headers,
    make_customer_headers,
    make_manager_headers,
    make_shift_lead_headers,
)
from .types import *  # noqa: F401,F403

__all__ = [
    "HotReadyApiClient",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "TEST_USERS",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    "headers_without_identity",
    "make_crew_headers",
    "make_customer_headers",
    "make_manager_headers",
    "make_shift_lead_headers",
]
