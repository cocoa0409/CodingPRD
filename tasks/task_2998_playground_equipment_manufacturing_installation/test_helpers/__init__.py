"""Shared test infrastructure for the Playground Equipment Manufacturing &
Installation API.

Import everything from this package root:

    from test_helpers import (
        api_client, ApiErrorId, UserRole, TEST_USERS,
        factories as f, fixtures as fx,
        validate_success, validate_error, assert_paginated_list,
    )

The package re-exports the generic runner framework alongside the API-specific
client, payload factories, assertions and composite setup helpers, so a test
module never needs to know which layer a symbol came from.
"""

# --------------------------------------------------------------------------
# Generic framework re-exports
# --------------------------------------------------------------------------
from prd_bench_local_runner.testing import (  # noqa: F401
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

# --------------------------------------------------------------------------
# API-specific layers
# --------------------------------------------------------------------------
from . import assertions  # noqa: F401
from . import constants  # noqa: F401
from . import factories  # noqa: F401
from . import fixtures  # noqa: F401
from . import types  # noqa: F401
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import (  # noqa: F401
    assert_allocation_invariant,
    assert_append_only_fields,
    assert_booked_crew_days,
    assert_cents,
    assert_common_fields,
    assert_component_model,
    assert_date_string,
    assert_empty_data_object,
    assert_freight,
    assert_freshly_created,
    assert_inspection,
    assert_installation_job,
    assert_installer,
    assert_object_envelope,
    assert_order,
    assert_paginated_list,
    assert_placement,
    assert_play_area,
    assert_pledge,
    assert_project,
    assert_quote,
    assert_quote_arithmetic,
    assert_rendering,
    assert_required_surfacing_depth,
    assert_same_instant,
    assert_standard,
    assert_unpaginated_list,
    assert_use_zone,
    assert_use_zone_snapshot_entry,
    assert_version_bumped_by,
    assert_warranty_claim,
    canonical_instant,
    days_between,
    expected_base_attenuation_depth,
    expected_covered_pct,
    expected_required_surfacing_depth,
    instant_for_date,
    separation_cm,
    shift_date,
)
from .constants import (  # noqa: F401
    ALLOCATION,
    CLOCK_DEFAULT_DATE,
    CLOCK_DEFAULT_INSTANT,
    COMMUNITY_REVIEW,
    GEOMETRY,
    INSTALLER,
    JOB,
    PAGINATION,
    QUOTE_PRICING,
    RETROFIT,
    TEST_DEFAULTS,
    WARRANTY,
)
from .factories import drop_fields  # noqa: F401
from .test_users import (  # noqa: F401
    ADMIN_USER_ID,
    AUDITOR_2_USER_ID,
    AUDITOR_USER_ID,
    CLIENT_USER_ID,
    CONSULTANT_2_USER_ID,
    CONSULTANT_USER_ID,
    INSTALLER_FALLBACK_USER_ID,
    OFFICER_2_USER_ID,
    OFFICER_USER_ID,
    TEST_USERS,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_without_role,
    headers_without_user_id,
    make_headers,
    make_installer_operator_headers,
)
from .types import ALL_ROLES, UserRole  # noqa: F401
