"""Error classes and error ID constants (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(msg="Missing or invalid auth headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Role not permitted or identity mismatch"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def validation(msg="Malformed request"):
    return ApiError("ERR_VALIDATION", 400, msg)


def invalid_state(msg="Transition not defined from current state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def parent_not_active(msg="Parent lifecycle gate failed"):
    return ApiError("ERR_PARENT_NOT_ACTIVE", 409, msg)


def stale_allocation_version(msg="Stale DealerAllocation version"):
    return ApiError("ERR_STALE_ALLOCATION_VERSION", 412, msg)


def stale_run_version(msg="Stale AllocationRun version"):
    return ApiError("ERR_STALE_RUN_VERSION", 412, msg)


def invalid_configuration(msg="Invalid order configuration"):
    return ApiError("ERR_INVALID_CONFIGURATION", 422, msg)


def commodity_cap_exceeded(msg="Commodity install-rate cap exceeded"):
    return ApiError("ERR_COMMODITY_CAP_EXCEEDED", 422, msg)


def allocation_exhausted(msg="Allocation pool exhausted"):
    return ApiError("ERR_ALLOCATION_EXHAUSTED", 422, msg)


def trade_exceeds_pool(msg="Trade exceeds from-dealer remaining pool"):
    return ApiError("ERR_TRADE_EXCEEDS_POOL", 422, msg)


def trade_invalid(msg="Invalid trade (cross-region, self-trade, or units < 1)"):
    return ApiError("ERR_TRADE_INVALID", 422, msg)


def trade_expired(msg="Trade action at or after expires_at"):
    return ApiError("ERR_TRADE_EXPIRED", 422, msg)


def window_closed(msg="Temporal window violated"):
    return ApiError("ERR_WINDOW_CLOSED", 422, msg)


def pickup_before_build_week(msg="pickup_week earlier than scheduled_week"):
    return ApiError("ERR_PICKUP_BEFORE_BUILD_WEEK", 422, msg)


def restriction_overlap(msg="Restriction window overlap"):
    return ApiError("ERR_RESTRICTION_OVERLAP", 422, msg)


def retrofit_blocked(msg="Retrofit blocked while restriction is ACTIVE"):
    return ApiError("ERR_RETROFIT_BLOCKED", 409, msg)


def appeal_ineligible(msg="Appeal eligibility check failed"):
    return ApiError("ERR_APPEAL_INELIGIBLE", 422, msg)


def appeals_open(msg="Open appeals block run lock"):
    return ApiError("ERR_APPEALS_OPEN", 409, msg)


def children_not_locked(msg="Some DealerAllocation children are still OPEN"):
    return ApiError("ERR_CHILDREN_NOT_LOCKED", 409, msg)


def duplicate(msg="Uniqueness violation"):
    return ApiError("ERR_DUPLICATE", 409, msg)


def carrier_capacity(msg="Carrier at weekly capacity"):
    return ApiError("ERR_CARRIER_CAPACITY", 422, msg)


def run_period_conflict(msg="A run for this line is already PUBLISHED"):
    return ApiError("ERR_RUN_PERIOD_CONFLICT", 409, msg)


def partial_build_not_allowed(msg="Partial build not allowed by restriction"):
    return ApiError("ERR_PARTIAL_BUILD_NOT_ALLOWED", 422, msg)


def program_closed(msg="Program outside its window or already CLOSED"):
    return ApiError("ERR_PROGRAM_CLOSED", 409, msg)
