"""Barrel export: framework generics + PRD-specific helpers.

Tests import everything from here:

    from test_helpers import (
        api_client, validate_created, validate_success, validate_error,
        validate_error_is_one_of, validate_paginated, ApiErrorId,
        setup_citation, assert_citation, make_inspector_headers, ...
    )

Reminders wired into this package:
- ``validate_success(resp)`` defaults to 200; creation endpoints answer 201
  (PRD §4) — use ``validate_created(resp)`` or pass expected_status=201.
- ``validate_error_is_one_of(resp, [ERR_A, ERR_B])`` is re-exported from the
  framework for error-precedence relaxations (PRD §2.5).
- The clock endpoint lives OUTSIDE the /msha prefix:
  ``api_client.set_clock(current_utc, headers)`` or the ``set_clock``
  fixture (PRD §4).
- Role identity (PRD §2.1): Inspector/OperatorRep headers MUST be built
  from the acting entity's id via ``make_inspector_headers`` /
  ``make_operator_rep_headers``; TEST_USERS holds the four opaque roles
  plus non-ownership fallbacks.
"""
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

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_commission_judge_headers,
    make_district_manager_headers,
    make_inspector_headers,
    make_operator_rep_headers,
    make_public_reader_headers,
)
from .fixtures import *  # noqa: F401,F403
