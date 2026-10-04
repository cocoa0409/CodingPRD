"""Barrel export: framework generics + PRD-specific test helpers.

Tests import everything from here (`from test_helpers import ...`).

Framework generics re-exported:
  validate_success, validate_error, validate_paginated,
  validate_error_is_one_of, get_success_data, is_valid_uuid,
  is_iso8601_timestamp, assert_cost_precision, assert_version_incremented,
  assert_timestamp_format, assert_race_outcome, assert_exactly_one_succeeds,
  assert_at_least_one_succeeds, run_race, build_user_headers,
  NON_EXISTENT_UUID

PRD-specific surface (see each module's API MANIFEST header):
  types.py        — status enums, UserRole, entity TypedDicts
  api_client.py   — api_client / ApiClient (one method per endpoint)
  api_errors.py   — ApiErrorId, HTTP_STATUS_CODES (registered on import)
  assertions.py   — assert_<entity>() shape checks, ledger invariants,
                    months_between / compute_provisional_months /
                    compute_committee_months oracles
  factories.py    — DEFAULTS + per-entity payload factories
  constants.py    — PRD-prose thresholds and vocabularies
  test_users.py   — TEST_USERS + make_<role>_headers builders
  fixtures.py     — composite setup helpers (contexts, lifecycle chains)
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
from .types import *
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    TEST_USERS,
    make_candidate_headers,
    make_conduct_adjudicator_headers,
    make_conduct_investigator_headers,
    make_experience_reviewer_headers,
    make_program_admin_headers,
    make_proctor_headers,
    make_reference_provider_headers,
)
from .fixtures import *
