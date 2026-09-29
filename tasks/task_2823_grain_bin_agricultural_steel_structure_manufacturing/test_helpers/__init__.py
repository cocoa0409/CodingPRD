"""Shared test infrastructure for the grain-bin manufacturing API.

Import everything from this package rather than from its modules:

    from test_helpers import (
        api_client, validate_success, ApiErrorId, setup_reference_data,
    )

The generic framework helpers (``validate_success``, ``validate_error``,
``validate_paginated``, ``run_race`` and friends) are re-exported here so a test
module needs a single import block.
"""

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

from . import assertions, constants, factories, fixtures, types
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    TEST_USERS,
    headers_for_role,
    headers_without_role,
    headers_without_user_id,
    make_dealer_principal_headers,
    make_design_engineer_headers,
    make_logistics_coordinator_headers,
    make_plant_admin_headers,
    make_production_planner_headers,
    make_quality_inspector_headers,
    make_sealing_engineer_headers,
)
from .types import *  # noqa: F401,F403
