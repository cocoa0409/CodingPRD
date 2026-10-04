"""Barrel export: framework generics + PRD-specific test infrastructure."""
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
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_artifact,
    assert_assessment_center,
    assert_assessor,
    assert_assignment,
    assert_benchmark,
    assert_booking,
    assert_candidate,
    assert_certification,
    assert_certification_validity_window,
    assert_common_fields,
    assert_cycle,
    assert_incentive_program,
    assert_program_budget_invariant,
    assert_renewal,
    assert_score_on_grid,
    assert_stipend,
    assert_submission,
    expected_weighted_total,
    round_half_up,
    validate_created,
)
from .constants import *
from .factories import *
from .fixtures import *
from .test_users import (
    TEST_USERS,
    make_anonymous_headers,
    make_assessor_headers,
    make_board_admin_headers,
    make_candidate_headers,
    make_incentive_admin_headers,
    make_scoring_admin_headers,
)
from .types import *
