"""Barrel export: framework generics plus the sponsorship-domain helpers."""

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
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ACTIVATION_USER_ID,
    APPROVER_USER_ID,
    AUDITOR_USER_ID,
    DUAL_ROLE_USER_ID,
    PROPERTY_ADMIN_USER_ID,
    SECOND_ACTIVATION_USER_ID,
    SECOND_APPROVER_USER_ID,
    SELLER_USER_ID,
    TEST_USERS,
    make_activation_headers,
    make_approver_headers,
    make_auditor_headers,
    make_property_admin_headers,
    make_seller_headers,
    make_sponsor_contact_headers,
)
from .types import *  # noqa: F401,F403
