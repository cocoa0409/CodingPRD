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
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_activation_token,
    assert_authorization_event,
    assert_authorization_rule,
    assert_bin_range,
    assert_card,
    assert_card_account,
    assert_card_program,
    assert_conversion_job,
    assert_mandate,
    assert_mandate_ack,
    assert_production_batch,
    assert_production_vendor,
    assert_program_economics,
    assert_reissue_campaign,
    assert_settlement,
)
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    TEST_USERS,
    make_cardholder_ops_headers,
    make_compliance_officer_headers,
    make_finance_controller_headers,
    make_operations_analyst_headers,
    make_platform_admin_headers,
    make_program_manager_headers,
)
from .types import *  # noqa: F401,F403
