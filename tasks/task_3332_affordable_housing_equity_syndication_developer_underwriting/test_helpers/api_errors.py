"""Error catalog: every ``error_id`` and its HTTP status (PRD §5).

The mapping is registered with the framework at import time, so
``validate_error(response, ApiErrorId.ERR_X)`` cross-checks the HTTP status
code automatically — no test needs to pass ``expected_status`` explicitly.

Keys of :data:`HTTP_STATUS_CODES` are plain strings so that a lookup with an
``error_id`` read out of a response body always hits.
"""

from enum import Enum
from typing import Dict, List

from prd_bench_local_runner.testing.validators import set_error_http_status_map

__all__ = [
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "ERROR_HTTP_STATUS",
    "ALL_ERROR_IDS",
    "error_status",
    "is_error_id",
]


class ApiErrorId(str, Enum):
    """Every error identifier the API can return."""

    # --- Authentication / authorization ---------------------------------
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_FORBIDDEN_SCOPE = "ERR_FORBIDDEN_SCOPE"

    # --- Request shape ---------------------------------------------------
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
    ERR_EXIT_WINDOW_INVERTED = "ERR_EXIT_WINDOW_INVERTED"

    # --- Not found (one per addressable segment) -------------------------
    ERR_DEVELOPER_NOT_FOUND = "ERR_DEVELOPER_NOT_FOUND"
    ERR_FUND_NOT_FOUND = "ERR_FUND_NOT_FOUND"
    ERR_PROJECT_NOT_FOUND = "ERR_PROJECT_NOT_FOUND"
    ERR_ALLOCATION_NOT_FOUND = "ERR_ALLOCATION_NOT_FOUND"
    ERR_CAPITAL_CALL_NOT_FOUND = "ERR_CAPITAL_CALL_NOT_FOUND"
    ERR_GUARANTEE_NOT_FOUND = "ERR_GUARANTEE_NOT_FOUND"
    ERR_SUBSCRIPTION_NOT_FOUND = "ERR_SUBSCRIPTION_NOT_FOUND"
    ERR_REVIEW_NOT_FOUND = "ERR_REVIEW_NOT_FOUND"
    ERR_EXIT_EVENT_NOT_FOUND = "ERR_EXIT_EVENT_NOT_FOUND"

    # --- Target state ----------------------------------------------------
    ERR_PROJECT_NOT_COMMITTABLE = "ERR_PROJECT_NOT_COMMITTABLE"
    ERR_INVALID_ALLOCATION_STATE = "ERR_INVALID_ALLOCATION_STATE"
    ERR_CALL_NOT_ISSUED = "ERR_CALL_NOT_ISSUED"
    ERR_REVIEW_NOT_ESCALATED = "ERR_REVIEW_NOT_ESCALATED"
    ERR_EXIT_EVENT_NOT_PENDING = "ERR_EXIT_EVENT_NOT_PENDING"
    ERR_SUBSCRIPTION_TERMINAL = "ERR_SUBSCRIPTION_TERMINAL"

    # --- Sponsor and guarantee safeguards --------------------------------
    ERR_DEVELOPER_WATCH_BLOCKED = "ERR_DEVELOPER_WATCH_BLOCKED"
    ERR_GUARANTEE_EXPOSURE_EXCEEDED = "ERR_GUARANTEE_EXPOSURE_EXCEEDED"
    ERR_DEVELOPER_NOT_ELIGIBLE_FOR_EXIT = "ERR_DEVELOPER_NOT_ELIGIBLE_FOR_EXIT"

    # --- Revision bands and conflicts ------------------------------------
    ERR_STALE_VERSION = "ERR_STALE_VERSION"
    ERR_DUPLICATE_CALL_MILESTONE = "ERR_DUPLICATE_CALL_MILESTONE"
    ERR_CALL_BUFFER_TOO_SHORT = "ERR_CALL_BUFFER_TOO_SHORT"
    ERR_DUPLICATE_SUBSCRIPTION = "ERR_DUPLICATE_SUBSCRIPTION"
    ERR_DUPLICATE_ALLOCATION_PERIOD = "ERR_DUPLICATE_ALLOCATION_PERIOD"
    ERR_ROFR_WINDOW_OVERLAP = "ERR_ROFR_WINDOW_OVERLAP"
    ERR_COVERAGE_WINDOW_OVERLAP = "ERR_COVERAGE_WINDOW_OVERLAP"
    ERR_INVESTOR_SUSPENDED = "ERR_INVESTOR_SUSPENDED"
    ERR_FUND_POSTURE_FROZEN = "ERR_FUND_POSTURE_FROZEN"
    ERR_FUND_NOT_FORMING = "ERR_FUND_NOT_FORMING"
    ERR_DUPLICATE_REVIEW_PERIOD = "ERR_DUPLICATE_REVIEW_PERIOD"
    ERR_EXIT_NOT_ELIGIBLE = "ERR_EXIT_NOT_ELIGIBLE"

    # --- Equity buckets ---------------------------------------------------
    ERR_SUBSCRIPTION_EXCEEDS_CAPACITY = "ERR_SUBSCRIPTION_EXCEEDS_CAPACITY"
    ERR_OVERPAYMENT = "ERR_OVERPAYMENT"
    ERR_DISTRIBUTION_EXCEEDS_DELIVERED = "ERR_DISTRIBUTION_EXCEEDS_DELIVERED"

    # --- Temporal windows -------------------------------------------------
    ERR_SUBSCRIPTION_WINDOW_CLOSED = "ERR_SUBSCRIPTION_WINDOW_CLOSED"
    ERR_CALL_NOT_DUE = "ERR_CALL_NOT_DUE"
    ERR_REVIEW_PERIOD_OPEN = "ERR_REVIEW_PERIOD_OPEN"
    ERR_ROFR_WINDOW_EXPIRED = "ERR_ROFR_WINDOW_EXPIRED"
    ERR_PLACED_IN_SERVICE_DEADLINE_PASSED = "ERR_PLACED_IN_SERVICE_DEADLINE_PASSED"


