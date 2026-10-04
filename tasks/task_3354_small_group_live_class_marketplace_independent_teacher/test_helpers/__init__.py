"""Barrel export: framework generics + PRD-specific helpers."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
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
    NON_EXISTENT_UUID,
)

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import TEST_USERS, make_teacher_headers  # noqa: F401
from .fixtures import *  # noqa: F401,F403

# Explicit re-exports of the setup helpers most tests reach for, so the
# star-import surface above stays readable in test modules.
from .fixtures import (  # noqa: F401
    cancel_section,
    confirm_seat,
    create_application,
    create_learner,
    create_listing,
    create_section,
    declare_minimum_met,
    dispose_report,
    file_report,
    get_enrollment,
    get_learner,
    get_listing,
    get_payout,
    get_report,
    get_section,
    get_teacher,
    get_teacher_version,
    list_payouts_for_teacher,
    onboard_active_teacher,
    onboard_pending_teacher,
    policy_approve_listing,
    publish_listing,
    request_payout,
    reserve_and_confirm,
    reserve_seat,
    review_sample,
    run_ops,
    set_clock,
    setup_application_at_sample_pending,
    setup_compensating_refund_scenario,
    setup_listing,
    setup_refund_cascade_scenario,
    setup_tax_document_gate_scenario,
    submit_application,
    submit_sample,
    subscribe_learner,
    transition_payout,
)
from .test_users import (  # noqa: F401
    make_parent_headers,
    make_platform_admin_headers,
    make_teacher_applicant_headers,
    make_teacher_reviewer_headers,
)
