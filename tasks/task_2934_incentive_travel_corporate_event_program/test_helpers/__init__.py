"""Shared test infrastructure for the Incentive Travel Program API suite.

Every test module imports from this package, never from the framework directly,
so the framework re-exports below are part of the public surface.
"""

from prd_bench_local_runner.testing import (  # noqa: F401
    GenericApiClient,
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

from .api_client import ApiClient, api_client, canonical_instant  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ROLE_HEADER_BUILDERS,
    TEST_USERS,
    headers_for_role,
    make_contract_approver_headers,
    make_participant_headers,
    make_program_director_headers,
    make_sales_ops_analyst_headers,
    make_sourcing_manager_headers,
    make_tax_officer_headers,
    make_travel_desk_headers,
)
from .types import *  # noqa: F401,F403
