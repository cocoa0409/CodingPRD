"""Barrel export: framework generics plus this API's own test infrastructure."""

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

from .api_client import ApiClient, api_client, canonical_instant, instants_equal  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    BAKER_ONE_USER_ID,
    BAKER_TWO_USER_ID,
    CAKE_DESK_USER_ID,
    DECORATOR_USER_ID,
    PLACEHOLDER_DEPARTMENT_ID,
    REGIONAL_ADMIN_USER_ID,
    TEST_USERS,
    headers_without_user_id,
    make_baker_headers,
    make_cake_desk_headers,
    make_decorator_headers,
    make_department_manager_headers,
    make_regional_admin_headers,
)
from .types import *  # noqa: F401,F403
