"""Barrel export: framework generics + PRD-specific code.

Tests import everything from test_helpers; this module re-exports the
framework's generic validators/utilities alongside the domain types, API
client, error catalog, assertions, factories, constants, role headers, and
fixtures.
"""
# Framework generics (re-exported for convenience)
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

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    LC_JANE_ID,
    LC_JOHN_ID,
    SCI_ANNA_ID,
    SCI_BOB_ID,
    TEST_USERS,
    make_claims_scientist_headers,
    make_legal_counsel_headers,
    make_media_buyer_headers,
    make_platform_admin_headers,
    make_product_lead_headers,
    make_retail_exec_headers,
    make_sourcing_manager_headers,
)
from .fixtures import *  # noqa: F401,F403
