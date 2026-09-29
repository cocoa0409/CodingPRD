"""
Test infrastructure for the State Fish Hatchery Stocking Program API.

Re-exports the pieces test modules need: the endpoint client, the error
catalogue, the payload factories, the domain assertions, the business constants,
the role headers and the composite setup helpers, alongside the shared validators
from the runner's testing package.
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

from . import assertions, constants, factories, fixtures
from .api_client import ApiClient, canonical_instant
from .api_errors import ERROR_HTTP_STATUS
from .assertions import (
    assert_appropriation_ledger,
    assert_ascending_by,
    assert_common_fields,
    assert_decimal_places,
    assert_descending_by,
    assert_error_meta_is_minimal,
    assert_female_ledger,
    assert_fish_conservation,
    assert_instant_equals,
    assert_instant_format,
    assert_integer_equals,
    assert_is_none,
    assert_no_revision_fields,
    assert_number_equals,
    assert_request_id_prefix,
    assert_water_right_ledger,
    ids_of,
    validate_unpaginated,
)
from .test_users import (
    ADMIN_HEADERS,
    ADMIN_HEADERS_ALT,
    BIO_CARLA_HEADERS,
    BIO_DANA_HEADERS,
    BIO_FRANK_HEADERS,
    PUB_DANA_HEADERS,
    PUB_ERIN_HEADERS,
    PUB_EVE_HEADERS,
    TEST_USERS,
    VET_ANNA_HEADERS,
    VET_BRUNO_HEADERS,
    VET_CARA_HEADERS,
    headers_blank_user_id,
    headers_missing_user_id,
    make_hatchery_manager_headers,
)

__all__ = [
    # Modules
    "assertions",
    "constants",
    "factories",
    "fixtures",
    # Client
    "ApiClient",
    "canonical_instant",
    # Errors
    "ERROR_HTTP_STATUS",
    # Shared validators
    "validate_success",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "get_success_data",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "assert_cost_precision",
    "assert_version_incremented",
    "assert_timestamp_format",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "run_race",
    "build_user_headers",
    "NON_EXISTENT_UUID",
    # Domain assertions
    "validate_unpaginated",
    "assert_common_fields",
    "assert_no_revision_fields",
    "assert_error_meta_is_minimal",
    "assert_request_id_prefix",
    "assert_instant_equals",
    "assert_instant_format",
    "assert_number_equals",
    "assert_integer_equals",
    "assert_decimal_places",
    "assert_is_none",
    "assert_water_right_ledger",
    "assert_appropriation_ledger",
    "assert_female_ledger",
    "assert_fish_conservation",
    "assert_ascending_by",
    "assert_descending_by",
    "ids_of",
    # Users
    "TEST_USERS",
    "ADMIN_HEADERS",
    "ADMIN_HEADERS_ALT",
    "VET_ANNA_HEADERS",
    "VET_BRUNO_HEADERS",
    "VET_CARA_HEADERS",
    "BIO_CARLA_HEADERS",
    "BIO_DANA_HEADERS",
    "BIO_FRANK_HEADERS",
    "PUB_ERIN_HEADERS",
    "PUB_DANA_HEADERS",
    "PUB_EVE_HEADERS",
    "make_hatchery_manager_headers",
    "headers_missing_user_id",
    "headers_blank_user_id",
]
