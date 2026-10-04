"""Barrel export: framework generics plus PRD-specific infrastructure."""

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

from .constants import *  # noqa: F401,F403
from .types import *  # noqa: F401,F403
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .api_client import ApiClient, api_client
from .test_users import (
    ADMIN,
    COMPLIANCE,
    TEST_USERS,
    make_admin_headers,
    make_compliance_headers,
    make_patient_headers,
    make_physician_headers,
    make_qa_auditor_headers,
)
from . import factories  # noqa: F401
from .factories import *  # noqa: F401,F403
from .assertions import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .fixtures import api, client  # noqa: F401
