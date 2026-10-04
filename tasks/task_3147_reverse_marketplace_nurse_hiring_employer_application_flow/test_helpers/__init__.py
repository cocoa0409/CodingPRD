"""Barrel export: framework generics + PRD-specific code."""
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

from . import fixtures  # noqa: F401
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, HTTP_STATUS_CODES_BY_ID, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .test_users import ADMIN, TEST_USERS, make_candidate_headers, make_employer_headers  # noqa: F401
from .types import *  # noqa: F401,F403

__all__ = [
    "validate_success", "validate_error", "validate_paginated",
    "validate_error_is_one_of", "get_success_data",
    "is_valid_uuid", "is_iso8601_timestamp",
    "assert_cost_precision", "assert_version_incremented", "assert_timestamp_format",
    "assert_race_outcome", "assert_exactly_one_succeeds", "assert_at_least_one_succeeds",
    "run_race", "build_user_headers", "NON_EXISTENT_UUID",
    "api_client", "ApiClient", "ApiErrorId", "HTTP_STATUS_CODES", "HTTP_STATUS_CODES_BY_ID",
    "TEST_USERS", "ADMIN", "make_candidate_headers", "make_employer_headers", "fixtures",
]
