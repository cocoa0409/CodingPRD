"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    GenericApiClient,
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

# PRD-specific
from .types import *
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import CAPACITY, MAX_STORES_BY_GRADE, MIN_COVERAGE_RATE, RENEWAL_WINDOW_DAYS, DEFAULT_CLOCK_UTC, TERMS
from .test_users import (
    TEST_USERS,
    make_operator_headers,
    make_admin_headers,
    make_finance_headers,
    make_coop_headers,
)
from .fixtures import (
    set_clock,
    create_site,
    create_operator,
    create_and_submit_capacity_review,
    create_strong_approved_operator,
    get_operator_version,
    get_sublease_version,
    create_store_for,
    activate_agreement,
    activate_sublease,
    setup_open_store,
    deposit_escrow,
    post_rent_charge,
    create_locked_sales_month,
    declare_store_default,
    setup_defaulted_store,
    setup_repossessed_store,
    create_and_open_second_store,
)
