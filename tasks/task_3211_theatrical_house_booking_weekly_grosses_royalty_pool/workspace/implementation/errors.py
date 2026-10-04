"""Error classes and HTTP status mapping."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def forbidden(msg="Missing or invalid role headers, or role not authorized"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def not_found(msg="Referenced path resource does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def invalid_request(msg="Missing required field, malformed datetime, or invalid enum value"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def invalid_state(msg="Transition attempted from a state that does not allow it"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def already_terminal(msg="Operation targets a resource in a terminal state"):
    return ApiError("ERR_ALREADY_TERMINAL", msg, 409)


def stale_version(msg="expected_booking_version does not match the booking's current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def window_conflict(msg="Booking window overlaps an approved/active booking or a scheduled capital project window"):
    return ApiError("ERR_BOOKING_WINDOW_CONFLICT", msg, 409)


def size_class_mismatch(msg="Theatre size_class is smaller than Production.required_size_class"):
    return ApiError("ERR_SIZE_CLASS_MISMATCH", msg, 422)


def union_min_crew(msg="Crew size below the union minimum for the theatre size_class"):
    return ApiError("ERR_UNION_MIN_CREW_VIOLATION", msg, 422)


def royalty_points_oob(msg="Royalty point total for the production is outside [1, 100]"):
    return ApiError("ERR_ROYALTY_POINTS_OUT_OF_BOUNDS", msg, 422)


def discount_code_invalid(msg="Discount code is invalid for this order"):
    return ApiError("ERR_DISCOUNT_CODE_INVALID", msg, 422)


def dynamic_factor_oob(msg="dynamic_pricing_factor outside [0.5, 2.0]"):
    return ApiError("ERR_DYNAMIC_FACTOR_OUT_OF_RANGE", msg, 422)


def group_sale_mismatch(msg="Group-sale flag does not match ticket count"):
    return ApiError("ERR_GROUP_SALE_FLAG_MISMATCH", msg, 422)


def stop_clause_not_met(msg="Stop-clause threshold not met or no OPEN notice exists"):
    return ApiError("ERR_STOP_CLAUSE_NOT_MET", msg, 409)


def capital_project_in_use(msg="Cancelling a capital project whose window holds a booking in MAINTENANCE_HOLD"):
    return ApiError("ERR_CAPITAL_PROJECT_IN_USE", msg, 409)


def report_week_duplicate(msg="A weekly gross report already exists for this booking and week_start"):
    return ApiError("ERR_REPORT_WEEK_DUPLICATE", msg, 409)


def fiscal_guard(msg="Fiscal guardrail breached"):
    return ApiError("ERR_FISCAL_GUARD_VIOLATION", msg, 422)
