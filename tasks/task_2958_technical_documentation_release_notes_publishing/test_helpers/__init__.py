"""Barrel export: framework generics + PRD-specific code."""
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient, canonical_instant, instants_equal
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import THRESHOLDS, TEST_DEFAULTS
from .test_users import (
    TEST_USERS,
    make_docs_lead_headers,
    make_writer_headers,
    make_reviewer_headers,
    make_localization_coordinator_headers,
    make_support_analyst_headers,
    make_reader_headers,
    make_headers,
    make_headers_missing_user_id,
    make_headers_missing_role,
    make_headers_empty_user_id,
    make_headers_empty_role,
    DOCS_LEAD_USER_ID,
    DOCS_LEAD_ALT_USER_ID,
    LOCALIZATION_COORDINATOR_USER_ID,
    SUPPORT_ANALYST_USER_ID,
    READER_USER_ID,
    UNRESOLVABLE_ENTITY_USER_ID,
)
from .fixtures import *  # noqa: F401,F403
