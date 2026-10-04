"""Barrel export: framework generics plus PRD-specific helpers.

Tests import everything from this one module: the framework's generic
validators and race utilities, this PRD's types, API client, error catalogue,
assertions, payload factories, constants, role headers, and composite
fixtures.
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
from .types import *
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    TEST_USERS,
    UNDECLARED_ROLE,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    make_capacity_planner_headers,
    make_device_maker_headers,
    make_finance_controller_headers,
    make_legal_counsel_headers,
    make_platform_admin_headers,
    make_program_manager_headers,
)
from .fixtures import *
