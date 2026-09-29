"""Shared test infrastructure for the state child care licensing API.

Import surface used by ``test_suite/``::

    from test_helpers import (
        api_client, admin_headers, supervisor_headers,
        validate_success, validate_error,
        fixtures, factories, constants, types,
    )
"""

# ─── framework primitives ──────────────────────────────────────────────
from prd_bench_local_runner.testing import (
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

# ─── domain modules (import as namespaces too) ─────────────────────────
from . import api_errors, assertions, constants, factories, fixtures, types
from .api_client import ApiClient, api_client
from .api_errors import ERROR_HTTP_STATUS, NOT_FOUND_BY_PATH_PARAM
from .assertions import (
    SCORE_TOLERANCE,
    assert_banner_for_ladder_step,
    assert_capacity_slots,
    assert_capacity_total_preserved,
    assert_cents,
    assert_checklist_item,
    assert_compliance_score_read,
    assert_created_at_ascending,
    assert_default_page_window,
    assert_fields_absent,
    assert_group_size_within_statutory_max,
    assert_inspection,
    assert_instant,
    assert_list_envelope,
    assert_point_conservation,
    assert_point_ledger,
    assert_points,
    assert_provider,
    assert_record,
    assert_risk,
    assert_risk_assessment,
    assert_roster_flags,
    assert_score,
    assert_versioned_record,
    assert_violation,
    canonical_instant,
    expected_required_staff_count,
    expected_risk_tier,
    parse_instant,
    plus_days,
    plus_hours,
    plus_minutes,
    plus_months,
    plus_seconds,
)
# every module-level constant (CODE_*, DEFAULT_*, FINE_*, RISK_*, ...) is
# re-exported, so tests can write ``from test_helpers import CODE_RATIO``
globals().update(
    {n: getattr(constants, n) for n in dir(constants) if n[:1].isupper()}
)
from .test_users import (
    ADMIN_1,
    ADMIN_2,
    BGU_1,
    INTAKE_1,
    PUBLIC_1,
    SUPERVISOR_1,
    SUPERVISOR_2,
    SUPERVISOR_3,
    TEST_USERS,
    admin_headers,
    applicant_creation_headers,
    bgu_headers,
    headers_with_blank_user_id,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    intake_headers,
    make_applicant_headers,
    make_inspector_headers,
    make_investigator_headers,
    no_identity_headers,
    public_headers,
    supervisor_headers,
)

# every ERR_* symbol, so tests can write ``from test_helpers import ERR_...``
globals().update(
    {n: getattr(api_errors, n) for n in dir(api_errors) if n.startswith("ERR_")}
)

__all__ = [n for n in globals() if not n.startswith("_")]
