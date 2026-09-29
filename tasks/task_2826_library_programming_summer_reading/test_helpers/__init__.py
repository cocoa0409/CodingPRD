"""Test infrastructure for the Library Programming & Summer Reading API.

Importing this package registers the error_id to HTTP status mapping with the
runner's validators, so ``validate_error`` cross-checks statuses everywhere.
"""

from . import assertions, constants, factories
from .api_client import (
    LibraryApiClient,
    canonicalize_instant,
    instants_equal,
)
from .api_errors import ERROR_HTTP_STATUS, PATH_NOT_FOUND_BY_ENTITY
from .assertions import (
    assert_all_money_fields_are_integers,
    assert_append_only_fields,
    assert_award_pricing,
    assert_budget_variance_and_posture,
    assert_common_fields,
    assert_contract_fee_breakdown,
    assert_date_equals,
    assert_deferred_award,
    assert_error_payload_is_minimal,
    assert_fresh_contract,
    assert_instant_equals,
    assert_lot_conservation,
    assert_lot_state,
    assert_materials_conservation,
    assert_millisecond_instant,
    assert_money_cents,
    assert_object_envelope,
    assert_one_decimal_pct,
    assert_prize_conservation,
    assert_program_status,
    assert_supply_draw_lines,
    expected_travel_fee_cents,
    round_half_up,
)
from .constants import (
    ACCESSIBLE_SETUP_MINUTES,
    BASE,
    CROSS_BRANCH_SURCHARGE_RATE,
    DAILY_LOG_CAPS,
    DEFAULT_CLOCK_UTC,
    DEFAULT_LIMIT,
    MATERIALS_CONTINGENCY_THRESHOLD_CENTS,
    MAX_LIMIT,
    PROGRAM_FEE_CAP_CENTS,
    ROLE_PROGRAM_COORDINATOR,
    ROLE_PROGRAM_MANAGER,
    ROLE_READER,
    ROLE_SCREENING_OFFICER,
    SCREENING_VALIDITY_DAYS_FINGERPRINT,
    SCREENING_VALIDITY_DAYS_NAME_CHECK,
)
from .fixtures import LibraryWorld
from .test_users import (
    COORDINATOR_HEADERS,
    COORDINATOR_USER_ID,
    EMPTY_ROLE_HEADERS,
    EMPTY_USER_ID_HEADERS,
    MANAGER_HEADERS,
    MANAGER_USER_ID,
    MISSING_ROLE_HEADERS,
    MISSING_USER_ID_HEADERS,
    NO_AUTH_HEADERS,
    SCREENING_OFFICER_HEADERS,
    SCREENING_OFFICER_USER_ID,
    SECOND_COORDINATOR_HEADERS,
    SECOND_COORDINATOR_USER_ID,
    SECOND_MANAGER_HEADERS,
    SECOND_MANAGER_USER_ID,
    UNKNOWN_ROLE_HEADERS,
    make_coordinator_headers,
    make_manager_headers,
    make_reader_headers,
    make_screening_officer_headers,
)
from .types import (
    APPEND_ONLY_FIELD_NAMES,
    COMMON_FIELD_NAMES,
    SUPPLY_DRAW_LINE_FIELDS,
)

__all__ = [
    "LibraryApiClient",
    "LibraryWorld",
    "assertions",
    "constants",
    "factories",
    "canonicalize_instant",
    "instants_equal",
    "ERROR_HTTP_STATUS",
    "PATH_NOT_FOUND_BY_ENTITY",
    "COMMON_FIELD_NAMES",
    "APPEND_ONLY_FIELD_NAMES",
    "SUPPLY_DRAW_LINE_FIELDS",
    "make_reader_headers",
]
