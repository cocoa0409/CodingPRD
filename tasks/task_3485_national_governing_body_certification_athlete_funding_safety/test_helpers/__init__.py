"""Barrel export: framework generics + PRD-specific test infrastructure."""
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
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client, set_clock
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ARBITRATOR_ALT_ID,
    ARBITRATOR_ID,
    AUDITOR_CLOSER_ID,
    AUDITOR_ISSUER_ID,
    AUDITOR_THIRD_ID,
    COMMITTEE_ADMIN_ALT_ID,
    COMMITTEE_ADMIN_ID,
    INTERIM_MANAGER_ID,
    PLACEHOLDER_ATHLETE_ID,
    PLACEHOLDER_BODY_ID,
    RESULTS_OFFICIAL_ALT_ID,
    RESULTS_OFFICIAL_ID,
    SAFE_SPORT_OFFICER_ALT_ID,
    SAFE_SPORT_OFFICER_ID,
    TEST_USERS,
    make_arbitrator_headers,
    make_athlete_headers,
    make_auditor_headers,
    make_committee_admin_headers,
    make_ngb_admin_headers,
    make_results_official_headers,
    make_safe_sport_officer_headers,
)
from .fixtures import *  # noqa: F401,F403
from .fixtures import current_clock, reset_clock_tracker, set_logical_clock  # noqa: F401
