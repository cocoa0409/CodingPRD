"""Test infrastructure for the residential addiction treatment step-down network.

Barrel export: framework generics plus the domain-specific client, factories,
assertions, constants, role headers and composite setup helpers.
"""

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

from . import constants, factories  # noqa: F401
from .api_client import BASE, ApiClient, api_client  # noqa: F401
from .api_errors import (  # noqa: F401
    HTTP_STATUS_CODES,
    REFERENCE_NOT_FOUND,
    ApiErrorId,
)
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ALUMNI_COORDINATOR_HEADERS,
    CLINICAL_DIRECTOR_HEADERS,
    INTAKE_NURSE_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    READ_HEADERS,
    TEST_USERS,
    UTILIZATION_REVIEWER_HEADERS,
    make_alumni_coordinator_headers,
    make_clinical_director_headers,
    make_clinician_headers,
    make_headers,
    make_intake_nurse_headers,
    make_platform_admin_headers,
    make_read_headers,
    make_utilization_reviewer_headers,
)
from .types import *  # noqa: F401,F403
