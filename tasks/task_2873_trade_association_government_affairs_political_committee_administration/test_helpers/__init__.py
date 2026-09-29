"""Barrel export: framework generics plus this API's test infrastructure."""
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

from .api_client import ApiClient, api_client, canonicalize_instant, instants_equal  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN_USER_ID,
    COMPLIANCE_USER_ID,
    COMPLIANCE_USER_ID_2,
    DIRECTOR_USER_ID,
    DUAL_HAT_USER_ID,
    NO_HEADERS,
    TEST_USERS,
    TRUSTEE_USER_ID,
    TRUSTEE_USER_ID_2,
    UNKNOWN_ROLE,
    UNKNOWN_ROLE_USER_ID,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    make_admin_headers,
    make_compliance_headers,
    make_director_headers,
    make_member_delegate_headers,
    make_trustee_headers,
)
from .types import *  # noqa: F401,F403
