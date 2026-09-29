"""Test infrastructure for the Human Milk Bank Screening Pasteurization API.

Importing this package registers the error-identifier to HTTP-status mapping with
the framework validators, so `validate_error(response, ApiErrorId.X.value)` can
check the status without the caller repeating it.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assert_timestamp_format,
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
from .api_client import BASE, ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .test_users import (
    ADMIN_HEADERS,
    ADMIN_ID,
    INTAKE_HEADERS,
    INTAKE_ID,
    MEDICAL_DIRECTOR_HEADERS,
    MEDICAL_DIRECTOR_ID,
    NO_HEADERS,
    PHARMACIST_HEADERS,
    PHARMACIST_ID,
    PRESCRIBER_HEADERS,
    PRESCRIBER_ID,
    QA_OFFICER_HEADERS,
    QA_OFFICER_ID,
    QA_RELEASER_HEADERS,
    QA_RELEASER_ID,
    TECHNICIAN_HEADERS,
    TECHNICIAN_ID,
    TEST_USERS,
    UNKNOWN_ROLE_HEADERS,
    headers_for,
    headers_missing_role,
    headers_missing_user_id,
    make_donor_headers,
)

__all__ = [
    # framework re-exports
    "GenericApiClient",
    "NON_EXISTENT_UUID",
    "assert_at_least_one_succeeds",
    "assert_exactly_one_succeeds",
    "assert_race_outcome",
    "assert_timestamp_format",
    "build_user_headers",
    "get_success_data",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "run_race",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
    # modules
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    # client and errors
    "ApiClient",
    "api_client",
    "BASE",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    # identities
    "TEST_USERS",
    "ADMIN_HEADERS",
    "ADMIN_ID",
    "INTAKE_HEADERS",
    "INTAKE_ID",
    "MEDICAL_DIRECTOR_HEADERS",
    "MEDICAL_DIRECTOR_ID",
    "TECHNICIAN_HEADERS",
    "TECHNICIAN_ID",
    "QA_OFFICER_HEADERS",
    "QA_OFFICER_ID",
    "QA_RELEASER_HEADERS",
    "QA_RELEASER_ID",
    "PHARMACIST_HEADERS",
    "PHARMACIST_ID",
    "PRESCRIBER_HEADERS",
    "PRESCRIBER_ID",
    "NO_HEADERS",
    "UNKNOWN_ROLE_HEADERS",
    "headers_for",
    "headers_missing_role",
    "headers_missing_user_id",
    "make_donor_headers",
]
