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

from .api_client import ApiClient, api_client, canonical_instant, same_instant  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    BOARD_ANALYST_USER_ID,
    BUREAU_ADMIN_USER_ID,
    CENTER_SCHEDULER_USER_ID,
    INCENTIVE_APPROVER_2_USER_ID,
    INCENTIVE_APPROVER_USER_ID,
    ROLE_HEADER_KEYS,
    SALES_MANAGER_2_USER_ID,
    SALES_MANAGER_USER_ID,
    SERVICES_MANAGER_USER_ID,
    TEST_USERS,
    headers_for_role,
    headers_with_blank_role,
    headers_with_blank_user_id,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    make_hotel_partner_headers,
    make_incentive_approver_headers,
    make_meeting_planner_headers,
    make_sales_manager_headers,
)
from .types import *  # noqa: F401,F403
