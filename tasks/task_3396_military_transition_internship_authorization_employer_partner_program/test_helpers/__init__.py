"""Barrel export: framework generics + PRD-specific helpers."""

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

from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *
from .constants import *
from .factories import *
from .fixtures import *
from .test_users import TEST_USERS
from .test_users import (
    INSTALLATION_AUTHORITY_HEADERS,
    PROGRAM_OFFICE_HEADERS,
    TRANSITION_COUNSELOR_HEADERS,
    UNIT_COMMANDER_HEADERS,
    make_employer_rep_headers,
    make_installation_authority_headers,
    make_program_office_headers,
    make_service_member_headers,
    make_transition_counselor_headers,
    make_unit_commander_headers,
)
from .types import *
from .worlds import *
