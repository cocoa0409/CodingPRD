"""Shared test infrastructure for the Field Force Sample Accountability API.

Barrel export: the generic framework utilities plus the PRD-specific
client, errors, factories, constants, role headers, assertions, and fixture
builders.  Tests import everything from here.
"""

# Framework generics (re-exported for convenience)
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

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN_HEADERS,
    COMPLIANCE_HEADERS,
    DISTRICT_MANAGER_HEADERS,
    FIELD_REP_HEADERS,
    QA_HEADERS,
    TEST_USERS,
    make_admin_headers,
    make_compliance_headers,
    make_district_manager_headers,
    make_field_rep_headers,
    make_qa_headers,
)
from . import fixtures  # noqa: F401
from .fixtures import *  # noqa: F401,F403
