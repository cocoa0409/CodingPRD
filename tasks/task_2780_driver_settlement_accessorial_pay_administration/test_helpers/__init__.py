"""
Test helper package for the driver settlement and accessorial pay API.

Importing this package registers the error_id -> HTTP status mapping with the
framework validators, so every validate_error() call cross-checks the status code
of the asserted error without the test restating it.
"""

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

from . import assertions, constants, factories, fixtures, types
from .api_client import ApiClient, api_client, canonical_ts
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_advance_principal_conserved,
    assert_all_money_fields_integer,
    assert_all_none,
    assert_append_only_record_shape,
    assert_created_at_ascending,
    assert_escrow_ledger_reconciles,
    assert_fields,
    assert_gross_decomposition,
    assert_money_integer,
    assert_mutable_record_shape,
    assert_net_decomposition,
    assert_sequences_ascending_from_one,
    assert_settlement_totals_consistent,
    assert_timestamps_equal,
    assert_version_is,
    assert_wage_identity,
    find_line,
    lines_of_type,
)
from .test_users import (
    ADMIN_ALT_HEADERS,
    ADMIN_HEADERS,
    APPROVER_ALT_HEADERS,
    APPROVER_HEADERS,
    AUDITOR_HEADERS,
    CLERK_ALT_HEADERS,
    CLERK_HEADERS,
    COMPLIANCE_AUDITOR_ID,
    PAYROLL_ADMIN_ALT_ID,
    PAYROLL_ADMIN_ID,
    SETTLEMENT_APPROVER_ALT_ID,
    SETTLEMENT_APPROVER_ID,
    SETTLEMENT_CLERK_ALT_ID,
    SETTLEMENT_CLERK_ID,
    TEST_USERS,
    headers_for,
    make_driver_headers,
)
from .types import UserRole

__all__ = [
    # Framework re-exports
    "validate_success",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "get_success_data",
    "build_user_headers",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "assert_cost_precision",
    "assert_version_incremented",
    "assert_timestamp_format",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "run_race",
    "NON_EXISTENT_UUID",
    # Modules
    "types",
    "constants",
    "factories",
    "fixtures",
    "assertions",
    # Client
    "ApiClient",
    "api_client",
    "canonical_ts",
    # Errors
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    # Identities
    "TEST_USERS",
    "UserRole",
    "ADMIN_HEADERS",
    "ADMIN_ALT_HEADERS",
    "CLERK_HEADERS",
    "CLERK_ALT_HEADERS",
    "APPROVER_HEADERS",
    "APPROVER_ALT_HEADERS",
    "AUDITOR_HEADERS",
    "PAYROLL_ADMIN_ID",
    "PAYROLL_ADMIN_ALT_ID",
    "SETTLEMENT_CLERK_ID",
    "SETTLEMENT_CLERK_ALT_ID",
    "SETTLEMENT_APPROVER_ID",
    "SETTLEMENT_APPROVER_ALT_ID",
    "COMPLIANCE_AUDITOR_ID",
    "make_driver_headers",
    "headers_for",
    # Domain assertions
    "assert_mutable_record_shape",
    "assert_append_only_record_shape",
    "assert_version_is",
    "assert_fields",
    "assert_all_none",
    "assert_money_integer",
    "assert_all_money_fields_integer",
    "assert_timestamps_equal",
    "assert_wage_identity",
    "assert_gross_decomposition",
    "assert_net_decomposition",
    "assert_settlement_totals_consistent",
    "assert_escrow_ledger_reconciles",
    "assert_advance_principal_conserved",
    "assert_sequences_ascending_from_one",
    "assert_created_at_ascending",
    "find_line",
    "lines_of_type",
]
