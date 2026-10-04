"""Shared test infrastructure for the Medicare Enrollment API.

One import source for test modules: the framework's generic validators and
race utilities, plus this domain's client, error catalogue, entity
assertions, payload factories, constants, role headers and composite
fixtures.
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
from .api_client import ApiClient, api_client, canonical_instant, same_instant
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (
    APPEALS_OFFICER_2_HEADERS,
    APPEALS_OFFICER_HEADERS,
    APPEALS_OFFICER_USER_ID,
    BENEFIT_ADMINISTRATOR_HEADERS,
    BENEFIT_ADMINISTRATOR_USER_ID,
    FIELD_OFFICER_2_HEADERS,
    FIELD_OFFICER_HEADERS,
    FIELD_OFFICER_USER_ID,
    IRS_DATA_AGENT_HEADERS,
    IRS_DATA_AGENT_USER_ID,
    MISSING_USER_ID_HEADERS,
    MISSING_USER_ROLE_HEADERS,
    NO_AUTH_HEADERS,
    TEST_USERS,
    UNDECLARED_ROLE_HEADERS,
    make_appeals_officer_headers,
    make_beneficiary_headers,
    make_benefit_administrator_headers,
    make_field_officer_headers,
    make_irs_data_agent_headers,
)
from .fixtures import *  # noqa: F401,F403
