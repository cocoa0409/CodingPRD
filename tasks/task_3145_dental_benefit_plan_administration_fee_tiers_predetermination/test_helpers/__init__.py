"""Barrel export: framework generics plus PRD-specific infrastructure."""

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
from .constants import *  # noqa: F401,F403
from .api_errors import *  # noqa: F401,F403
from .api_client import ApiClient, api_client, canonical_instant, same_instant
from .test_users import (
    ADMIN,
    EXAMINER,
    NETWORK,
    NO_HEADERS,
    REVIEWER_1,
    REVIEWER_2,
    TEST_USERS,
    headers_for,
    make_member_headers,
    make_provider_headers,
    make_reviewer_headers,
)
from . import factories  # noqa: F401
from .factories import *  # noqa: F401,F403
from .assertions import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .fixtures import api, client  # noqa: F401
