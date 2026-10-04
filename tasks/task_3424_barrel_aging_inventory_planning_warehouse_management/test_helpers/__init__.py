"""Barrel export: framework generics + PRD-specific code.

Tests import everything from here:
    from test_helpers import (
        api_client, TEST_USERS, ApiErrorId, validate_success, validate_error, ...
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

# PRD-specific modules
from .types import *
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    DEFAULT_OFFICER_USER_ID,
    DEFAULT_PREPARER_USER_ID,
    TEST_USERS,
    make_bonded_preparer_headers,
    make_compliance_officer_headers,
    make_distillery_planner_headers,
    make_master_blender_headers,
    make_operations_director_headers,
    make_platform_admin_headers,
    make_program_director_headers,
    make_warehouse_manager_headers,
)
from .fixtures import *
