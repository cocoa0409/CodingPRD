"""Error catalog and ApiError exception.

Every error_id and HTTP status comes from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


STATUS = {
    "ERR_INVALID_REQUEST": 400,
    "ERR_MISSING_ROLE": 401,
    "ERR_MISSING_USER_ID": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_OWNERSHIP_MISMATCH": 403,
    "ERR_SELF_DECISION": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_DUPLICATE": 409,
    "ERR_CASE_ALREADY_OPEN": 409,
    "ERR_DIVESTITURE_ALREADY_OPEN": 409,
    "ERR_TRANSFER_ALREADY_OPEN": 409,
    "ERR_NEGOTIATION_ALREADY_OPEN": 409,
    "ERR_ITEM_NOT_TRANSFERABLE": 409,
    "ERR_TARGET_PLANT_NOT_OPERATING": 409,
    "ERR_TSA_NOT_STARTED": 409,
    "ERR_TSA_STILL_ACTIVE": 409,
    "ERR_SELL_THROUGH_OPEN": 409,
    "ERR_NEGOTIATION_EXPIRED": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SAME_PLANT": 422,
    "ERR_SOURCE_PLANT_MISMATCH": 422,
    "ERR_NOT_COMBINED": 422,
    "ERR_BRAND_NOT_NEGOTIABLE": 422,
    "ERR_BRAND_CORE": 422,
    "ERR_CLOSE_DATE_OUTSIDE_TSA": 422,
    "ERR_INVALID_RUN": 422,
    "ERR_CYCLE_WINDOW_OVERLAP": 422,
    "ERR_NEGOTIATION_WINDOW_OVERLAP": 422,
    "ERR_PLANT_OVER_CAPACITY": 422,
    "ERR_INSUFFICIENT_UNITS": 422,
    "ERR_CAPITAL_REQUEST_TOO_LARGE": 422,
}


def fail(error_id, message):
    """Raise an ApiError with the catalog HTTP status for error_id."""
    raise ApiError(error_id, STATUS[error_id], message)
