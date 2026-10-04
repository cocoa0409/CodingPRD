"""Barrel export: framework generics + PRD-specific code."""

# Framework generics (re-exported for convenience)
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

# PRD-specific infrastructure
from . import constants
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_artwork_approval,
    assert_card_set,
    assert_card_set_invariants,
    assert_collector_complaint,
    assert_collector_notification,
    assert_distribution_allocation,
    assert_endorsement_pair,
    assert_license,
    assert_license_invariants,
    assert_pack_configuration,
    assert_print_run_decision,
    assert_product_line,
    assert_quality_claim,
    assert_redemption,
    assert_signing_session,
)
from .constants import *
from .factories import (
    allocation_line,
    create_allocation_payload,
    create_artwork_approval_payload,
    create_card_set_payload,
    create_complaint_payload,
    create_license_payload,
    create_notification_payload,
    create_pack_configuration_payload,
    create_print_run_decision_payload,
    create_product_line_payload,
    create_quality_claim_payload,
    create_redemption_payload,
    create_signing_session_payload,
)
from .fixtures import (
    advance_clock,
    approve_artwork_for_set,
    approve_card_set,
    build_approved_quality_claim,
    build_approved_set,
    build_fulfilled_redemption,
    build_packed_out_line,
    build_ready_to_ship_allocation,
    build_redemption_near_deadline,
    create_active_license,
    create_card_set_raw,
    create_license_raw,
    create_line_ready,
    create_product_line_raw,
    freeze_print_run,
    issue_plain_redemption,
    publish_pack_configuration,
    setup_clock,
    submit_card_set_for_review,
)
from .test_users import TEST_USERS, make_licensor_approver_headers, make_unknown_role_headers
from .types import *