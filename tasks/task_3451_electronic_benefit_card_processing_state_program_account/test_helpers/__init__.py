"""Test helper package for the EBT state benefits API.

Re-exports the framework generics alongside the PRD-specific helpers so a test
module needs a single import line. Submodules stay importable as modules
(`test_helpers.fixtures`, `test_helpers.factories`, ...); the client singleton
is named `default_client` precisely so that `test_helpers.api_client` always
resolves to the module, never to an instance.
"""
from prd_bench_local_runner.testing import (  # noqa: F401
    NON_EXISTENT_UUID,
    GenericApiClient,
    assert_at_least_one_succeeds,
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

# Submodules as modules (attribute access: fixtures.setup_pos_ready, ...).
from . import api_client, api_errors, assertions, constants, factories, fixtures, test_users, types  # noqa: F401

# Headline names re-exported for convenience.
from .api_client import ApiClient, default_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import canonical_instant, instants_equal  # noqa: F401
from .constants import (  # noqa: F401
    ACQUIRER_FEE_BASIS_POINTS,
    CARD_MAIL_DELAY_HOURS,
    CASH_WITHDRAWAL_DAILY_LIMIT_CENTS,
    CASH_WITHDRAWAL_MULTIPLE_CENTS,
    CLAIM_WINDOW_DAYS,
    DEFAULT_AVAILABILITY_HOUR_UTC,
    DEFAULT_DISASTER_EXPIRY_DAYS,
    DEFAULT_EXPUNGEMENT_INACTIVITY_DAYS,
    DEFAULT_POSTING_MODULUS,
    DEFAULT_REPLACEMENT_FEE_CENTS,
    DISPUTE_WINDOW_DAYS,
    EXPUNGEMENT_NOTICE_LEAD_DAYS,
    FREE_REPLACEMENTS_PER_365D,
    LOGICAL_CLOCK_DEFAULT_UTC,
    PIN_MAX_FAILURES,
    PROVISIONAL_CREDIT_CAP_CENTS,
    PROVISIONAL_CREDIT_DELAY_DAYS,
    SETTLEMENT_CUTOFF_HOUR_UTC,
    SKIMMING_SUSPEND_THRESHOLD,
)
from .factories import DEFAULTS as FACTORY_DEFAULTS  # noqa: F401
from .test_users import (  # noqa: F401
    ALL_ROLE_HEADER_KEYS,
    CSR_USER_A,
    CSR_USER_B,
    STATE_ADMIN_USER_ID,
    TEST_USERS,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    make_cardholder_headers,
    make_cardholder_services_headers,
    make_retailer_system_headers,
    make_state_admin_headers,
)
