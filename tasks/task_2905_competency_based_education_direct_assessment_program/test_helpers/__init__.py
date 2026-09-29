"""Test infrastructure for the competency-based education / direct assessment API.

Framework generics are re-exported so test modules have a single import source.
"""
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
    NO_HEADERS,
    SECOND_INTEGRITY_OFFICER,
    TEST_USERS,
    blank_identity_headers,
    blank_role_headers,
    make_evaluator_headers,
    make_financial_aid_officer_headers,
    make_integrity_officer_headers,
    make_mentor_headers,
    make_platform_admin_headers,
    make_registrar_headers,
    make_student_headers,
    missing_identity_headers,
    missing_role_headers,
)
from .types import *  # noqa: F401,F403
