"""Error types and catalog for the Cookie Program API."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# HTTP status per error id (from the PRD error catalogue).
ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_SEASON_INVALID_STATE": 409,
    "ERR_PRODUCT_CATALOG_EMPTY": 422,
    "ERR_ORDER_INVALID_STATE": 409,
    "ERR_ORDER_EMPTY": 422,
    "ERR_ORDER_WINDOW_CLOSED": 422,
    "ERR_SEASON_NOT_ACCEPTING": 422,
    "ERR_SUPPLY_INSUFFICIENT": 422,
    "ERR_CASE_PACK_VIOLATION": 422,
    "ERR_TRANSFER_INVALID_STATE": 409,
    "ERR_TRANSFER_IN_FLIGHT": 409,
    "ERR_SOD_SAME_TROOP": 422,
    "ERR_REQUEST_INVALID_STATE": 409,
    "ERR_BOOTH_REQUEST_PENDING": 409,
    "ERR_BOOTH_CONFLICT": 409,
    "ERR_BOOTH_CAPACITY_FULL": 422,
    "ERR_HOST_PERMISSION_MISSING": 422,
    "ERR_SEASON_NOT_SELLING": 422,
    "ERR_PAYMENT_INVALID_STATE": 409,
    "ERR_FULFILLMENT_INVALID_STATE": 409,
    "ERR_FULFILLMENT_TYPE_MISMATCH": 422,
    "ERR_UNPAID_DELIVERY": 422,
    "ERR_REFUND_REQUIRED": 422,
    "ERR_ALREADY_DELIVERED": 422,
    "ERR_PO_INVALID_STATE": 409,
    "ERR_OVERDELIVERY": 422,
    "ERR_SITE_CAPACITY_EXCEEDED": 422,
    "ERR_RECALL_INVALID_STATE": 409,
    "ERR_RECALL_DRAFT_OPEN": 409,
    "ERR_RECALLED_PRODUCT": 422,
    "ERR_AGREEMENT_INVALID_STATE": 409,
    "ERR_UNDERPAID": 422,
    "ERR_UNRESOLVED_UNCOLLECTED": 409,
    "ERR_FISCAL_VIOLATION": 422,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_STALE_VERSION": 412,
}


def raise_err(error_id, message):
    raise ApiError(error_id, ERR[error_id], message)
