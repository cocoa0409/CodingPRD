"""Test infrastructure for the Youth Sports Accident Insurance Claims API."""

# Framework generics, re-exported for convenience
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

from .api_client import ApiClient, api_client, canonical_iso, iso_instant
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ALL_ROLE_NAMES,
    CLAIMS_EXAMINER_USER_ID,
    MEDICAL_REVIEWER_USER_ID,
    PROGRAM_ADMIN_USER_ID,
    SANCTIONING_OFFICIAL_USER_ID,
    SECOND_CLAIMS_EXAMINER_USER_ID,
    TEST_USERS,
    THIRD_OFFICIAL_USER_ID,
    VERIFYING_OFFICIAL_USER_ID,
    make_claims_examiner_headers,
    make_guardian_headers,
    make_league_admin_headers,
    make_league_official_headers,
    make_medical_reviewer_headers,
    make_program_admin_headers,
)
from .types import *  # noqa: F401,F403
