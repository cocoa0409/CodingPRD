"""Test helper package for the Film Sales Presale API suite.

Re-exports the framework generics alongside the domain-specific client, error
catalogue, assertions, constants, payload factories and composite state builders,
so a test module needs a single import.
"""

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

from .api_client import PREFIX, ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, NOT_FOUND_ERROR_IDS, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    COLLECTION_AGENT_USER,
    COLLECTION_AGENT_USER_ALT,
    DELIVERY_MANAGER_USER,
    HEAD_OF_SALES_CLOSER,
    HEAD_OF_SALES_USER,
    HEAD_OF_SALES_VALUER,
    LENDER_APPROVER,
    LENDER_APPROVER_ALT,
    LENDER_DRAWER,
    LENDER_USER,
    NO_AUTH_HEADERS,
    NO_ROLE_HEADERS,
    NO_USER_HEADERS,
    PLATFORM_ADMIN_USER,
    ROLE_NAMES,
    SALES_AGENT_USER,
    SALES_AGENT_USER_ALT,
    TEST_USERS,
    make_buyer_headers,
    make_collection_agent_headers,
    make_delivery_manager_headers,
    make_head_of_sales_headers,
    make_lender_headers,
    make_platform_admin_headers,
    make_sales_agent_headers,
)
from .types import (
    BankingFacility,
    Buyer,
    BuyerMeeting,
    CollectionAccount,
    ComparableTitle,
    DeliverablePackage,
    DistributionRun,
    Film,
    Market,
    PaymentMilestone,
    PreSaleContract,
    SalesAgencyAgreement,
    ScreeningSlot,
    Territory,
    TerritoryValuation,
    WaterfallTier,
)
