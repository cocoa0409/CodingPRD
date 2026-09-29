"""Test infrastructure for the Executive Protection & Travel Risk Management API."""

from prd_bench_local_runner.testing import (  # noqa: F401
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

from . import assertions, constants, factories, fixtures  # noqa: F401
from .api_client import ExecProtectionClient  # noqa: F401
from .api_errors import ERROR_HTTP_STATUS  # noqa: F401
from .assertions import (  # noqa: F401
    assert_append_only_fields,
    assert_budget_ledger,
    assert_cents,
    assert_common_fields,
    assert_decimal_value,
    assert_envelope_meta,
    assert_error_meta_shape,
    assert_field_absent,
    assert_identifier,
    assert_instant_format,
    assert_items_in_canonical_order,
    assert_list_ordering,
    assert_single_resource_meta,
    assert_staff_hours,
    assert_trip_states,
    assert_vendor_hours,
    round_half_up,
    round_half_up_cents,
)
from .test_users import (  # noqa: F401
    COMPLIANCE_OFFICER_HEADERS,
    COMPLIANCE_OFFICER_ID,
    SYSTEM_OPERATOR_HEADERS,
    SYSTEM_OPERATOR_ID,
    TEST_USERS,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_without_role,
    headers_without_user_id,
    make_compliance_officer_headers,
    make_executive_headers,
    make_headers,
    make_protection_manager_headers,
    make_security_analyst_headers,
    make_security_director_headers,
    make_system_operator_headers,
)
