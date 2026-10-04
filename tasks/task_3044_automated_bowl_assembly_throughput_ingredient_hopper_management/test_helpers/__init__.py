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
    assert_assembly_line,
    assert_calibration_adjustment,
    assert_hopper,
    assert_hopper_mass_balance,
    assert_ingredient,
    assert_labor_assignment,
    assert_order,
    assert_portion_verification,
    assert_prep_batch,
    assert_prep_batch_quantity_invariant,
    assert_recipe,
    assert_refill_task,
    assert_restaurant,
    assert_sanitation_cycle,
    assert_substitution_rule,
)
from .factories import *  # noqa: F401,F403
from .constants import TEST_DEFAULTS, THRESHOLDS
from .test_users import (
    CUSTOMER_HEADERS,
    LINE_OPERATOR_HEADERS,
    OPS_ADMIN_HEADERS,
    PREP_COOK_HEADERS,
    QUALITY_LEAD_HEADERS,
    SHIFT_MANAGER_HEADERS,
    TEST_USERS,
    make_customer_headers,
    make_line_operator_headers,
    make_ops_admin_headers,
    make_prep_cook_headers,
    make_quality_lead_headers,
    make_shift_manager_headers,
)
from .fixtures import *  # noqa: F401,F403
