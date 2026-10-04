"""Barrel export: framework generics plus this domain's helpers."""

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
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient  # noqa: F401
from .api_errors import (  # noqa: F401
    ApiErrorId,
    ERROR_HTTP_STATUS_BY_ID,
    HTTP_STATUS_CODES,
)
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN_HEADERS,
    ANONYMOUS_HEADERS,
    BANKER_HEADERS,
    CLOSING_HEADERS,
    COMPLIANCE_HEADERS,
    SALES_HEADERS,
    TEST_USERS,
    headers_with_unknown_role,
    headers_without_role,
    make_buyer_headers,
)
from .fixtures import *  # noqa: F401,F403