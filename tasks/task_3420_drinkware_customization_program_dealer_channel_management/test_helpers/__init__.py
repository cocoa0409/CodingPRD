"""Barrel export: framework generics + PRD-specific helpers.

Tests import everything they need from this single package.
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
from .types import *                  # entity TypedDicts, status enums, UserRole
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *             # assert_<entity>() + ledger invariants
from .factories import *              # create_<entity>_payload() factories
from .constants import *              # domain thresholds and constants
from .test_users import (
    TEST_USERS,
    make_buyer_headers,
    make_channel_manager_headers,
    make_customer_care_headers,
    make_dealer_headers,
    make_field_inspector_headers,
    make_platform_admin_headers,
    make_prepress_tech_headers,
    make_production_lead_headers,
    make_warranty_agent_headers,
)
from .fixtures import *               # composite setup helpers
