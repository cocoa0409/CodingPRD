"""Test helper package for the Airline Distribution Offers API.

Re-exports the framework generics alongside this suite's domain helpers so test
modules have a single import surface.
"""

from prd_bench_local_runner.testing import (  # noqa: F401
    NON_EXISTENT_UUID,
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

from . import factories, fixtures  # noqa: F401
from .api_client import (  # noqa: F401
    ApiClient,
    api_client,
    canonical_instant,
    instants_equal,
    shift_instant,
)
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import OMIT, unique_code, unique_suffix  # noqa: F401
from .test_users import (  # noqa: F401
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    AUDITOR_HEADERS,
    AUDITOR_USER_ID,
    DISTRIBUTION_MANAGER_HEADERS,
    DISTRIBUTION_MANAGER_USER_ID,
    OTHER_DISTRIBUTION_MANAGER_HEADERS,
    OTHER_DISTRIBUTION_MANAGER_USER_ID,
    PRICING_ANALYST_HEADERS,
    PRICING_ANALYST_USER_ID,
    TEST_USERS,
    UNKNOWN_ROLE,
    agency_headers,
    headers_empty_role,
    headers_empty_user_id,
    headers_for_role,
    headers_missing_role,
    headers_missing_user_id,
    headers_unknown_role,
    technology_partner_headers,
)
from .types import (  # noqa: F401
    AgencyAgreement,
    AncillaryProduct,
    BundleDefinition,
    Channel,
    ConnectivityTest,
    CorporateContract,
    DistributionPartner,
    FareFiling,
    Offer,
    OfferItem,
    Order,
    PartnerCertification,
    ServiceRequest,
    SurchargeRule,
)
