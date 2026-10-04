"""API error type carrying the PRD error catalog identifiers."""


class ApiError(Exception):
    def __init__(self, status, error_id, message=""):
        super().__init__(message or error_id)
        self.status = status
        self.error_id = error_id
        self.message = message or error_id


# Error catalog (id -> http status), from PRD section 5.
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_STALE_ORDER_VERSION": 412,
    "ERR_STALE_INVENTORY_VERSION": 412,
    "ERR_ORDER_FROZEN": 409,
    "ERR_ORDER_RESTRICTED": 409,
    "ERR_CHEMISTRY_OUT_OF_SPEC": 422,
    "ERR_EMISSIONS_PERMIT_BREACH": 409,
    "ERR_FOOD_SAFETY_INCOMPLETE": 422,
    "ERR_CURE_PROFILE_VIOLATION": 422,
    "ERR_FURNACE_WINDOW_OVERLAP": 409,
    "ERR_OVEN_CAPACITY_EXCEEDED": 409,
    "ERR_CRITICAL_DEFECT_MUST_SCRAP": 422,
    "ERR_REWORK_LIMIT_EXCEEDED": 422,
    "ERR_USE_AS_IS_MINOR_ONLY": 422,
    "ERR_TOLERANCE_EXCEEDED": 422,
    "ERR_SAND_MIX_VIOLATION": 422,
    "ERR_SAND_LOSS_EXCEEDED": 422,
    "ERR_MOLD_ORDER_MISMATCH": 422,
    "ERR_UNITS_NOT_SAME_ORDER": 422,
    "ERR_SHIP_WEEK_INVALID": 422,
    "ERR_ALLOCATION_FROZEN": 409,
    "ERR_PRODUCT_DISCONTINUED": 422,
    "ERR_PRICE_BELOW_BRAND_FLOOR": 422,
    "ERR_OUTLET_PRICE_BELOW_FLOOR": 422,
    "ERR_INSUFFICIENT_INVENTORY": 422,
    "ERR_INSUFFICIENT_IRON": 422,
    "ERR_YIELD_BELOW_MINIMUM": 422,
}


def err(error_id, message=""):
    return ApiError(ERRORS[error_id], error_id, message or error_id)
