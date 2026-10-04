"""Barrel export: framework generics plus the PRD-specific helpers."""

# Framework generics (re-exported for convenience).
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

# PRD-specific infrastructure.
from .api_client import ApiClient, api_client, canonical_instant
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_append_only_fields,
    assert_campaign_budget_invariant,
    assert_catalog_item,
    assert_cents,
    assert_common_fields,
    assert_donation,
    assert_donor,
    assert_donor_conservation,
    assert_equity_fund,
    assert_fraud_case,
    assert_identity_fields,
    assert_instant,
    assert_instant_format,
    assert_match_campaign,
    assert_one_dp,
    assert_project,
    assert_project_item,
    assert_purchase_order,
    assert_school,
    assert_teacher,
    assert_thank_you_package,
    assert_vendor,
)
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .test_users import (
    ADMIN_HEADERS,
    ANON_HEADERS,
    REVIEWER_ANA_HEADERS,
    REVIEWER_BEN_HEADERS,
    TEST_USERS,
    make_donor_headers,
    make_teacher_headers,
    make_vendor_headers,
    reviewer_headers,
)
from . import fixtures
from .types import (  # noqa: F401
    CatalogItemStatus,
    DonationKind,
    DonationStatus,
    EmploymentStatus,
    EquityFundStatus,
    FraudCaseStatus,
    MatchCampaignStatus,
    ProjectStatus,
    PurchaseOrderStatus,
    RefundReason,
    ThankYouPackageStatus,
    UserRole,
    VendorStatus,
)
