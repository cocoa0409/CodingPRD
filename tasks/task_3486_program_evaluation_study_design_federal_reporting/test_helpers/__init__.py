"""Barrel export: framework generics + PRD-specific helpers.

Note: the framework's validate_success (which defaults expected_status to 200)
is intentionally NOT re-exported here. This package's validate_success comes
from .assertions and REQUIRES an explicit expected_status, so create-endpoint
checks (201) can never be silently validated against 200.
"""
# Framework generics (validate_success deliberately excluded — see docstring)
from prd_bench_local_runner.testing import (
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

# PRD-specific
from .types import *
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *  # provides the strict validate_success
from .factories import *
from .constants import *
from .test_users import TEST_USERS
from .test_users import (
    make_agency_officer_headers,
    make_principal_investigator_headers,
    make_study_director_headers,
    make_data_manager_headers,
    make_irb_reviewer_headers,
    make_peer_reviewer_headers,
    make_participant_headers,
    make_external_researcher_headers,
    make_platform_admin_headers,
)
from .fixtures import *
