"""Test infrastructure for the Member Eligibility Military Lineage API.

Re-exports the shared framework generics alongside the helpers written for
this specification, so a test module can import everything from one place.
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

from test_helpers import (  # noqa: F401
    assertions,
    constants,
    factories,
    fixtures,
    types,
)
from test_helpers.api_client import ApiClient, api_client  # noqa: F401
from test_helpers.api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from test_helpers.test_users import (  # noqa: F401
    OFFICER_A_ID,
    OFFICER_B_ID,
    OFFICER_C_ID,
    TEST_USERS,
    make_member_headers,
    make_officer_headers,
)
