"""Test infrastructure for the Limited-Assortment Grocery API.

Re-exports the pieces test modules reach for most often: framework generics,
the endpoint client, the error catalog, domain assertions, payload factories,
role headers, and composite fixtures.
"""

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
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_allocation,
    assert_bid,
    assert_cart_coin_event,
    assert_category,
    assert_claim,
    assert_employee,
    assert_finds_buy,
    assert_labor_window,
    assert_panel,
    assert_product,
    assert_register_shift,
    assert_store,
    assert_store_coin_invariants,
    assert_store_refund_invariants,
    assert_supplier,
    assert_tender,
    assert_two_dp,
)
from .constants import (
    CLAIM_WINDOW_DAYS,
    CLOCK_DEFAULT,
    COIN_VALUE_CENTS,
    DISQUALIFIED_SCORE_MARKER,
    GUARANTEE_MULTIPLIER,
    MAX_WINDOWS_PER_ISO_WEEK,
    MIN_SOURCES_DEFAULT,
    PANEL_MIN_SCORE,
    ROLE_RATE_CENTS_PER_HOUR,
    SCAN_TARGET,
    SKU_CAP_DEFAULT,
    SKU_CAP_MAX,
    SKU_CAP_MIN,
    STANDARD_MULTIPLIER,
    SUPPLIER_INITIAL_QUALITY_SCORE,
    TIER_SHARE_HIGH_VOLUME,
    TIER_SHARE_STANDARD,
    VOID_PENALTY,
    W_PANEL,
    W_PRICE,
    W_QUALITY,
)
from .test_users import (
    CATEGORY_MANAGER_HEADERS,
    CUSTOMER_SERVICE_HEADERS,
    OPERATIONS_ADMIN_HEADERS,
    PROCUREMENT_LEAD_HEADERS,
    QA_LEAD_HEADERS,
    TEST_USERS,
    headers_without_role,
    headers_without_user_id,
    make_cashier_headers,
    make_store_manager_headers,
    make_supplier_rep_headers,
)
from . import factories, fixtures, types
