"""Shared test infrastructure for the Municipal Credit Ratings API.

One import surface for tests: the framework's generic validators and race
utilities, plus this package's PRD-specific types, client, error catalogue,
assertions, factories, constants, role headers and composite fixtures.
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

# PRD-specific infrastructure
from .types import *
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    ADMIN_HEADERS,
    ANALYST_2_HEADERS,
    ANALYST_HEADERS,
    CHAIR_2_HEADERS,
    CHAIR_HEADERS,
    ISSUER_HEADERS,
    MISSING_USER_ID_HEADERS,
    MISSING_USER_ROLE_HEADERS,
    NO_HEADERS,
    OFFICER_HEADERS,
    TEST_USERS,
    UNDERWRITER_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    headers_for,
    make_committee_chair_headers,
    make_committee_member_headers,
    make_issuer_headers,
    make_lead_analyst_headers,
    make_platform_admin_headers,
    make_surveillance_officer_headers,
    make_underwriter_headers,
)
from .fixtures import *
