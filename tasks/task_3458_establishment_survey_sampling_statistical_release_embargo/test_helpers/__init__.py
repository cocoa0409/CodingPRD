"""Barrel export: framework generics + PRD-specific helpers.

Tests import everything from this one package. Note: `api_client` here is
the shared ApiClient singleton (bound after the submodule loads); use
`ApiClient` for the class.
"""
# Framework generics (re-exported for convenience)
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

# PRD-specific
from .types import *
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *
from .constants import *
from .factories import *
from .test_users import (
    ADMIN_USER_ID,
    ANALYST_2_USER_ID,
    ANALYST_USER_ID,
    COLLECTOR_USER_ID,
    DISCLOSURE_OFFICER_USER_ID,
    FALLBACK_MEDIA_USER_ID,
    FALLBACK_RESPONDENT_USER_ID,
    METHODOLOGIST_USER_ID,
    RELEASE_MANAGER_USER_ID,
    TEST_USERS,
    make_accredited_media_headers,
    make_disclosure_officer_headers,
    make_estimation_analyst_headers,
    make_respondent_headers,
)
from .fixtures import *
