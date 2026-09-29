"""
Barrel export for the Ethanol Plant Operations compliance suite.

Framework generics are re-exported alongside the API-specific client, error
catalogue, assertions, factories, constants, role headers and composite
fixtures so a test file has a single import source.
"""

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

from . import assertions, constants, factories, fixtures, test_users, types
from .api_client import EthanolOpsApiClient, canonical_instant, instants_equal
from .api_errors import HTTP_STATUS_CODES, NOT_FOUND_ORDER, ApiErrorId
from .test_users import TEST_USERS

api_client = EthanolOpsApiClient()
