"""Test helpers for the Government Surplus Property Disposal API.

Barrel export: framework generics plus the PRD-specific client, types,
factories, assertions, constants, role headers and composite fixtures.
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

from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN_USER_ID,
    ASSESSOR_USER_ID,
    FINANCE_USER_ID,
    OFFICER_USER_ID,
    SECOND_ASSESSOR_USER_ID,
    SECOND_FINANCE_USER_ID,
    SECOND_OFFICER_USER_ID,
    SECOND_TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID,
    TEST_USERS,
    make_agency_officer_headers,
    make_bidder_headers,
    make_clearance_technician_headers,
    make_disposal_officer_headers,
    make_finance_controller_headers,
    make_program_admin_headers,
    make_surplus_assessor_headers,
)
from .types import *  # noqa: F401,F403
