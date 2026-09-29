"""Test infrastructure for the Mental Health Parity Comparative Analysis API.

Importing this package registers the error_id -> HTTP status map, so
`validate_error` cross-checks the status of every error identifier it is given.
"""

from prd_bench_local_runner.testing import (
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

from . import factories
from . import fixtures
from .api_client import ApiClient, api_client, canonical_instant
from .api_errors import HTTP_STATUS_CODES, NOT_FOUND_ERROR_IDS, ApiErrorId
from .assertions import (
    assert_append_only_resource,
    assert_cents,
    assert_collection,
    assert_created,
    assert_empty_collection,
    assert_error,
    assert_fields,
    assert_id_set,
    assert_ids_equal,
    assert_index,
    assert_instant_equals,
    assert_is_none,
    assert_ok,
    assert_ratio,
    assert_score,
    assert_versioned_resource,
)
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    OFFICER_USER_ID,
    OFFICER_USER_ID_ALT,
    REGULATOR_USER_ID,
    REGULATOR_USER_ID_ALT,
    SPONSOR_USER_ID,
    SPONSOR_USER_ID_ALT,
    TEST_USERS,
    make_administrator_headers,
    make_blank_user_id_headers,
    make_headers,
    make_missing_role_headers,
    make_missing_user_id_headers,
    make_officer_headers,
    make_regulator_headers,
    make_sponsor_headers,
    make_unknown_role_headers,
)
from .types import (
    Administrator,
    BenefitClassification,
    ClockState,
    CommonFields,
    ComparativeAnalysis,
    CorrectiveActionPlan,
    DataSubmission,
    NqtlItem,
    ParityTest,
    ParticipantNotice,
    PlanYear,
    RegulatorRequest,
    TreatmentLimitation,
    VendorDataRequest,
)
