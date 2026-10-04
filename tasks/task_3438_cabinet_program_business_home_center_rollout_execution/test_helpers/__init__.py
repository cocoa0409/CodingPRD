"""Barrel export: framework generics plus PRD-specific helpers.

Tests import everything from ``test_helpers`` — one import source for the
validators, the API client, the entity assertions, the payload factories,
the domain constants, the role headers and the composite fixtures.
"""

# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    GenericApiClient,
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

# PRD-specific: constants, types, errors, client, factories, users, assertions, fixtures
from .constants import *
from .types import *
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .api_client import ApiClient, api_client, canonical_instant
from .factories import *
from .test_users import *
from .assertions import *
from .fixtures import *
