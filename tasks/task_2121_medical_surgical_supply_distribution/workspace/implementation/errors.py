"""Error catalogue (PRD section 5 / SCAFFOLD 1.6)."""

ERROR_STATUS = {
    # -- auth -------------------------------------------------------------
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_SUPPLY_ROOM_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # -- schema -----------------------------------------------------------
    "ERR_VALIDATION": 400,
    # -- existence --------------------------------------------------------
    "ERR_SUPPLY_ROOM_NOT_FOUND": 404,
    "ERR_ITEM_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_CONTRACT_LINE_NOT_FOUND": 404,
    "ERR_FORMULARY_ITEM_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ORDER_LINE_NOT_FOUND": 404,
    "ERR_SUBSTITUTION_REQUEST_NOT_FOUND": 404,
    "ERR_RECALL_NOTICE_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_CHARGEBACK_CLAIM_NOT_FOUND": 404,
    # -- concurrency ------------------------------------------------------
    "ERR_STALE_VERSION": 412,
    # -- state ------------------------------------------------------------
    "ERR_ORDER_NOT_DRAFT": 409,
    "ERR_ORDER_STATE_INVALID": 409,
    "ERR_ORDER_LINE_STATE_INVALID": 409,
    "ERR_CONTRACT_TRANSITION_INVALID": 409,
    "ERR_FORMULARY_STATE_INVALID": 409,
    "ERR_LOT_STATE_INVALID": 409,
    "ERR_SUBSTITUTION_STATE_INVALID": 409,
    "ERR_RECALL_STATE_INVALID": 409,
    "ERR_ROUTE_STATE_INVALID": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    # -- uniqueness -------------------------------------------------------
    "ERR_DUPLICATE_ROOM_CODE": 409,
    "ERR_DUPLICATE_SKU": 409,
    "ERR_DUPLICATE_CONTRACT_CODE": 409,
    "ERR_DUPLICATE_ROUTE_CODE": 409,
    "ERR_DUPLICATE_CONTRACT_LINE": 409,
    "ERR_DUPLICATE_FORMULARY_ITEM": 409,
    "ERR_CLAIM_ALREADY_OPEN": 409,
    # -- safety and compliance -------------------------------------------
    "ERR_CONTROLLED_HANDLING_NOT_PERMITTED": 422,
    "ERR_COLD_CHAIN_ROOM_REQUIRED": 422,
    "ERR_LOT_NOT_ALLOCATABLE": 422,
    "ERR_LOT_EXPIRED": 422,
    # -- referential ------------------------------------------------------
    "ERR_ITEM_NOT_ON_FORMULARY": 422,
    "ERR_NO_ACTIVE_CONTRACT_PRICE": 422,
    # -- temporal ---------------------------------------------------------
    "ERR_CONTRACT_PERIOD_OVERLAP": 409,
    "ERR_ROOM_WINDOW_CONFLICT": 409,
    "ERR_STOP_OUTSIDE_ROOM_WINDOW": 422,
    # -- capacity and limits ---------------------------------------------
    "ERR_ROUTE_COLD_CAPACITY_EXCEEDED": 409,
    "ERR_CONTROLLED_QTY_LIMIT_EXCEEDED": 422,
    "ERR_SUBSTITUTION_ROUNDS_EXHAUSTED": 409,
    "ERR_NO_CHARGEBACK_ELIGIBLE_LINES": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be one of the five declared roles.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorised for this endpoint.",
    "ERR_SUPPLY_ROOM_SCOPE_VIOLATION": "A MaterialsManager may only act on resources scoped to its own supply room.",
    "ERR_SEGREGATION_OF_DUTIES": "This operation requires a different acting user than the one recorded on the resource.",
    "ERR_VALIDATION": "The request payload failed schema validation.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def validation_error(message):
    return ApiError("ERR_VALIDATION", message)
