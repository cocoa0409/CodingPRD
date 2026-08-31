"""Barrel export: framework generics plus PRD-specific test infrastructure."""

from prd_bench_local_runner.testing import (  # noqa: F401
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

from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN,
    ADMIN_USER_ID,
    BA_APPROVER,
    BA_APPROVER_USER_ID,
    BA_PAYER,
    BA_PAYER_USER_ID,
    EDITOR_APPROVE,
    EDITOR_APPROVE_USER_ID,
    EDITOR_ASSIGN,
    EDITOR_ASSIGN_USER_ID,
    EXEC_ALPHA,
    EXEC_ALPHA_USER_ID,
    EXEC_BETA,
    EXEC_BETA_USER_ID,
    SUBMITTER,
    SUBMITTER_USER_ID,
    TEST_USERS,
    make_business_affairs_headers,
    make_committee_member_headers,
    make_development_exec_headers,
    make_reader_headers,
    make_slate_admin_headers,
    make_story_editor_headers,
    make_submitter_headers,
    make_writer_headers,
)
from .types import *  # noqa: F401,F403
