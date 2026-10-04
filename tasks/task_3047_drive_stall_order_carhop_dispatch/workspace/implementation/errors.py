"""Error classes and error ID constants (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


HTTP_BY_ERROR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_STALL_OCCUPIED": 409,
    "ERR_STALL_NOT_OCCUPIED_BY_ORDER": 409,
    "ERR_INTERCOM_UNAVAILABLE": 409,
    "ERR_FAULT_STILL_OPEN": 409,
    "ERR_LANE_CLOSED": 409,
    "ERR_STALL_WEATHER_CLOSED": 409,
    "ERR_APP_ONLY": 409,
    "ERR_MENU_ITEM_RETIRED": 409,
    "ERR_SIZE_REQUIRED": 422,
    "ERR_OPTION_INVALID": 422,
    "ERR_EMPTY_ORDER": 409,
    "ERR_NO_SERVICE_TARGET": 409,
    "ERR_OFFER_NOT_APPLICABLE": 409,
    "ERR_PAYMENT_NOT_CAPTURED": 409,
    "ERR_PAYMENT_CAPTURED_REQUIRES_REFUND": 409,
    "ERR_WALLET_NEGATIVE": 409,
    "ERR_KITCHEN_SATURATED": 409,
    "ERR_EMPTY_RUN": 409,
    "ERR_NO_CARHOP_ELIGIBLE": 409,
    "ERR_NOT_ASSIGNED_CARHOP": 409,
    "ERR_RUN_SEQUENCE_VIOLATION": 409,
}


def raise_error(error_id, message):
    raise ApiError(error_id, HTTP_BY_ERROR[error_id], message)


def not_found(message="Resource not found"):
    raise_error("ERR_NOT_FOUND", message)


def invalid_request(message="Malformed input"):
    raise_error("ERR_INVALID_REQUEST", message)


def invalid_state(message="Entity not in a valid from-state for the requested transition"):
    raise_error("ERR_INVALID_STATE", message)
