"""Shared test infrastructure for the Stroke Center Certification & Telestroke Network API.

Re-exports the framework generics alongside this task's client, factories,
assertions, constants, identities and composite fixtures so a test module can
import everything it needs from one place.
"""
from prd_bench_local_runner.testing import (  # noqa: F401
    NON_EXISTENT_UUID,
    GenericApiClient,
    assert_cost_precision,
    assert_race_outcome,
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

from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import ApiClient, api_client, canonical_instant, instants_equal  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ABSTRACTOR,
    ATTESTER,
    COORD,
    COORD_ALT,
    ED,
    ED_ALT,
    REVIEWER,
    REVIEWER_ALT,
    TEST_USERS,
    TRANSFER,
    make_certification_reviewer_headers,
    make_ed_physician_headers,
    make_neurologist_headers,
    make_program_coordinator_headers,
    make_quality_abstractor_headers,
    make_transfer_coordinator_headers,
)
from .types import UserRole  # noqa: F401
