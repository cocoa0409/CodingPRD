"""Test helpers for the Student Data Privacy Vendor Vetting API.

Importing this package registers the PRD §5 error_id -> HTTP status map with
the framework validators, so `validate_error(response, ERR_X)` cross-checks the
status code without each test restating it.
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

from . import api_errors, assertions, constants, factories, fixtures  # noqa: F401
from .api_client import (  # noqa: F401
    OMIT,
    ApiClient,
    canonical_instant,
    instants_equal,
    parse_instant,
    render_instant,
    shift_instant,
)
from .api_errors import ERROR_HTTP_STATUS, NOT_FOUND_ERROR_IDS  # noqa: F401
from .assertions import (  # noqa: F401
    assert_ascending_by_created_at,
    assert_bare_uuid,
    assert_common_fields,
    assert_covers_exactly,
    assert_decimal_equals,
    assert_instant_before,
    assert_instant_equals,
    assert_integer_equals,
    assert_pagination_meta,
    assert_risk_and_posture,
    assert_three_fraction_digits,
    assert_two_decimal_scale,
    assert_unchanged,
    ids_of,
)
from .test_users import (  # noqa: F401
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    ADMIN_USER_ID_ALT,
    TELEMETRY_HEADERS,
    TELEMETRY_USER_ID,
    TELEMETRY_USER_ID_ALT,
    TEST_USERS,
    make_admin_headers,
    make_analyst_headers,
    make_blank_identity_headers,
    make_missing_identity_headers,
    make_role_headers,
    make_teacher_headers,
    make_telemetry_headers,
    make_vendor_liaison_headers,
)
from .types import (  # noqa: F401
    AnalystContext,
    ApplicationContext,
    Headers,
    Json,
    ReviewChain,
    TeacherContext,
    VendorContext,
)
