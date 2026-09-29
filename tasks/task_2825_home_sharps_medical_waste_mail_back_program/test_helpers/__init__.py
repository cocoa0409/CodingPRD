"""Barrel export: framework generics plus this PRD's own test infrastructure."""

# Framework generics, re-exported so tests have a single import source.
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

from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import (  # noqa: F401
    HTTP_STATUS_CODES,
    NOT_FOUND_ERROR_BY_ENTITY,
    ApiErrorId,
)
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN_USER_ID,
    DESTRUCTION_OFFICER_USER_ID,
    HEADERS_BY_ROLE,
    INTAKE_TECHNICIAN_USER_ID,
    LOGISTICS_USER_ID,
    SECOND_DESTRUCTION_OFFICER_USER_ID,
    SECOND_INTAKE_TECHNICIAN_USER_ID,
    TEST_USERS,
    make_destruction_officer_headers,
    make_intake_technician_headers,
    make_logistics_coordinator_headers,
    make_patient_headers,
    make_program_admin_headers,
    make_sponsor_representative_headers,
)
from .types import *  # noqa: F401,F403
