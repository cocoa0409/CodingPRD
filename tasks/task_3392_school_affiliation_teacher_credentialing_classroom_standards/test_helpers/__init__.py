"""Barrel export: framework generics + PRD-specific helpers.

Tests import everything from here — one import source for the framework's
validators and race utilities plus this task's types, client, error ids,
assertions, factories, constants, role headers and fixtures.
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
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (
    ACCREDITATION_REVIEWER,
    ACCREDITATION_REVIEWER_2,
    ACCREDITATION_REVIEWER_2_USER_ID,
    ACCREDITATION_REVIEWER_USER_ID,
    ANONYMOUS,
    CONSULTANT,
    CONSULTANT_2,
    CONSULTANT_2_USER_ID,
    CONSULTANT_USER_ID,
    REGISTRAR,
    REGISTRAR_USER_ID,
    SOCIETY_ADMIN,
    SOCIETY_ADMIN_USER_ID,
    TEST_USERS,
    make_adult_learner_headers,
    make_consultant_headers,
    make_headers,
    make_program_director_headers,
    make_reviewer_headers,
    make_school_admin_headers,
)
from .fixtures import *  # noqa: F401,F403
