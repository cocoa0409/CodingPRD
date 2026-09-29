"""
Test helpers for the Building Trades Hiring Hall Dispatch API compliance suite.

Test modules import everything they need from this package, never from the
underlying framework directly.
"""

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

from . import factories, fixtures  # noqa: F401
from .api_client import (  # noqa: F401
    HiringHallApiClient,
    canonical_instant,
    parse_instant,
    plus_days,
    plus_hours,
    plus_millis,
    render_instant,
)
from .api_errors import *  # noqa: F401,F403
from .api_errors import ERROR_HTTP_STATUS  # noqa: F401
from .assertions import (  # noqa: F401
    assert_bare_uuid,
    assert_envelope_meta,
    assert_error_meta_is_minimal,
    assert_full_common_fields,
    assert_instant_equals,
    assert_instant_order,
    assert_instant_shape,
    assert_integer_hours,
    assert_integer_money,
    assert_ordinal_block,
    assert_pagination,
    assert_reduced_common_fields,
    assert_registration_off_book,
    assert_registration_on_book,
    assert_single_read_omits_pagination,
    assert_slot_conservation,
    expect_created,
    expect_error,
    expect_ok,
    expect_one_of,
    find_row,
    ids_of,
    round_half_up_bp,
    validate_list,
    validate_unpaginated,
)
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    BUSINESS_MANAGER,
    BUSINESS_MANAGER_USER_ID,
    DISPATCHER,
    DISPATCHER_USER_ID,
    HALL_ADMIN,
    HALL_ADMIN_USER_ID,
    OTHER_BUSINESS_MANAGER,
    OTHER_BUSINESS_MANAGER_USER_ID,
    OTHER_DISPATCHER,
    OTHER_DISPATCHER_USER_ID,
    TEST_USERS,
    headers_blank_role,
    headers_blank_user_id,
    headers_missing_role,
    headers_missing_user_id,
    headers_unknown_role,
    make_business_manager_headers,
    make_contractor_rep_headers,
    make_dispatcher_headers,
    make_hall_admin_headers,
    make_member_headers,
)
from .types import (  # noqa: F401
    ClockState,
    Contractor,
    Dispatch,
    DispatchLedgerEntry,
    DispatchOrderRead,
    DispatchRunResult,
    ErrorPayload,
    Grievance,
    JobRequest,
    Local,
    Member,
    OutOfWorkList,
    RatioPolicy,
    ReciprocityCredit,
    Referral,
    Registration,
    ResponseMeta,
    SkillEndorsement,
)
