"""Barrel export: framework generics + PRD-specific code.

Import contract (read before importing):

- ``from test_helpers import api_client`` gives the SHARED ApiClient singleton
  (constructed from ``API_BASE_URL`` at import time). This is the intended
  handle for tests and fixtures.
- Because the package attribute ``api_client`` is re-bound to that singleton,
  ``import test_helpers.api_client as ac`` ALSO binds the singleton, not the
  module object. This is deliberate. The module object itself remains
  reachable as ``test_helpers.api_client_module`` (and via
  ``importlib.import_module("test_helpers.api_client")``).
- The client class is exported as ``test_helpers.ApiClient``; construct a new
  one only if a test needs an isolated session.
"""

# Framework generics (re-exported for convenience)
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

# PRD-specific: bind the submodule first so it stays reachable under an
# explicit alias, then re-export the class and the shared singleton.
from . import api_client as api_client_module  # noqa: F401  (module handle)
from .api_client import ApiClient, api_client  # noqa: F401  (class, singleton)
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    TEST_USERS,
    make_compliance_officer_headers,
    make_entry_reviewer_headers,
    make_facility_owner_headers,
    make_field_inspector_headers,
    make_importer_headers,
    make_platform_admin_headers,
    make_recall_coordinator_headers,
)
from .types import *  # noqa: F401,F403
