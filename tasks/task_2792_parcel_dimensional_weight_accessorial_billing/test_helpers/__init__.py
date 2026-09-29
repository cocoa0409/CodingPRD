"""Barrel export: framework generics plus the parcel-billing test toolkit.

Importing this package also registers the domain error catalogue with the
shared response validators, so ``validate_error`` cross-checks each error_id
against its declared HTTP status without every test repeating it.
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

from . import api_errors as errors  # noqa: F401
from . import factories  # noqa: F401
from . import fixtures  # noqa: F401
from .api_client import ApiClient, ParcelBillingApiClient, api_client  # noqa: F401
from .api_errors import *  # noqa: F401,F403
from .api_errors import ERROR_HTTP_STATUS  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import *  # noqa: F401,F403
from .types import *  # noqa: F401,F403
