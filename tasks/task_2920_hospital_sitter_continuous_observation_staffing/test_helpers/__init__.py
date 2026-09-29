"""
Test infrastructure for the Hospital Sitter & Continuous Observation Staffing API.

Importing this package registers the PRD section 5 error -> HTTP status catalogue
with the generic envelope validators, so ``validate_error`` cross-checks the HTTP
status of every rejection even when a test does not name it explicitly.
"""

from prd_bench_local_runner.testing import (  # noqa: F401  (re-exported for tests)
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

from . import assertions, constants, factories, fixtures, test_users, types  # noqa: F401
from .api_client import (  # noqa: F401
    ObservationApiClient,
    canonical_instant,
    instant,
    minutes_between,
)
from .api_errors import (  # noqa: F401
    ERROR_HTTP_STATUS,
    HTTP_BAD_REQUEST,
    HTTP_CONFLICT,
    HTTP_CREATED,
    HTTP_FORBIDDEN,
    HTTP_NOT_FOUND,
    HTTP_OK,
    HTTP_PAYMENT_REQUIRED,
    HTTP_PRECONDITION_FAILED,
    HTTP_UNAUTHORIZED,
    HTTP_UNPROCESSABLE,
)

__all__ = [
    "ObservationApiClient",
    "ERROR_HTTP_STATUS",
    "assertions",
    "canonical_instant",
    "constants",
    "factories",
    "fixtures",
    "instant",
    "minutes_between",
    "test_users",
    "types",
]
