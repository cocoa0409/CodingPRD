"""Barrel export: framework generics + PRD-specific test infrastructure.

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

# PRD-specific infrastructure
from .types import *
from .api_client import API_PREFIX, ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    TEST_USERS,
    make_charging_coordinator_headers,
    make_claims_adjuster_headers,
    make_compliance_officer_headers,
    make_fleet_manager_headers,
    make_platform_admin_headers,
    make_production_planner_headers,
    make_quality_inspector_headers,
    make_release_manager_headers,
    make_service_dispatcher_headers,
    make_service_technician_headers,
    make_telematics_ingestion_headers,
)
from .fixtures import *
