"""Shared test infrastructure for the Menu Prep Par Management API.

The framework package ``prd_bench_local_runner.testing`` supplies the generic
client, validators, and race utilities.  This package layers the PRD-specific
surface on top: role headers (PRD section 2.1), domain constants, an
``ApiClient`` with one method per PRD section 4 endpoint, entity assertions,
payload factories, and composite fixtures that build the deep preconditions
most tests need (published menus, finalized forecasts, locked prep lists,
prepped batches, confirmed bakery orders).
"""

# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)

# PRD-specific
from .types import *
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .constants import *
from .factories import *
from .test_users import *
from .fixtures import *
