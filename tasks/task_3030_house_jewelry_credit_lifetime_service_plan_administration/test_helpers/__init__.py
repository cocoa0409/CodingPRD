"""Barrel export: framework generics plus PRD-specific infrastructure."""

from prd_bench_local_runner.testing import (
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

from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_appraisal,
    assert_billing_statement,
    assert_bundle,
    assert_credit_application,
    assert_custom_design_order,
    assert_customer,
    assert_customer_invariants,
    assert_diamond,
    assert_inspection_visit,
    assert_ledger_entry,
    assert_plan_invariants,
    assert_promotional_plan,
    assert_purchase,
    assert_purchase_invariants,
    assert_registration,
    assert_registration_invariants,
    assert_regulation,
    assert_repair,
    assert_repair_hold,
    assert_repair_invariants,
    assert_store,
    assert_timestamp,
    assert_vendor_shop,
)
from .constants import *  # noqa: F401,F403
from .factories import (
    create_appraisal_payload,
    create_billing_statement_payload,
    create_bundle_payload,
    create_credit_application_payload,
    create_custom_design_order_payload,
    create_customer_payload,
    create_diamond_payload,
    create_inspection_visit_payload,
    create_ledger_entry_payload,
    create_promotional_plan_payload,
    create_purchase_payload,
    create_registry_row_payload,
    create_registration_payload,
    create_regulation_payload,
    create_repair_hold_payload,
    create_repair_payload,
    create_store_payload,
    create_vendor_shop_payload,
)
from .fixtures import *  # noqa: F401,F403
from .test_users import TEST_USERS, make_customer_headers
from .types import *  # noqa: F401,F403

__all__ = [
    # framework generics
    "NON_EXISTENT_UUID", "GenericApiClient", "assert_at_least_one_succeeds",
    "assert_cost_precision", "assert_exactly_one_succeeds", "assert_race_outcome",
    "assert_timestamp_format", "assert_version_incremented", "build_user_headers",
    "get_success_data", "is_iso8601_timestamp", "is_valid_uuid", "run_race",
    "validate_error", "validate_error_is_one_of", "validate_paginated",
    "validate_success",
    # PRD infrastructure
    "ApiClient", "api_client", "ApiErrorId", "HTTP_STATUS_CODES",
    "TEST_USERS", "make_customer_headers",
    "create_store_payload", "create_customer_payload", "create_registry_row_payload",
    "create_regulation_payload", "create_vendor_shop_payload", "create_bundle_payload",
    "create_credit_application_payload", "create_promotional_plan_payload",
    "create_ledger_entry_payload", "create_diamond_payload", "create_purchase_payload",
    "create_registration_payload", "create_inspection_visit_payload",
    "create_repair_payload", "create_repair_hold_payload", "create_appraisal_payload",
    "create_custom_design_order_payload", "create_billing_statement_payload",
    "assert_timestamp", "assert_store", "assert_customer", "assert_credit_application",
    "assert_promotional_plan", "assert_ledger_entry", "assert_diamond", "assert_bundle",
    "assert_vendor_shop", "assert_regulation", "assert_registration",
    "assert_inspection_visit", "assert_repair", "assert_repair_hold", "assert_appraisal",
    "assert_purchase", "assert_custom_design_order", "assert_billing_statement",
    "assert_registration_invariants", "assert_repair_invariants",
    "assert_purchase_invariants", "assert_plan_invariants", "assert_customer_invariants",
]