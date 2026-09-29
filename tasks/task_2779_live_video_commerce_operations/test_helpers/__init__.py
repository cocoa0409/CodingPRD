"""Test helper package: one import surface for the whole suite."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
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

from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, PATH_ID_NOT_FOUND, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ADMIN_ID,
    ALL_ROLE_NAMES,
    CERT_OFFICER_ID,
    CLAIMS_OFFICER_ID,
    MERCHANDISER_ID,
    MODERATOR_ID,
    PRODUCER_ID,
    SIGNOFF_OFFICER_ID,
    TEST_USERS,
    make_compliance_officer_headers,
    make_host_headers,
    make_merchandising_manager_headers,
    make_moderator_headers,
    make_platform_admin_headers,
    make_show_producer_headers,
    make_viewer_headers,
)
