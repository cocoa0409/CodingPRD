"""Barrel export: framework generics plus PRD-specific infrastructure."""

# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
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
from . import factories  # noqa: F401
from .api_client import ApiClient, api_client, canonical_instant, same_instant
from .api_errors import (  # noqa: F401
    ERR_BAY_SLOT_CONFLICT,
    ERR_CALIBRATION_SIGNOFF_REQUIRED,
    ERR_CAPACITY_EXCEEDED,
    ERR_CROSS_TERRITORY,
    ERR_CURB_ACCESS_DENIED,
    ERR_DUPLICATE_RESOURCE,
    ERR_EXCLUSION_ZONE_ACTIVE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LOCATION_INVALID,
    ERR_MAX_ATTEMPTS_NOT_REACHED,
    ERR_NOT_FOUND,
    ERR_NO_TEAM_AVAILABLE,
    ERR_NO_VEHICLE_AVAILABLE,
    ERR_POSTURE_LOCKDOWN,
    ERR_RESPONSE_SLA_BREACHED,
    ERR_ROUTE_NOT_ALLOWED,
    ERR_SESSION_TERMINAL,
    ERR_STALE_VERSION,
    ERR_TEAM_CAPACITY_EXCEEDED,
    ERR_TERRITORY_NOT_ACTIVE,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_VEHICLE_HAS_ACTIVE_CYCLE,
    ERR_VEHICLE_IN_CYCLE,
    ERR_VEHICLE_NOT_SERVICE_READY,
    ERR_VEHICLE_ROADSIDE_BLOCKED,
    ERR_WEATHER_SUSPENDED,
    ERR_ZONE_BLOCKED_WAVE,
    ApiErrorId,
    HTTP_STATUS_CODES,
)
from .constants import *  # noqa: F401,F403
from .types import *  # noqa: F401,F403
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .test_users import (
    ASSIST,
    ASSIST_2,
    DEPOT,
    FLEET,
    MALFORMED_ROLE_HEADERS,
    MAPPING,
    MISSING_ID_HEADERS,
    MISSING_ROLE_HEADERS,
    NO_HEADERS,
    PLANNER,
    SAFETY,
    TEST_USERS,
    headers_for,
)
from .fixtures import *  # noqa: F401,F403
from .fixtures import api, client  # noqa: F401