#: error_id (string) -> HTTP status code.
HTTP_STATUS_CODES: Dict[str, int] = {
    ApiErrorId.ERR_UNAUTHENTICATED.value: 401,
    ApiErrorId.ERR_FORBIDDEN.value: 403,
    ApiErrorId.ERR_FORBIDDEN_SCOPE.value: 403,
    ApiErrorId.ERR_INVALID_REQUEST.value: 400,
    ApiErrorId.ERR_EXIT_WINDOW_INVERTED.value: 400,
    ApiErrorId.ERR_DEVELOPER_NOT_FOUND.value: 404,
    ApiErrorId.ERR_FUND_NOT_FOUND.value: 404,
    ApiErrorId.ERR_PROJECT_NOT_FOUND.value: 404,
    ApiErrorId.ERR_ALLOCATION_NOT_FOUND.value: 404,
    ApiErrorId.ERR_CAPITAL_CALL_NOT_FOUND.value: 404,
    ApiErrorId.ERR_GUARANTEE_NOT_FOUND.value: 404,
    ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND.value: 404,
    ApiErrorId.ERR_REVIEW_NOT_FOUND.value: 404,
    ApiErrorId.ERR_EXIT_EVENT_NOT_FOUND.value: 404,
    ApiErrorId.ERR_PROJECT_NOT_COMMITTABLE.value: 409,
    ApiErrorId.ERR_INVALID_ALLOCATION_STATE.value: 409,
    ApiErrorId.ERR_CALL_NOT_ISSUED.value: 409,
    ApiErrorId.ERR_REVIEW_NOT_ESCALATED.value: 409,
    ApiErrorId.ERR_EXIT_EVENT_NOT_PENDING.value: 409,
    ApiErrorId.ERR_SUBSCRIPTION_TERMINAL.value: 409,
    ApiErrorId.ERR_DEVELOPER_WATCH_BLOCKED.value: 422,
    ApiErrorId.ERR_GUARANTEE_EXPOSURE_EXCEEDED.value: 422,
    ApiErrorId.ERR_DEVELOPER_NOT_ELIGIBLE_FOR_EXIT.value: 422,
    ApiErrorId.ERR_STALE_VERSION.value: 412,
    ApiErrorId.ERR_DUPLICATE_CALL_MILESTONE.value: 409,
    ApiErrorId.ERR_CALL_BUFFER_TOO_SHORT.value: 409,
    ApiErrorId.ERR_DUPLICATE_SUBSCRIPTION.value: 409,
    ApiErrorId.ERR_DUPLICATE_ALLOCATION_PERIOD.value: 409,
    ApiErrorId.ERR_ROFR_WINDOW_OVERLAP.value: 409,
    ApiErrorId.ERR_COVERAGE_WINDOW_OVERLAP.value: 409,
    ApiErrorId.ERR_INVESTOR_SUSPENDED.value: 403,
    ApiErrorId.ERR_FUND_POSTURE_FROZEN.value: 409,
    ApiErrorId.ERR_FUND_NOT_FORMING.value: 409,
    ApiErrorId.ERR_DUPLICATE_REVIEW_PERIOD.value: 409,
    ApiErrorId.ERR_EXIT_NOT_ELIGIBLE.value: 409,
    ApiErrorId.ERR_SUBSCRIPTION_EXCEEDS_CAPACITY.value: 422,
    ApiErrorId.ERR_OVERPAYMENT.value: 422,
    ApiErrorId.ERR_DISTRIBUTION_EXCEEDS_DELIVERED.value: 422,
    ApiErrorId.ERR_SUBSCRIPTION_WINDOW_CLOSED.value: 422,
    ApiErrorId.ERR_CALL_NOT_DUE.value: 422,
    ApiErrorId.ERR_REVIEW_PERIOD_OPEN.value: 422,
    ApiErrorId.ERR_ROFR_WINDOW_EXPIRED.value: 422,
    ApiErrorId.ERR_PLACED_IN_SERVICE_DEADLINE_PASSED.value: 422,
}

#: Alias kept for readability at call sites.
ERROR_HTTP_STATUS = HTTP_STATUS_CODES

#: Every declared error id, as plain strings.
ALL_ERROR_IDS: List[str] = [member.value for member in ApiErrorId]


# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(HTTP_STATUS_CODES)


def error_status(error_id) -> int:
    """Return the declared HTTP status for ``error_id``.

    Accepts an :class:`ApiErrorId` member or a plain string. Raises ``KeyError``
    for an undeclared error id, which is itself a useful check that a test is
    asserting a real catalog entry.
    """
    key = error_id.value if isinstance(error_id, ApiErrorId) else str(error_id)
    return HTTP_STATUS_CODES[key]


def is_error_id(value) -> bool:
    """True when ``value`` names a declared error id."""
    key = value.value if isinstance(value, ApiErrorId) else value
    return isinstance(key, str) and key in HTTP_STATUS_CODES
