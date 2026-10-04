"""Barrel export: framework generics + PRD-specific helpers.

Test modules import everything from here:

    from test_helpers import (
        api_client, TEST_USERS, make_lab_operator_headers,
        create_account, setup_run_ready, ApiErrorId, ...
    )
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
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    make_account_manager_headers,
    make_field_service_engineer_headers,
    make_finance_admin_headers,
    make_lab_operator_headers,
    make_platform_admin_headers,
    make_supply_planner_headers,
)
from .fixtures import *
