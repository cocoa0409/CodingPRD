"""Test infrastructure for the Classroom Book Club API.

Re-exports the framework generics plus the pieces test modules reach for most
often: the endpoint client, the error catalog, domain assertions, factories,
composite fixtures, and pre-built role headers.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    assert_at_least_one_succeeds,
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

from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_book_fair,
    assert_class_order,
    assert_donation_request,
    assert_fair_title,
    assert_flyer_cycle,
    assert_flyer_offering,
    assert_order_line,
    assert_points_ledger_entry,
    assert_program_enrollment,
    assert_promotion,
    assert_redemption,
    assert_school,
    assert_teacher,
    assert_teacher_points_reconcile,
    assert_title,
)
from .constants import (
    CENTS_PER_POINT,
    CLUB_PRICE_FACTOR_DEN,
    CLUB_PRICE_FACTOR_NUM,
    CLOCK_DEFAULT_ISO,
    DEFAULT_CYCLE_MONTH,
    DEFAULT_ENROLLED_ON,
    FREE_SHIP_MIN_CENTS,
    POINTS_EXPIRY_MONTHS,
    PROMO_BASE_BP,
    ROYALTY_PER_UNIT_CENTS,
    SHIPPING_FLAT_CENTS,
    SUPPLY_UNIT_POINTS_COST,
    TIER_1_BP,
    TIER_1_MIN_CENTS,
    TIER_2_BP,
    TIER_2_MIN_CENTS,
    TIER_3_BP,
    TIER_3_MIN_CENTS,
    TITLE_FAIR_OVERLAP_LIMIT,
)
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import TEST_USERS, make_teacher_headers
from .types import *  # noqa: F401,F403
