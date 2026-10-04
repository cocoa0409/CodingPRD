"""Barrel export: framework generics + PRD-specific helpers.

Test modules import everything from here: the endpoint client and its
singleton, the error catalog, entity assertions and invariant checkers,
payload factories, domain constants, role header builders, and the
composite fixtures that walk the grading lifecycle.
"""
# Framework generics (re-exported for convenience)
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

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .test_users import TEST_USERS
from .test_users import (
    make_class_registrar_headers,
    make_community_official_headers,
    make_comms_supervisor_headers,
    make_evaluation_coordinator_headers,
    make_field_analyst_headers,
    make_fire_chief_headers,
    make_insurer_headers,
    make_water_utility_manager_headers,
)
from .fixtures import *  # noqa: F401,F403
