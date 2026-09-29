"""Shared test infrastructure for the Brokered Deposit Funding Compliance API.

Importing this package gives a test module everything it needs: the generic
framework validators, the typed API client, the error-id catalogue with its HTTP
status map installed, payload factories, role headers, domain assertions and the
composite setup helpers.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
    assert_at_least_one_succeeds,
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

from . import assertions, factories, fixtures, types
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .constants import DEFAULT_CLOCK_DATE, DEFAULT_CLOCK_INSTANT, TEST_DEFAULTS, THRESHOLDS
from .test_users import (
    ADMIN,
    COMPLIANCE,
    DESK,
    EXAMINER,
    TEST_USERS,
    TREASURY,
    USER_IDS,
    make_broker_representative_headers,
    make_compliance_headers,
    make_examiner_headers,
    make_funding_desk_headers,
    make_system_admin_headers,
    make_treasury_headers,
)
from .types import UserRole

__all__ = [
    "ADMIN",
    "COMPLIANCE",
    "DESK",
    "DEFAULT_CLOCK_DATE",
    "DEFAULT_CLOCK_INSTANT",
    "EXAMINER",
    "HTTP_STATUS_CODES",
    "NON_EXISTENT_UUID",
    "TEST_DEFAULTS",
    "TEST_USERS",
    "THRESHOLDS",
    "TREASURY",
    "USER_IDS",
    "ApiClient",
    "ApiErrorId",
    "GenericApiClient",
    "UserRole",
    "api_client",
    "assert_at_least_one_succeeds",
    "assert_exactly_one_succeeds",
    "assert_race_outcome",
    "assert_timestamp_format",
    "assert_version_incremented",
    "assertions",
    "build_user_headers",
    "factories",
    "fixtures",
    "get_success_data",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "make_broker_representative_headers",
    "make_compliance_headers",
    "make_examiner_headers",
    "make_funding_desk_headers",
    "make_system_admin_headers",
    "make_treasury_headers",
    "run_race",
    "types",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
]
