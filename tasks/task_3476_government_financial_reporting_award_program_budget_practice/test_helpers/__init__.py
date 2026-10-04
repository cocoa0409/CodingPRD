"""Barrel export: framework generics plus the PRD-specific helpers.

Tests import everything from here — the framework's validators, race
utilities, and header builder, plus this package's client, error catalog,
entity assertions, payload factories, constants, role headers, and composite
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
from .types import *
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    ALL_ROLES,
    AWARDS_DIRECTOR,
    AWARDS_DIRECTOR_USER_ID,
    EMPTY_USER_ID,
    EMPTY_USER_ROLE,
    MISSING_USER_ID,
    MISSING_USER_ROLE,
    PLATFORM_ADMIN,
    PLATFORM_ADMIN_USER_ID,
    ROLE_AWARDS_DIRECTOR,
    ROLE_COMMITTEE_MEMBER,
    ROLE_GOVERNMENT_CONTACT,
    ROLE_MEMBER,
    ROLE_PLATFORM_ADMIN,
    ROLE_REVIEWER,
    TEST_USERS,
    UNKNOWN_ROLE,
    headers_for,
    make_committee_member_headers,
    make_government_contact_headers,
    make_member_headers,
    make_reviewer_headers,
)
from .fixtures import *
