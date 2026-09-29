"""
Test infrastructure for the eye bank corneal tissue recovery and distribution API.

Importing this package registers the error-id to HTTP-status map with the shared
validators, so ``validate_error`` can cross-check statuses even when a test omits
``expected_status``.

Tests import everything they need from here::

    from test_helpers import (
        EyeBankApiClient, COORDINATOR_HEADERS, validate_success, validate_error,
        ERR_TISSUE_NOT_ELIGIBLE, fixtures, factories,
    )
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

from . import factories, fixtures  # noqa: F401
from .api_client import BASE, EyeBankApiClient  # noqa: F401
from .api_errors import *  # noqa: F401,F403
from .api_errors import ERROR_HTTP_STATUS  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .test_users import *  # noqa: F401,F403
from .types import *  # noqa: F401,F403
