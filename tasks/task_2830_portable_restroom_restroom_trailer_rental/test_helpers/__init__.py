"""Test helper package for the Portable Restroom & Restroom Trailer Rental API.

Re-exports the generic framework validators alongside the domain-specific
client, factories, assertions and composite setup helpers so a test module can
pull everything it needs from one place.
"""

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

from .api_client import ApiClient, api_client, calendar_date_of, canonical_instant
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    TEST_USERS,
    headers_without_role,
    headers_without_user_id,
    make_compliance_officer_headers,
    make_customer_contact_headers,
    make_dispatch_planner_headers,
    make_driver_operator_headers,
    make_headers_for_role,
    make_permit_coordinator_headers,
    make_platform_admin_headers,
    make_sales_rep_headers,
)
from .types import *  # noqa: F401,F403
