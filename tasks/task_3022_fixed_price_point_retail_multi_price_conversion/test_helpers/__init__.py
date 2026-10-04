"""Test infrastructure for the Fixed-Price-Point Retail Multi-Price Conversion API.

Re-exports the generic framework helpers so tests have a single import source,
plus the domain-specific client, types, factories, constants and fixtures.
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

# Domain-specific
from .types import *
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES, E
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    TEST_USERS,
    USER_CONTEXT,
    headers_for,
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    BUYER_HEADERS,
    DCO_HEADERS,
    IMPORT_HEADERS,
    LEGAL_HEADERS,
    PLANNER_HEADERS,
    SOM_HEADERS,
)
from .fixtures import *