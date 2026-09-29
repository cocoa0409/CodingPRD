"""Barrel export: framework generics plus the Deal Desk specific helpers."""
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
    USER_IDS,
    headers_missing_role,
    headers_missing_user_id,
    headers_with_empty_role,
    headers_with_empty_user_id,
    make_cfo_headers,
    make_deal_desk_analyst_headers,
    make_headers,
    make_legal_counsel_headers,
    make_platform_admin_headers,
    make_revenue_accountant_headers,
    make_sales_director_headers,
    make_sales_rep_headers,
    make_vp_sales_headers,
)
from .types import *  # noqa: F401,F403
