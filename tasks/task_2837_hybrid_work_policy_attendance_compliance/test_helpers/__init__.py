"""Barrel export: framework generics plus this API's own test infrastructure."""
from prd_bench_local_runner.testing import (  # noqa: F401
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

from .api_client import ApiClient, api_client, canonical_instant, same_instant  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ACCOMMODATION_USER_ID,
    AUDITOR_USER_ID,
    EMPTY_IDENTITY_HEADERS,
    HRBP_USER_ID,
    MANAGER_USER_ID,
    NO_IDENTITY_HEADERS,
    SECOND_HRBP_USER_ID,
    SECOND_MANAGER_USER_ID,
    SYSTEM_USER_ID,
    TEST_USERS,
    WPO_USER_ID,
    headers_for_role,
    make_accommodation_specialist_headers,
    make_compliance_auditor_headers,
    make_employee_headers,
    make_hr_business_partner_headers,
    make_people_manager_headers,
    make_system_integration_headers,
    make_workplace_program_office_headers,
)
from .types import *  # noqa: F401,F403
