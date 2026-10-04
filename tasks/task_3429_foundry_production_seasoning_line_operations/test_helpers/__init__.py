"""Barrel export: framework generics + PRD-specific helpers.

Tests import everything from here; the runner ensures the package is on
PYTHONPATH.
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
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    ENVIRONMENTAL_OFFICER_2_USER,
    ENVIRONMENTAL_OFFICER_USER,
    FOUNDRY_MANAGER_USER,
    MELT_OPERATOR_USER,
    OUTLET_MANAGER_USER,
    QUALITY_INSPECTOR_USER,
    RETAIL_PLANNER_USER,
    SEASONING_LEAD_USER,
    TEST_USERS,
    make_environmental_officer_headers,
    make_foundry_manager_headers,
    make_headers,
    make_melt_operator_headers,
    make_outlet_manager_headers,
    make_quality_inspector_headers,
    make_retail_planner_headers,
    make_seasoning_lead_headers,
)
from .fixtures import *
from .fixtures import SetupFailedError
