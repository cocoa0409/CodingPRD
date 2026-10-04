"""Barrel export: framework generics + PRD-specific helpers."""

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

from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_append_only_fields,
    assert_common_fields,
    assert_ledger_entry,
    assert_radio,
    assert_signal_command,
    assert_subscription,
    ledger_amount_of,
    ledger_entries_of,
)
from .constants import (
    BPS_DENOMINATOR,
    CELLULAR_RETRY_BASE_MINUTES,
    DEFAULT_CLOCK,
    FAMILY_DISCOUNT_BPS,
    MAX_SIGNAL_ATTEMPTS,
    NON_EXISTENT_ID,
    RENEWAL_DISCLOSURE_LEAD_DAYS,
    SATELLITE_RETRY_BASE_MINUTES,
    SAVE_OFFER_CAP_PER_TERM,
    SECONDS_PER_DAY,
)
from . import factories, fixtures, types
from .test_users import (
    ANONYMOUS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    RETENTION_AGENT_HEADERS,
    SYSTEM_OPERATOR_HEADERS,
    TEST_USERS,
    make_automaker_headers,
    make_customer_headers,
    make_dealer_headers,
)
