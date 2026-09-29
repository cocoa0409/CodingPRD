"""Test infrastructure for the Medical Professional Liability API.

Re-exports the shared framework generics alongside the helpers written for
this specification, so a test module can import everything from one place.
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

from test_helpers import assertions, constants, factories, fixtures, types  # noqa: F401
from test_helpers.api_client import ApiClient, api_client  # noqa: F401
from test_helpers.api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from test_helpers.test_users import (  # noqa: F401
    CARRIER_ROLE_NAMES,
    TEST_USERS,
    make_actuarial_analyst_headers,
    make_chief_actuary_headers,
    make_claims_adjuster_headers,
    make_claims_committee_approver_headers,
    make_compliance_officer_headers,
    make_insured_headers,
    make_operator_headers,
    make_peer_review_chair_headers,
    make_underwriting_officer_headers,
)
