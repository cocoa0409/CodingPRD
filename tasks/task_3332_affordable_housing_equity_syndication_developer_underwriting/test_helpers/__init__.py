"""Barrel export: framework generics + PRD-specific test infrastructure.

This package is the single import surface for the Affordable Housing Equity
Syndication & Developer Underwriting API test suite. Everything a test module
needs — the HTTP client, entity types, error catalog, domain constants, role
headers, entity assertions, payload factories and composite setup helpers —
is re-exported here.

    from test_helpers import (
        api_client, ApiErrorId, TEST_USERS, make_investor_headers,
        create_fund_payload, setup_committed_project,
        assert_fund, validate_error,
    )

Import order matters: ``api_errors`` registers the error_id -> HTTP status
mapping with the framework at import time, so ``validate_error(resp, ERR_X)``
cross-checks the status code automatically.
"""

# --- Framework generics (re-exported for convenience) -----------------------
from prd_bench_local_runner.testing import (
    GenericApiClient,
    validate_success,
    validate_error,
    validate_paginated,
    validate_error_is_one_of,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    run_race,
    build_user_headers,
    NON_EXISTENT_UUID,
)

# --- PRD-specific modules ---------------------------------------------------
from . import types as _types
from . import constants as _constants
from . import api_errors as _api_errors
from . import test_users as _test_users
from . import assertions as _assertions
from . import factories as _factories
from . import fixtures as _fixtures

from .types import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .api_errors import (  # noqa: F401
    ApiErrorId,
    HTTP_STATUS_CODES,
    ERROR_HTTP_STATUS,
    ALL_ERROR_IDS,
    error_status,
    is_error_id,
)
from .api_client import ApiClient, api_client  # noqa: F401
from .test_users import *  # noqa: F401,F403
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403

_FRAMEWORK_EXPORTS = [
    "GenericApiClient",
    "validate_success",
    "validate_error",
    "validate_paginated",
    "validate_error_is_one_of",
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
]

_PRD_EXPORTS = ["ApiClient", "api_client"]

__all__ = list(
    dict.fromkeys(
        _FRAMEWORK_EXPORTS
        + _PRD_EXPORTS
        + list(_types.__all__)
        + list(_constants.__all__)
        + list(_api_errors.__all__)
        + list(_test_users.__all__)
        + list(_assertions.__all__)
        + list(_factories.__all__)
        + list(_fixtures.__all__)
    )
)
