"""Shared test infrastructure for the motor-carrier operating-authority API.

Importing this package registers the PRD S5 error-id -> HTTP-status map with the
framework validators (side effect of ``api_errors``), so ``validate_error`` can
check the status of any catalogued error id without the test restating it.

Test modules import everything from here::

    from test_helpers import (
        ApiClient, ApiErrorId, REGISTRY_ADMIN, setup_active_authority, ...
    )
"""

from prd_bench_local_runner.testing import (  # noqa: F401
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

from . import factories  # noqa: F401
from .api_client import ApiClient, canonical_instant, raw_body  # noqa: F401
from .api_errors import ERROR_HTTP_STATUS, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .factories import OMITTED, without  # noqa: F401
from .fixtures import *  # noqa: F401,F403
from .test_users import *  # noqa: F401,F403
from .types import *  # noqa: F401,F403
