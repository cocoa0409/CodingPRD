"""Barrel export: framework generics plus the PRD-specific helpers."""
# Framework generics, re-exported for a single import source.
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
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_benefit_network,
    assert_booking,
    assert_business_subscription,
    assert_class_pack,
    assert_class_session,
    assert_class_template,
    assert_client,
    assert_commission_entry,
    assert_feature_gates_match_tier,
    assert_membership,
    assert_payroll_period,
    assert_portability_request,
    assert_same_instant,
    assert_seat_occupancy_conserved,
    assert_staff_member,
    assert_studio,
    assert_subscription_tier,
    assert_waitlist_entry,
    same_instant,
)
from .constants import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .fixtures import ADMIN, ANONYMOUS, OPERATOR, SetupFailure  # noqa: F401
from .factories import (
    create_benefit_network_payload,
    create_booking_payload,
    create_class_pack_payload,
    create_class_session_payload,
    create_class_template_payload,
    create_client_payload,
    create_marketplace_booking_payload,
    create_membership_payload,
    create_payroll_period_payload,
    create_portability_request_payload,
    create_staff_member_payload,
    create_studio_payload,
    join_waitlist_payload,
)
from .test_users import (
    NO_CONTEXT_HEADERS,
    TEST_USERS,
    make_anonymous_headers,
    make_client_headers,
    make_operator_headers,
    make_platform_admin_headers,
    make_staff_member_headers,
    make_studio_owner_headers,
)
from .types import *  # noqa: F401,F403