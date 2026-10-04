"""Barrel export: framework generics + PRD-specific helpers.

`test_helpers.api_client` is re-exported as the MODULE (with module-level
endpoint functions), never as a singleton instance — both of these work:

    from test_helpers import api_client
    api_client.get_application(app_id, headers)          # module function

    import test_helpers.api_client as ac
    ac.get_application(app_id, headers)                  # same module
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

# PRD-specific code. NOTE: `from . import api_client` binds the submodule
# itself; the endpoint functions are module-level (see api_client.py).
from . import api_client
from .api_client import ApiClient
from .types import *
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_reviewer_headers,
    make_program_officer_headers,
    make_referral_officer_headers,
    make_sro_headers,
    make_council_member_headers,
    make_grants_officer_headers,
    without_header,
)
from .fixtures import *
