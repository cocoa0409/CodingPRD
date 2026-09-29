"""Barrel export: framework generics + PRD-specific test infrastructure."""

# Framework generics (re-exported so tests have one import source)
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

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client, canonical_instant  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import (  # noqa: F401
    AGE_BAND_ORDER,
    DEFAULT_CLOCK_INSTANT,
    TEST_DEFAULTS,
    THRESHOLDS,
    TRAINING_VALIDITY_DAYS_BY_ROLE,
)
from .test_users import (  # noqa: F401
    ALL_ROLE_NAMES,
    OFFICERS,
    REVIEWERS,
    TEST_USERS,
    make_coach_headers,
    make_competition_director_headers,
    make_credentialing_officer_headers,
    make_health_screening_lead_headers,
    make_medical_reviewer_headers,
    make_program_manager_headers,
)
from .fixtures import *  # noqa: F401,F403
