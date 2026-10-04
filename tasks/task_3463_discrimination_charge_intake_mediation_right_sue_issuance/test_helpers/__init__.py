"""Barrel export: framework generics + PRD-specific helpers.

Importing this package also registers the PRD section 5 error-id/HTTP-status
map with the framework validators (see api_errors.py).
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
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    TEST_USERS,
    make_charging_party_headers,
    make_commissioner_headers,
    make_director_headers,
    make_intake_officer_headers,
    make_investigator_headers,
    make_mediator_headers,
    make_platform_admin_headers,
    make_respondent_rep_headers,
    make_state_agency_officer_headers,
)
from .fixtures import *
