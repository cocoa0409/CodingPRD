"""Barrel export: framework generics plus this API's domain helpers."""

# Framework generics (re-exported for convenience)
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

# Domain-specific
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    HR_DECIDER_HEADERS,
    HR_DECIDER_ID,
    HR_RECOMMENDER_HEADERS,
    HR_RECOMMENDER_ID,
    TEST_USERS,
    make_appeal_panelist_headers,
    make_evaluator_headers,
    make_hr_admin_headers,
    make_teacher_headers,
    make_union_rep_headers,
)
from .types import *  # noqa: F401,F403
