"""Error identifiers and HTTP status mapping for the SMR Licensing API.

Every error identifier the PRD's error catalogue (PRD §5) declares, paired
with the HTTP status each one must carry. Registering the mapping with the
shared validators lets ``validate_error`` cross-check the status
automatically, so a test only has to name the identifier it expects.
"""

from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    """Declared error identifiers from the contract's error catalogue."""

    # Authentication and authorization.
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"

    # Existence.
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # State-machine discipline.
    ERR_INVALID_STATE = "ERR_INVALID_STATE"

    # Segregation of duties on RAI acceptance.
    ERR_SELF_ACCEPT_FORBIDDEN = "ERR_SELF_ACCEPT_FORBIDDEN"

    # Domain rules.
    ERR_PROCUREMENT_GATE = "ERR_PROCUREMENT_GATE"
    ERR_AUDIT_OVERLAP = "ERR_AUDIT_OVERLAP"
    ERR_HEARING_IN_PAST = "ERR_HEARING_IN_PAST"
    ERR_HEARING_WINDOW = "ERR_HEARING_WINDOW"
    ERR_OUT_OF_ORDER_RESULT = "ERR_OUT_OF_ORDER_RESULT"
    ERR_SAR_SECTION_UNKNOWN = "ERR_SAR_SECTION_UNKNOWN"
    ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"
    ERR_STALE_VERSION = "ERR_STALE_VERSION"
    ERR_ESCALATION_OUT_OF_RANGE = "ERR_ESCALATION_OUT_OF_RANGE"
    ERR_DUPLICATE = "ERR_DUPLICATE"
    ERR_DCA_NOT_CERTIFIED = "ERR_DCA_NOT_CERTIFIED"
    ERR_VALIDATION = "ERR_VALIDATION"


HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_UNAUTHORIZED: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_SELF_ACCEPT_FORBIDDEN: 403,
    ApiErrorId.ERR_PROCUREMENT_GATE: 422,
    ApiErrorId.ERR_AUDIT_OVERLAP: 409,
    ApiErrorId.ERR_HEARING_IN_PAST: 422,
    ApiErrorId.ERR_HEARING_WINDOW: 422,
    ApiErrorId.ERR_OUT_OF_ORDER_RESULT: 422,
    ApiErrorId.ERR_SAR_SECTION_UNKNOWN: 422,
    ApiErrorId.ERR_CAPACITY_EXCEEDED: 422,
    ApiErrorId.ERR_STALE_VERSION: 412,
    ApiErrorId.ERR_ESCALATION_OUT_OF_RANGE: 422,
    ApiErrorId.ERR_DUPLICATE: 409,
    ApiErrorId.ERR_DCA_NOT_CERTIFIED: 422,
    ApiErrorId.ERR_VALIDATION: 400,
}

# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(HTTP_STATUS_CODES)
