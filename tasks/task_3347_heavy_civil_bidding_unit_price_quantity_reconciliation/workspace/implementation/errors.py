"""Error catalog for the Heavy Civil Bidding API.

Every identifier below is copied verbatim from the PRD's error catalogue
(section 5) together with its HTTP status code.
"""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status=None):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_BID_ITEM_NOT_FOUND": 404,
    "ERR_SURETY_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_BOND_NOT_FOUND": 404,
    "ERR_MEASUREMENT_NOT_FOUND": 404,
    "ERR_RECONCILIATION_NOT_FOUND": 404,
    "ERR_CONDITION_NOT_FOUND": 404,
    "ERR_DETERMINATION_NOT_FOUND": 404,
    "ERR_COMMITMENT_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_RECONCILIATION_ALREADY_OPEN": 409,
    "ERR_RESERVATION_OVERLAP": 409,
    "ERR_DUPLICATE_PROJECT_CODE": 409,
    "ERR_DUPLICATE_ITEM_CODE": 409,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_STALE_BID_ITEM_VERSION": 412,
    "ERR_ITEM_NOT_ACTIVE": 409,
    "ERR_SURETY_SUSPENDED": 422,
    "ERR_BID_SHOPPING_RESTRICTED": 422,
    "ERR_BID_WINDOW_CLOSED": 422,
    "ERR_BID_NOT_YET_CLOSED": 422,
    "ERR_QUOTE_AFTER_DEADLINE": 422,
    "ERR_CLAIM_WINDOW_CLOSED": 422,
    "ERR_NOTICE_PERIOD_EXPIRED": 422,
    "ERR_DOCUMENTATION_INCOMPLETE": 422,
    "ERR_CLAIM_AMOUNT_REQUIRED": 422,
    "ERR_CLAIM_NOT_UNDER_REVIEW": 422,
    "ERR_RATE_BELOW_COST": 422,
    "ERR_UNIT_PRICE_REQUIRED": 422,
    "ERR_BOND_AMOUNT_INSUFFICIENT": 422,
    "ERR_NO_LIEN_CLAIM": 422,
    "ERR_AGGREGATE_CAPACITY_EXCEEDED": 422,
    "ERR_DBE_GOOD_FAITH_MISSING": 422,
    "ERR_QUANTITY_RENEGOTIATION_REQUIRED": 422,
    "ERR_OPEN_CLAIM_BLOCKS_CLOSEOUT": 422,
    "ERR_MEASUREMENTS_PENDING": 422,
    "ERR_RETENTION_NOT_RELEASABLE": 422,
}


def invalid_request(message="The request body is not well formed."):
    return ApiError("ERR_INVALID_REQUEST", message, 400)


def not_found(error_id, message):
    return ApiError(error_id, message, 404)


def invalid_state(message):
    return ApiError("ERR_INVALID_STATE", message, 409)
