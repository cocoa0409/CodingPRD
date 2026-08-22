"""Barrel export: framework generics plus the School Health Office domain helpers."""

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
    PHYSICIAN_USER_ID,
    PHYSICIAN_USER_ID_ALT,
    RECORDS_OFFICER_USER_ID,
    RECORDS_OFFICER_USER_ID_ALT,
    TEST_USERS,
    make_admin_headers,
    make_aide_headers,
    make_guardian_headers,
    make_nurse_headers,
    make_physician_headers,
    make_records_officer_headers,
)
from .types import *  # noqa: F401,F403
