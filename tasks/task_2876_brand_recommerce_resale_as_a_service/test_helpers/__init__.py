"""Barrel export: framework generics + brand-recommerce-specific test code."""

# Framework generics, re-exported so tests have a single import source.
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

from .api_client import (  # noqa: F401
    ApiClient,
    api_client,
    canonical_instant,
    instants_equal,
)
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN,
    AUTH1,
    AUTH2,
    INTAKE,
    MERCH,
    PROGRAM_ADMIN_ID,
    INTAKE_AGENT_ID,
    AUTHENTICATOR_ID,
    SECOND_AUTHENTICATOR_ID,
    REFURB_TECHNICIAN_ID,
    SECOND_REFURB_TECHNICIAN_ID,
    MERCHANDISING_MANAGER_ID,
    TECH1,
    TECH2,
    TEST_USERS,
    headers_with_whitespace_user_id,
    headers_without_user_id,
    make_admin_headers,
    make_authenticator_headers,
    make_customer_headers,
    make_intake_agent_headers,
    make_merchandising_manager_headers,
    make_refurb_technician_headers,
)
from .types import *  # noqa: F401,F403
