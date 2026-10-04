"""Barrel export: framework generics + PRD-specific test infrastructure."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
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
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_claim,
    assert_confidence_level_for_score,
    assert_consumer,
    assert_correction_request,
    assert_data_source,
    assert_dealer,
    assert_history_record,
    assert_listing,
    assert_network,
    assert_report_order,
    assert_shop,
    assert_vehicle,
)
from .constants import *
from .factories import *
from .fixtures import *
from .test_users import (
    ANY_READER_HEADERS,
    TEST_USERS,
    make_dealer_agent_headers,
    make_guarantee_admin_headers,
    make_network_admin_headers,
    make_shop_operator_headers,
    make_source_operator_headers,
    make_vehicle_owner_headers,
)
from .types import *
