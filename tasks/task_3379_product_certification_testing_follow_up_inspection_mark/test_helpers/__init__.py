"""Test infrastructure for the Product Certification Followup API.

Barrel export: the framework's generic validators and race utilities are
re-exported alongside the PRD-specific client, error catalog, assertions,
factories, constants, role headers and composite fixtures, so test modules
import everything from one place.
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
from .api_client import ApiClient, api_client, canonical_instant
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    DEFAULT_ADMIN_ID,
    DEFAULT_COMPLIANCE_OFFICER_ID,
    DEFAULT_ENGINEER_ID,
    DEFAULT_INSPECTOR_ID,
    DEFAULT_REVIEWER_ID,
    SECOND_ENGINEER_ID,
    SECOND_REVIEWER_ID,
    TEST_USERS,
    UNDECLARED_ROLE,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    make_ahj_authority_headers,
    make_certification_body_admin_headers,
    make_certification_reviewer_headers,
    make_compliance_officer_headers,
    make_factory_inspector_headers,
    make_manufacturer_rep_headers,
    make_test_engineer_headers,
    no_auth_headers,
)
from .fixtures import *
from . import fixtures
