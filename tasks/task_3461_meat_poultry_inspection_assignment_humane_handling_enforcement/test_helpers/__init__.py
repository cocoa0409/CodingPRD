"""Test infrastructure for the Meat & Poultry Inspection API.

Barrel export: framework generics plus the PRD-specific client, error catalog,
assertions, factories, constants, role headers and composite fixtures, so test
modules import everything from one place.

Two deliberate shape decisions:

* ``validate_success`` is the STRICT wrapper from ``assertions`` — its
  ``expected_status`` argument is required (no silent 200 default), because
  the PRD splits success statuses: 201 on creates, 200 on reads/actions.
  The framework's defaulting variant is not re-exported.

* No module-level client singleton is bound to the name ``api_client`` — that
  name always resolves to the ``test_helpers.api_client`` MODULE. Tests get a
  client from the pytest ``api`` fixture (or construct ``ApiClient()``, which
  reads ``API_BASE_URL`` from the environment).
"""

# ── Framework generics (validate_success deliberately excluded — see above) ──
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
)

# ── PRD-specific modules (also importable as test_helpers.<module>) ──────────
from . import api_client  # noqa: F401  (module, never an instance)
from . import assertions  # noqa: F401
from . import constants  # noqa: F401
from . import factories  # noqa: F401
from . import fixtures  # noqa: F401
from . import test_users  # noqa: F401
from . import types  # noqa: F401

from .api_client import ApiClient, canonical_instant
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# The strict success validator: validate_success(response, expected_status).
from .assertions import (
    assert_appeal,
    assert_effectiveness_check,
    assert_enforcement_action,
    assert_envelope_meta,
    assert_establishment,
    assert_establishment_scores,
    assert_grant_application,
    assert_humane_event,
    assert_inspector,
    assert_instant,
    assert_instant_format,
    assert_label_application,
    assert_list_page,
    assert_noncompliance_record,
    assert_pathogen_sample,
    assert_recall,
    assert_shift_assignment,
    assert_shift_window,
    validate_success,
)

from .constants import *  # noqa: F401,F403  (ROLE_*, thresholds, windows, minimums)

from .factories import (
    adequacy_payload,
    appeal_decision_payload,
    appeal_payload,
    assignment_payload,
    clock_payload,
    determine_class_payload,
    effectiveness_check_payload,
    enforcement_action_payload,
    establishment_payload,
    grant_application_payload,
    grant_decision_payload,
    grant_resubmit_payload,
    humane_event_payload,
    inspector_payload,
    iso_add_days,
    iso_add_minutes,
    iso_add_seconds,
    label_application_payload,
    label_decision_payload,
    label_resubmit_payload,
    lift_payload,
    nr_payload,
    nr_response_payload,
    pathogen_sample_payload,
    recall_payload,
    record_result_payload,
    shift_window_payload,
    verify_response_payload,
)

from .test_users import (
    DISTRICT_MANAGER_HEADERS,
    LABEL_OFFICER_HEADERS,
    PROGRAM_ADMINISTRATOR_HEADERS,
    RECALL_COORDINATOR_HEADERS,
    TEST_USERS,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    make_establishment_manager_headers,
    make_headers,
    make_inspector_headers,
    make_supervisory_reviewer_headers,
)

from .types import *  # noqa: F401,F403  (entity TypedDicts, status enums, UserRole)

from .fixtures import (
    activate_enforcement,
    add_assignment,
    begin_grant_review,
    begin_label_review,
    cancel_assignment,
    categorize_pathogen,
    close_recall,
    collect_pathogen_sample,
    collect_pathogen_samples,
    confirm_assignment,
    confirm_humane_event,
    create_and_confirm_assignment,
    create_approved_label,
    create_class_determined_recall,
    create_closed_recall,
    create_enforcement_action,
    create_establishment,
    create_grant_application,
    create_granted_establishment,
    create_inspector,
    create_inspector_pair,
    create_label_in_review,
    create_recall,
    create_shift_window,
    create_vacated_nr,
    decide_appeal,
    decide_grant,
    decide_label,
    determine_recall_class,
    dismiss_humane_event,
    escalate_nr,
    file_appeal,
    get_establishment,
    get_nr,
    get_recall,
    get_shift_window,
    issue_and_escalate_nrs,
    issue_nr,
    lift_enforcement,
    list_enforcement_actions,
    list_label_applications,
    list_nrs,
    record_adequacy,
    record_all_adequate,
    record_effectiveness_check,
    record_effectiveness_checks,
    record_sample_result,
    report_humane_event,
    respond_to_nr,
    resubmit_label,
    set_clock,
    setup_granted_with_window,
    setup_verified_covered_window,
    submit_label_application,
    suspend_and_lift_via_egregious_event,
    suspend_establishment_via_egregious_event,
    verify_coverage,
    verify_nr,
)
