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

from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    AUDITOR_OPENER_ID,
    AUDITOR_VERIFIER_ID,
    NO_HEADERS,
    OPS_ALTERNATE_ID,
    OPS_CREATOR_ID,
    OPS_ISSUER_ID,
    TEST_USERS,
    make_franchise_chef_headers,
    make_franchisor_ops_headers,
    make_headers_with_blank_role,
    make_headers_without_identity,
    make_host_store_manager_headers,
    make_quality_auditor_headers,
    make_role_headers,
)
from .types import *  # noqa: F401,F403
