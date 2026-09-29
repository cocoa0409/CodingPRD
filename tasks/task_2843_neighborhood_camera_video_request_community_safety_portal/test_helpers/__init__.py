"""Shared test infrastructure for the Neighborhood Camera Video Request &
Community Safety Portal API.

Modules:

  ``constants``   contract literals: roles, enumerated values, declared defaults
                  and the arithmetic constants of the derived-value rules
  ``api_errors``  the declared error identifiers and their HTTP statuses
  ``test_users``  caller identities for the six roles, with per-entity builders
                  for the three entity-backed roles
  ``api_client``  one method per declared endpoint, returning the raw response
  ``factories``   request payload builders with overridable defaults
  ``assertions``  envelope, common-property, ledger and precision assertions
  ``fixtures``    composite setups that walk the API to a wanted state
  ``types``       the declared response shapes

Everything a test needs is re-exported here, so a test file can import from
``test_helpers`` alone.
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

from . import assertions, factories, fixtures  # noqa: F401
from .api_client import ApiClient, canonical_instant  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import (  # noqa: F401
    assert_array_envelope,
    assert_ascending,
    assert_bps,
    assert_created_equals_updated,
    assert_envelope_meta,
    assert_fanout_conservation,
    assert_field_sequence,
    assert_footage_ledger,
    assert_identity,
    assert_ids_in_order,
    assert_instant,
    assert_instant_format,
    assert_list_page,
    assert_millis_instant,
    assert_mutable_common_fields,
    assert_nulls,
    assert_object_envelope,
    assert_receipt_common_fields,
    assert_score,
    assert_solicitation_buckets,
    assert_solicitation_ledger,
    assert_strike_ladder,
    assert_subset,
    assert_two_dp,
    assert_version_advanced,
    assert_version_unchanged,
    assert_zero_counters,
)
from .constants import *  # noqa: F401,F403
from .fixtures import (  # noqa: F401
    FOOTAGE_WINDOW_END,
    FOOTAGE_WINDOW_START,
    SCENARIO_CLOCK,
    STANDARD_POSITIONS,
    add_auditor,
    certify_report,
    change_agency_status,
    compile_report,
    create_area,
    create_officer,
    create_post,
    create_video_request,
    decide_case,
    decline_solicitation,
    escalate_audit,
    exercise_data_control,
    flag_post,
    flag_until_flagged,
    list_cases_for_post,
    list_clips_for_device,
    list_data_control_actions,
    list_dispatches,
    list_rows,
    list_solicitations,
    lock_area,
    log_justification,
    onboarded_agency,
    open_case,
    purge_clip,
    read_agency,
    read_area,
    read_case,
    read_clip,
    read_device,
    read_officer,
    read_post,
    read_report,
    read_request,
    read_resident,
    read_solicitation,
    register_agency,
    register_device,
    register_resident,
    review_audit,
    review_onboarding,
    revise_post,
    run_sweep,
    seed_agency_with_officer,
    seed_flagged_post,
    seed_justified_request,
    seed_locked_area,
    seed_post_under_review,
    seed_resident_with_device,
    seed_residents_with_devices,
    seed_standard_canvass,
    seed_submitted_request,
    set_clock,
    share_footage,
    solicitation_for_device,
    submit_request,
    suspend_agency,
    update_alert_settings,
    update_device,
    withdraw_request,
)
from .test_users import (  # noqa: F401
    ANONYMOUS_HEADERS,
    MODERATOR_HEADERS,
    MODERATOR_ID,
    MODERATOR_SECOND_HEADERS,
    MODERATOR_SECOND_ID,
    NO_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    PLATFORM_ADMIN_ID,
    PLATFORM_ADMIN_SECOND_HEADERS,
    PLATFORM_ADMIN_SECOND_ID,
    TEST_USERS,
    UNDECLARED_ROLE,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    make_agency_admin_headers,
    make_anonymous_headers,
    make_moderator_headers,
    make_officer_headers,
    make_platform_admin_headers,
    make_resident_headers,
)
