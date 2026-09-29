"""Test infrastructure for the multifamily physical inspection readiness API.

Everything a test needs is re-exported here, so a test module imports from
`test_helpers` alone: the framework's generic validators, the endpoint client,
the error catalogue, domain assertions, payload factories, constants, actors and
composite setup builders.
"""

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
from prd_bench_local_runner.testing.validators import set_error_http_status_map

from .api_client import ApiClient, api_client, canonicalize_instant
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ALL_ROLES,
    APPEALS_OFFICER_ID,
    HOUSING_AGENCY_INSPECTOR_ID,
    MAINTENANCE_TECHNICIAN_ID,
    PLATFORM_ADMIN_ID,
    QUALITY_ASSURANCE_REVIEWER_ALT_ID,
    QUALITY_ASSURANCE_REVIEWER_ID,
    ROLE_APPEALS_OFFICER,
    ROLE_HOUSING_AGENCY_INSPECTOR,
    ROLE_MAINTENANCE_TECHNICIAN,
    ROLE_PLATFORM_ADMIN,
    ROLE_PROPERTY_OWNER,
    ROLE_QUALITY_ASSURANCE_REVIEWER,
    TEST_USERS,
    UNOWNED_PROPERTY_OWNER_ID,
    make_appeals_officer_headers,
    make_headers,
    make_headers_without_user_id,
    make_housing_agency_inspector_headers,
    make_maintenance_technician_headers,
    make_platform_admin_headers,
    make_property_owner_headers,
    make_quality_assurance_reviewer_headers,
)
from .types import *  # noqa: F401,F403

# Teach the framework's error validator which HTTP status each catalogued
# error_id carries, so validate_error can check the pair in one step.
set_error_http_status_map(HTTP_STATUS_CODES)
