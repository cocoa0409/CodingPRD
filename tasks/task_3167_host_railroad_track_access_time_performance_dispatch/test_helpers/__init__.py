"""Barrel export: framework generics plus PRD-specific helpers.

Tests import everything from here and focus purely on test logic.
"""

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

from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client, canonical_instant  # noqa: F401
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    HOST_REP_HEADERS,
    PASSENGER_OPERATOR_HEADERS,
    STATE_SPONSOR_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    TEST_USERS,
    make_host_rep_headers,
)
from .fixtures import *  # noqa: F401,F403
from . import fixtures  # noqa: F401
from . import factories  # noqa: F401
