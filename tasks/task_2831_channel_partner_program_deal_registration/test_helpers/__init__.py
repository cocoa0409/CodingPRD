"""Barrel export: framework generics plus the channel partner program's own helpers."""

# Framework generics, re-exported so test modules have one import source.
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
    ANALYST,
    ANALYST_2,
    DIRECT_REP,
    DIRECT_REP_2,
    DIRECTOR,
    DIRECTOR_2,
    DIRECTOR_2_USER_ID,
    DIRECTOR_USER_ID,
    DIRECT_SALES_REP_2_USER_ID,
    DIRECT_SALES_REP_USER_ID,
    OPS_ANALYST_2_USER_ID,
    OPS_ANALYST_USER_ID,
    TEST_USERS,
    make_channel_director_headers,
    make_channel_ops_analyst_headers,
    make_direct_sales_rep_headers,
    make_partner_headers,
)
from .types import *  # noqa: F401,F403
