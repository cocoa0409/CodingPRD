"""Barrel export: framework generics + Wish Grant PRD-specific helpers.

Tests import everything from this single module. Importing this package also
registers the error_id -> HTTP status map with the framework validators
(via api_errors import side effect).
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

# PRD-specific modules (order: leaf modules first)
from .types import *          # entity TypedDicts, status enums, UserRole
from .constants import *      # thresholds, canonical values, reference formulas
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .api_client import ApiClient, api_client
from .assertions import *     # assert_<entity> + invariant/pagination checkers
from .factories import *      # create_*_payload builders
from .test_users import (     # role headers + per-instance builders
    TEST_USERS,
    CHAPTER_DIRECTOR_ALT_ID,
    CHAPTER_DIRECTOR_ID,
    ELIGIBILITY_REVIEWER_ID,
    IN_KIND_OFFICER_ID,
    MEDICAL_PROVIDER_ID,
    NATIONAL_ADMIN_ID,
    NATIONAL_DIRECTOR_ID,
    REFERRAL_SOURCE_ID,
    WISH_COORDINATOR_ID,
    make_chapter_director_headers,
    make_eligibility_reviewer_headers,
    make_in_kind_officer_headers,
    make_medical_provider_headers,
    make_national_admin_headers,
    make_national_director_headers,
    make_referral_source_headers,
    make_volunteer_headers,
    make_wish_coordinator_headers,
)
from .fixtures import *       # composite setup helpers (tiers 0-5)
