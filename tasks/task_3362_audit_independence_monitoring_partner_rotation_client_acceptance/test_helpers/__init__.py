"""Barrel export: framework generics plus this project's helpers.

Tests import everything from here, so a name only has to be right in one place.
"""

# Framework generics, re-exported for convenience.
from prd_bench_local_runner.testing import (  # noqa: F401
    validate_success,
    validate_error,
    validate_paginated,
    validate_error_is_one_of,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    run_race,
    build_user_headers,
    NON_EXISTENT_UUID,
)

from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient, canonical_instant, instant_matches  # noqa: F401
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    TEST_USERS,
    PLATFORM_ADMIN_HEADERS,
    COMMITTEE_HEADERS,
    OFFICER_HEADERS,
    LIAISON_HEADERS,
    ENGAGEMENT_PARTNER_HEADERS,
    QUALITY_REVIEWER_HEADERS,
    make_engagement_partner_headers,
    make_quality_reviewer_headers,
    headers_without_auth,
    headers_without_user_id,
    headers_without_role,
)
from . import fixtures  # noqa: F401
from .fixtures import *  # noqa: F401,F403
