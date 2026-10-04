"""Error identifiers and their HTTP status codes (PRD §5).

Every rejection in this API carries one of the identifiers below in the
``error_id`` field of the standard error envelope, with the HTTP status shown
alongside it.  The trigger conditions live in the PRD prose, not in this table.

Registering the mapping with the framework lets ``validate_error()`` cross-check
the HTTP status automatically, so callers only need to name the expected
``error_id``.
"""

from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    """Every ``error_id`` the API can return."""

    # Authentication / authorization
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_SELF_APPROVAL_FORBIDDEN = "ERR_SELF_APPROVAL_FORBIDDEN"

    # Existence
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_COMPONENT_NOT_FOUND = "ERR_COMPONENT_NOT_FOUND"

    # State and concurrency
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"
    ERR_STALE_VERSION = "ERR_STALE_VERSION"

    # Regulatory and temporal
    ERR_REGULATORY_LIFE_EXCEEDED = "ERR_REGULATORY_LIFE_EXCEEDED"
    ERR_RETROFIT_DEADLINE_PASSED = "ERR_RETROFIT_DEADLINE_PASSED"
    ERR_SHOP_SLOT_OVERLAP = "ERR_SHOP_SLOT_OVERLAP"
    ERR_ASSIGNMENT_OVERLAP = "ERR_ASSIGNMENT_OVERLAP"
    ERR_CHANGEOVER_CONFLICT = "ERR_CHANGEOVER_CONFLICT"

    # Sourcing and prerequisites
    ERR_COMPONENT_SHORTAGE = "ERR_COMPONENT_SHORTAGE"
    ERR_LEAD_TIME_INFEASIBLE = "ERR_LEAD_TIME_INFEASIBLE"
    ERR_MATERIAL_ENDORSEMENT_PENDING = "ERR_MATERIAL_ENDORSEMENT_PENDING"
    ERR_ENDORSEMENT_RETRY_EXHAUSTED = "ERR_ENDORSEMENT_RETRY_EXHAUSTED"
    ERR_PREREQUISITE_NOT_MET = "ERR_PREREQUISITE_NOT_MET"
    ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"

    # Shape and uniqueness
    ERR_DUPLICATE_ROW = "ERR_DUPLICATE_ROW"
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"

    # Fiscal
    ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"
    ERR_FLEET_CAP_EXCEEDED = "ERR_FLEET_CAP_EXCEEDED"
    ERR_SETTLEMENT_UNBALANCED = "ERR_SETTLEMENT_UNBALANCED"

    # Referential / availability
    ERR_CAR_NOT_HELD = "ERR_CAR_NOT_HELD"
    ERR_LESSEE_MISMATCH = "ERR_LESSEE_MISMATCH"
    ERR_UNSETTLED_RETURNS = "ERR_UNSETTLED_RETURNS"


HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_COMPONENT_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_ALREADY_TERMINAL: 409,
    ApiErrorId.ERR_STALE_VERSION: 412,
    ApiErrorId.ERR_REGULATORY_LIFE_EXCEEDED: 422,
    ApiErrorId.ERR_RETROFIT_DEADLINE_PASSED: 422,
    ApiErrorId.ERR_SHOP_SLOT_OVERLAP: 409,
    ApiErrorId.ERR_ASSIGNMENT_OVERLAP: 409,
    ApiErrorId.ERR_CHANGEOVER_CONFLICT: 409,
    ApiErrorId.ERR_COMPONENT_SHORTAGE: 409,
    ApiErrorId.ERR_LEAD_TIME_INFEASIBLE: 422,
    ApiErrorId.ERR_MATERIAL_ENDORSEMENT_PENDING: 409,
    ApiErrorId.ERR_ENDORSEMENT_RETRY_EXHAUSTED: 409,
    ApiErrorId.ERR_PREREQUISITE_NOT_MET: 409,
    ApiErrorId.ERR_DUPLICATE_ROW: 409,
    ApiErrorId.ERR_INVALID_REQUEST: 400,
    ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED: 402,
    ApiErrorId.ERR_FLEET_CAP_EXCEEDED: 402,
    ApiErrorId.ERR_SETTLEMENT_UNBALANCED: 409,
    ApiErrorId.ERR_CAR_NOT_HELD: 409,
    ApiErrorId.ERR_LESSEE_MISMATCH: 409,
    ApiErrorId.ERR_UNSETTLED_RETURNS: 409,
    ApiErrorId.ERR_CAPACITY_EXCEEDED: 409,
}

# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(HTTP_STATUS_CODES)


def http_status_for(error_id) -> int:
    """Return the catalogued HTTP status for an ``error_id``.

    Accepts either an ``ApiErrorId`` member or the plain wire string.
    """
    return HTTP_STATUS_CODES[error_id]
