"""Barrel export: framework generics + PRD-specific helpers.

Tests import everything from this single module.
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
    AUDITOR_ID,
    CERT_AUTHORITY_ID,
    PLATFORM_ADMIN_ID,
    PUBLIC_REQUESTER_ID,
    TEST_USERS,
    VENDOR_REP_ID,
    make_auditor_headers,
    make_certification_authority_headers,
    make_election_official_headers,
    make_lab_agent_headers,
    make_platform_admin_headers,
    make_public_requester_headers,
    make_vendor_rep_headers,
)
from .fixtures import *
