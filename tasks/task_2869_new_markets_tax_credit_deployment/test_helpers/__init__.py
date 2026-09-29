"""Barrel export: framework generics plus the NMTC-specific test infrastructure."""

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
from .api_errors import (  # noqa: F401
    HTTP_STATUS_CODES,
    NOT_FOUND_CODES,
    ApiErrorId,
)
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    AGENCY_USER_ID,
    ALL_ROLES,
    INVESTOR_DELTA_USER_ID,
    INVESTOR_ECHO_USER_ID,
    REVIEWER_ANNUAL_USER_ID,
    REVIEWER_CBA_USER_ID,
    REVIEWER_ELIGIBILITY_USER_ID,
    ROLE_CDE_SPONSOR,
    ROLE_CERTIFYING_AGENCY,
    ROLE_COMPLIANCE_REVIEWER,
    ROLE_QALICB_SPONSOR,
    ROLE_TAX_CREDIT_INVESTOR,
    SPONSOR_BAYOU_USER_ID,
    SPONSOR_DELTA_USER_ID,
    SPONSOR_ECHO_USER_ID,
    TEST_USERS,
    UNOWNED_CDE_SPONSOR_USER_ID,
    make_agency_headers,
    make_cde_sponsor_headers,
    make_headers,
    make_investor_headers,
    make_qalicb_sponsor_headers,
    make_reviewer_headers,
)
from .types import *  # noqa: F401,F403
