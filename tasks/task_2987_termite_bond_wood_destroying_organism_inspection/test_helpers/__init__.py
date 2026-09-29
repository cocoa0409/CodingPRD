"""Test helper package for the Termite Bond & WDO Inspection API.

Importing ``api_errors`` here registers the error/HTTP-status map with the
shared validators, so every test file gets automatic status cross-checking
simply by importing from this package.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
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

from . import api_errors  # noqa: F401  (registers the HTTP status map)
from .api_client import ApiClient, api_client
from .api_errors import *  # noqa: F401,F403
from .api_errors import HTTP_STATUS_CODES
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import *  # noqa: F401,F403
from .types import *  # noqa: F401,F403
