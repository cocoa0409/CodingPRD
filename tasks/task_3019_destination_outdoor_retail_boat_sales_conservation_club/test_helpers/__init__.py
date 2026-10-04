"""Barrel export: framework generics + PRD-specific code."""
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
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *
from .constants import *
from .factories import *
from .fixtures import *
from .test_users import TEST_USERS
from .test_users import (
    AGENCY_OPERATOR,
    ANONYMOUS,
    ATTRACTION_HOST,
    CLUB_CARD_SPECIALIST,
    CREDIT_OFFICER,
    CREDIT_UNDERWRITER,
    DEAL_DESK_CLERK,
    EVENTS_COORDINATOR,
    FINANCE_ADMIN,
    MEMBER_FALLBACK,
    PERMIT_CLERK,
    PLATFORM_ADMIN,
    RECEIVING_MANAGER,
    REMIT_ADMIN,
    SERVICE_TECHNICIAN,
    SERVICE_WRITER,
    STORE_MANAGER,
    TITLE_CLERK,
    make_member_headers,
)
from .types import *