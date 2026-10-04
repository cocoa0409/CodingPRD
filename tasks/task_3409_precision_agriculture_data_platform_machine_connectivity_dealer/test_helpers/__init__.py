"""Shared test infrastructure for the Precision Ag Connectivity API.

Barrel export: framework generics plus the PRD-specific client, errors,
types, assertions, factories, constants, role headers, and fixtures.  Tests
import everything from here.
"""

# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success,
    validate_error,
    validate_paginated,
    validate_error_is_one_of,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    run_race,
    build_user_headers,
    NON_EXISTENT_UUID,
)

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient, canonical_instant, same_instant
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (
    TEST_USERS,
    ADMIN,
    SYSTEM,
    AGRONOMIST,
    COOP_ANALYST,
    INDEPENDENT,
    ADMIN_USER_ID,
    SYSTEM_USER_ID,
    AGRONOMIST_USER_ID,
    AGRONOMIST_2_USER_ID,
    COOP_ANALYST_USER_ID,
    INDEPENDENT_USER_ID,
    INDEPENDENT_2_USER_ID,
    UNKNOWN_ROLE_HEADERS,
    MISSING_USER_ID_HEADERS,
    MISSING_USER_ROLE_HEADERS,
    make_grower_manager_headers,
    make_dealer_technician_headers,
    make_partner_app_headers,
    make_agronomist_headers,
    make_coop_analyst_headers,
    make_independent_technician_headers,
    make_platform_admin_headers,
    make_system_headers,
    headers_for,
)
from .fixtures import *  # noqa: F401,F403
