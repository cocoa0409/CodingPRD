"""Test infrastructure for the Multimodal Shipment Visibility API.

Re-exports the framework generics and the pieces of this package that test
modules reach for most often: the endpoint client, the error catalog, the
domain assertions, the payload factories and the composite fixtures.
"""

# Framework generics (re-exported for convenience).
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

# Domain-specific.
from . import constants, factories, fixtures
from .api_client import ApiClient, api_client, canonical_instant
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_alert,
    assert_append_only_common_fields,
    assert_appointment,
    assert_carrier,
    assert_connection,
    assert_consignee,
    assert_data_share_grant,
    assert_facility,
    assert_heartbeat_record,
    assert_identity_link,
    assert_instant_equal,
    assert_list_page,
    assert_mutable_common_fields,
    assert_ops_run,
    assert_purchase_order,
    assert_shipment,
    assert_shipper,
    assert_tracking_event,
)
from .constants import (
    BASE_CLOCK,
    CADENCE_MINUTES,
    CI_BASE_HALFWIDTH_MINUTES,
    CONFIRM_THRESHOLD,
    ESCALATION_SLA_MINUTES,
    FREE_TIME_MINUTES,
    GRACE_MINUTES,
    QUALITY_GATE_MINIMUM,
    STALE_CI_MULTIPLIER,
    TOLERANCE_MINUTES,
    UNSET_QUALITY_NEUTRAL,
)
from .test_users import (
    CUSTOMER_SERVICE_HEADERS,
    NETWORK_OPS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    TEST_USERS,
    make_carrier_rep_headers,
    make_consignee_rep_headers,
    make_shipper_rep_headers,
)
from .types import (
    ROLE_CARRIER_REP,
    ROLE_CONSIGNEE_REP,
    ROLE_CUSTOMER_SERVICE,
    ROLE_NETWORK_OPS,
    ROLE_PLATFORM_ADMIN,
    ROLE_SHIPPER_REP,
)
