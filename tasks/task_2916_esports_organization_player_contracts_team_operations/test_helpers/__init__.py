"""Test infrastructure for the esports league API.

Re-exports the framework's generic validators alongside the domain-specific
client, payload factories, assertions, identity headers and setup fixtures, so
test modules can import everything they need from one place.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
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

from . import assertions, constants, factories, fixtures, types
from .api_client import ApiClient, api_client, canonical_instant
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    TEST_USERS,
    headers_without_role,
    headers_without_user_id,
    make_coaching_staff_headers,
    make_finance_officer_headers,
    make_general_manager_headers,
    make_guardian_representative_headers,
    make_headers,
    make_league_admin_headers,
    make_ops_manager_headers,
    make_performance_support_headers,
    make_player_agent_headers,
    make_scout_headers,
    make_sponsorship_manager_headers,
)
from .types import *  # noqa: F401,F403
