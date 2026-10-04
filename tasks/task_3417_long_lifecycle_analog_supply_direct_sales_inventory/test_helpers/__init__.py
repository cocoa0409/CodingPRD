"""Barrel export: framework generics + PRD-specific helpers."""
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
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_allocation_run,
    assert_capacity_pool,
    assert_common_fields,
    assert_customer,
    assert_design_win,
    assert_eol_notice,
    assert_inventory_position,
    assert_lifetime_buy,
    assert_order_line,
    assert_part,
    assert_pricing_schedule,
    assert_reference_design,
    assert_sales_order,
    assert_site_qualification,
)
from .factories import (
    create_allocation_run_payload,
    create_capacity_pool_payload,
    create_customer_payload,
    create_design_win_payload,
    create_eol_notice_payload,
    create_lifetime_buy_payload,
    create_order_payload,
    create_part_payload,
    create_pricing_schedule_payload,
    create_reference_design_payload,
    create_site_qualification_payload,
)
from .constants import (
    DESIGN_WIN_ONE_YEAR_CLOCK,
    DESIGN_WIN_START_DATE,
    EOL_LAST_ORDER_DATE,
    EOL_LAST_SHIP_DATE,
    EOL_NOTICE_DATE,
    POOL_PERIOD_END,
    POOL_PERIOD_START,
    PRICING_EFFECTIVE_FROM,
)
from .test_users import NO_AUTH_HEADERS, TEST_USERS, make_customer_headers
from .fixtures import (
    get_customer,
    get_inventory_position,
    get_order_lines,
    get_part,
    get_pool,
    make_active_design_win,
    make_allocation_run,
    make_capacity_pool,
    make_customer,
    make_eol_notice,
    make_ltb_ready_part,
    make_order,
    make_part,
    make_stocked_priced_part,
    place_lifetime_buy,
    publish_price,
    qualify_site,
    record_receipt,
    set_clock,
    submit_order,
)
