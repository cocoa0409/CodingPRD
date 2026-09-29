"""Test helper package for the Retail FX & Travel Money API.

Importing this package is enough for a test module: it re-exports the framework
generics alongside every domain-specific client, factory, assertion and fixture.
"""

from prd_bench_local_runner.testing import (  # noqa: F401
    NON_EXISTENT_UUID,
    GenericApiClient,
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

from . import assertions, factories, fixtures  # noqa: F401
from .api_client import (  # noqa: F401
    ApiClient,
    api_client,
    canonical_ts,
    iso_z,
    parse_ts,
    same_instant,
    shift,
)
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import (  # noqa: F401
    assert_branch,
    assert_branch_posture_band,
    assert_buyback_contract,
    assert_cash_shipment,
    assert_common_fields,
    assert_compliance_report,
    assert_computed_targets_shape,
    assert_currency_profile,
    assert_customer,
    assert_denomination_entries,
    assert_exchange_transaction,
    assert_inventory_plan,
    assert_inventory_position,
    assert_mix_counts,
    assert_note_assessment,
    assert_position_mix_invariants,
    assert_quote_money,
    assert_rate_board,
    assert_rate_card,
    assert_rate_card_derivation,
    assert_reference_entity,
    assert_risk_tier_band,
    assert_settlement_money,
    assert_timestamp_equals,
    assert_travel_corridor,
    assert_vault_state,
    assert_versioned_entity,
    assert_wholesale_rate,
    find_mix_entry,
    per_line_usd_cents,
    round_half_up,
    usd_cents_from_minor,
)
from .constants import (  # noqa: F401
    ASSESSMENT_OUTCOMES,
    BPS_ONE,
    CLOCK_START,
    COMPLIANCE_DECISIONS,
    CURRENCY_CLASSES,
    DIRECTIONS,
    MICROS,
    OPERATORS,
    PAGINATION,
    ROLES,
    TEST_DEFAULTS,
)
from .test_users import (  # noqa: F401
    TEST_USERS,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    make_admin_headers,
    make_compliance_headers,
    make_customer_headers,
    make_manager_headers,
    make_teller_headers,
    make_treasury_headers,
)
