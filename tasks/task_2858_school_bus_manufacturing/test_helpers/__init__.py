"""Barrel export: framework generics plus this API's own test infrastructure."""

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
    TEST_USERS,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    make_compliance_officer_headers,
    make_contracts_admin_headers,
    make_dealer_agent_headers,
    make_plant_scheduler_headers,
    make_quality_inspector_headers,
    make_sales_engineer_headers,
)
from .types import *  # noqa: F401,F403
