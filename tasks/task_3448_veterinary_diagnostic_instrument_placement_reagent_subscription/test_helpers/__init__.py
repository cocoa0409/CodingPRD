"""Barrel export: framework generics + PRD-specific code.

Test files import everything from here::

    from test_helpers import (
        api_client, ApiClient, ApiErrorId, TEST_USERS,
        validate_success, validate_error, validate_error_is_one_of, ...
    )

IMPORT-IDIOM WARNING: ``from test_helpers import api_client`` yields the
shared ApiClient INSTANCE (re-exported below). Because the instance shadows
the ``test_helpers.api_client`` submodule on the package, never write
``import test_helpers.api_client as ac`` expecting a module — use the barrel.
"""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    assert_at_least_one_succeeds,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assert_timestamp_format,
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
from prd_bench_local_runner.testing import (
    assert_version_incremented as _framework_assert_version_incremented,
)


def assert_version_incremented(before, after, min_increment=1):
    """Assert OCC version incremented, in documented (before, after) order.

    INTERFACE.md and every call site in this suite pass (before, after); the
    framework helper takes (new_version, old_version) — adapt here.
    """
    _framework_assert_version_incremented(after, before, min_increment)

# PRD-specific
from .types import *
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    TEST_USERS,
    make_clinic_manager_headers,
    make_field_service_engineer_headers,
    make_finance_reviewer_headers,
    make_laboratory_technician_headers,
    make_platform_admin_headers,
)
from .fixtures import *
