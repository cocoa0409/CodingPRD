"""Test infrastructure for the Craft Brewery Taproom & Self-Distribution API.

Importing this package registers the error-to-HTTP-status map from PRD §5 with
the shared envelope validators, so ``validate_error`` cross-checks statuses
without any per-test setup.
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

from . import api_errors, constants, factories, fixtures, test_users  # noqa: F401
from .api_client import ApiClient  # noqa: F401
from .api_errors import *  # noqa: F401,F403
from .assertions import (  # noqa: F401
    BBL_TOL,
    OZ_TOL,
    assert_allocation_lines,
    assert_batch_conserved,
    assert_bbl,
    assert_cents,
    assert_common_fields,
    assert_decimal_places,
    assert_instant_equals,
    assert_ledger_conserved,
    assert_no_prefix_uuid,
    assert_oz,
    assert_pagination_meta,
    assert_pour_shape,
    canonical_instant,
    gal_to_oz,
    oz_to_bbl,
)
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN,
    ADMIN_2,
    CELLAR,
    CELLAR_2,
    COMPLIANCE,
    COMPLIANCE_2,
    HEADERS_BY_ROLE,
    REGULATOR,
    REGULATOR_2,
    TAPROOM,
    TAPROOM_2,
    TEST_USERS,
    USER_ADMIN_1,
    USER_ADMIN_2,
    USER_CELLAR_1,
    USER_CELLAR_2,
    USER_COMPLIANCE_1,
    USER_COMPLIANCE_2,
    USER_REGULATOR_1,
    USER_REGULATOR_2,
    USER_TAPROOM_1,
    USER_TAPROOM_2,
    headers_blank_role,
    headers_blank_user_id,
    headers_for,
    headers_missing_role,
    headers_missing_user_id,
    headers_none,
    headers_unknown_role,
    other_roles,
)
from .types import (  # noqa: F401
    AllocationLine,
    Batch,
    Beer,
    Brewery,
    DistributionOrder,
    DistributorAppointment,
    EventPermit,
    ExciseReport,
    KegAsset,
    PackagingRun,
    StateLicense,
    TaproomPour,
    Tank,
)
