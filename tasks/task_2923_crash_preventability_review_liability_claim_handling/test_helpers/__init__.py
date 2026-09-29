"""Shared test infrastructure for the crash review and liability claim service."""

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

from test_helpers import assertions, constants, factories, types  # noqa: F401
from test_helpers.api_client import ApiClient  # noqa: F401
from test_helpers.api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from test_helpers.test_users import (  # noqa: F401
    TEST_USERS,
    make_auditor_headers,
    make_blank_role_headers,
    make_blank_user_id_headers,
    make_claims_adjuster_headers,
    make_claims_manager_headers,
    make_committee_member_headers,
    make_dispatcher_headers,
    make_driver_headers,
    make_missing_role_headers,
    make_missing_user_id_headers,
    make_safety_admin_headers,
    make_safety_manager_headers,
    make_unknown_role_headers,
)
