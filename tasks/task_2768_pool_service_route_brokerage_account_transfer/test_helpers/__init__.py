"""Test helper package for the pool service route brokerage API.

Re-exports the framework generics alongside the domain-specific helpers so a
test module needs a single import line.
"""
from prd_bench_local_runner.testing import (  # noqa: F401
    NON_EXISTENT_UUID,
    GenericApiClient,
    assert_at_least_one_succeeds,
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

from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import ApiClient, api_client, canonical_instant, instants_equal  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .test_users import (  # noqa: F401
    ALL_ROLE_HEADER_KEYS,
    BROKER_DILIGENCE_USER_ID,
    BROKER_OPS_ALT_USER_ID,
    BROKER_OPS_USER_ID,
    BROKER_VERIFIER_USER_ID,
    ESCROW_FUNDER_USER_ID,
    ESCROW_RELEASER_USER_ID,
    PLATFORM_ADMIN_USER_ID,
    TEST_USERS,
    headers_with_unknown_role,
    headers_without_role,
    make_broker_headers,
    make_buyer_headers,
    make_escrow_agent_headers,
    make_platform_admin_headers,
    make_seller_headers,
)
