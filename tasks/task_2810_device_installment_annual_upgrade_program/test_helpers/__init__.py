"""Test infrastructure for the Device Installment & Annual Upgrade Program API.

One barrel import gives a test module everything it needs:

    from test_helpers import (
        api_client, ApiErrorId, validate_success, validate_error,
        setup_active_loan, make_customer_headers, ...
    )

Framework generics come from ``prd_bench_local_runner.testing``; everything else is
specific to this PRD. Importing this package installs the error-id -> HTTP status
map, so ``validate_error`` can assert the declared status without repeating it.
"""

# --- framework generics -------------------------------------------------
from prd_bench_local_runner.testing import (
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

# --- PRD-specific modules ----------------------------------------------
from . import api_client as api_client_module
from . import assertions, constants, factories, fixtures, test_users, types
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import *  # noqa: F401,F403
from .types import *  # noqa: F401,F403
