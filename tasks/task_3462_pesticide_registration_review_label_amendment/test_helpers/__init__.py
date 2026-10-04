"""Barrel export: framework generics + PRD-specific helpers.

Tests import everything from here:

    from test_helpers import (
        api_client, ApiClient, ApiErrorId, TEST_USERS,
        validate_success, validate_error, validate_paginated, ...,
    )

Note on the client singleton: ``from test_helpers import api_client`` yields
the shared ``ApiClient`` instance (the package attribute is the instance;
the same-named submodule is intentionally shadowed at package level).
"""
# --- Framework generics (re-exported for convenience) ---
from prd_bench_local_runner.testing import (
    GenericApiClient,
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

# --- PRD-specific ---
from .types import *  # noqa: F401,F403 — enums and entity TypedDicts
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .constants import *  # noqa: F401,F403 — domain thresholds
from .calc import *  # noqa: F401,F403 — expected-value calculators
from .assertions import *  # noqa: F401,F403 — entity + invariant assertions
from .factories import *  # noqa: F401,F403 — payload factories
from .test_users import *  # noqa: F401,F403 — TEST_USERS + make_*_headers
from .fixtures import *  # noqa: F401,F403 — composite setup helpers
