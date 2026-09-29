"""Shared test infrastructure for the aging-life-care-management API.

Import surface for the suite: the framework generics are re-exported here beside
the domain-specific client, factories, assertions and composite setup helpers so
a test file needs one import line.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
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

from . import assertions, constants, factories, fixtures, types
from .api_client import ApiClient, api_client
from .api_errors import (
    HTTP_STATUS_CODES,
    NOT_FOUND_ERROR_IDS,
    ApiErrorId,
)
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ALL_ROLE_NAMES,
    BILLING_ADMINISTRATOR,
    PRACTICE_ADMIN,
    TEST_USERS,
    make_billing_administrator_headers,
    make_care_manager_headers,
    make_family_decision_maker_headers,
    make_headers,
    make_practice_admin_headers,
    make_practice_supervisor_headers,
)
from .types import *  # noqa: F401,F403
