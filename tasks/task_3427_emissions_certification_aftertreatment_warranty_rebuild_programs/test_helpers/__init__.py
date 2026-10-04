"""Barrel export: framework generics + PRD-specific helpers.

Tests import everything from test_helpers — one import source.
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
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (
    ADJUDICATOR_USER_ID,
    ADMIN_USER_ID,
    CERTIFIER_USER_ID,
    ENGINEER_USER_ID,
    OFFICER_USER_ID,
    PLANNER_USER_ID,
    SUBMITTER_USER_ID,
    TEST_USERS,
    make_certification_engineer_headers,
    make_fleet_manager_headers,
    make_platform_admin_headers,
    make_regulatory_officer_headers,
    make_reman_planner_headers,
    make_service_advisor_headers,
    make_warranty_adjudicator_headers,
)
from .fixtures import *  # noqa: F401,F403
