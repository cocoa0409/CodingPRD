"""Barrel export: framework generics + PRD-specific helpers.

Any helper whose name begins with ``setup_`` is re-exported, so scenarios can be
declared at module level with the plain ``setup_x(api)`` call form.
"""

# Framework generics
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
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    CURATOR_USER_ID,
    DC_MANAGER_USER_ID,
    PICKER_USER_ID,
    PLATFORM_ADMIN_USER_ID,
    TEST_USERS,
    make_account_headers,
    make_customer_account_headers,
)
from .fixtures import *  # noqa: F401,F403

# Composites named by tests. ``from .fixtures import *`` skips these because they
# start with a capital letter, so they are re-exported explicitly.
from .fixtures import (  # noqa: F401
    ADMIN,
    CURATOR,
    DCM,
    DC_MANAGER,
    PICKER,
    SetupFailed,
    account_headers,
    add_stock_row,
    allocate_order,
    confirm_cutoff,
    create_and_approve_return,
    create_released_order,
    get_shipment_for_order,
    list_lines,
    open_pick,
    pick_and_complete,
    receive_return,
    setup_account,
    setup_allocated_order,
    setup_allocated_order_with_two_stock_rows,
    setup_availability_report,
    setup_center,
    setup_center_and_account,
    setup_clock,
    setup_curated_items,
    setup_draft_order,
    setup_five_line_fee_order,
    setup_items_only,
    setup_order_scenario,
    setup_picked_order,
    setup_pick_shortage_with_claim,
    setup_possitive_availability_centers,
    setup_released_order,
    setup_shipped_order,
    setup_square_footage_quote,
    setup_supplier,
    setup_tier_boundary_order_count,
)