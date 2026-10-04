"""Error classes and IDs per the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err(error_id, message):
    status = ERROR_CATALOG[error_id]
    return ApiError(error_id, message, status)


ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE": 409,
    "ERR_BRANCH_OCCUPIED": 409,
    "ERR_BOA_ALREADY_ASSIGNED": 409,
    "ERR_TERRITORY_OVERLAP": 409,
    "ERR_LEASE_OVERLAP": 409,
    "ERR_TERRITORY_CAPACITY": 409,
    "ERR_CONTACT_OUTSIDE_WINDOW": 422,
    "ERR_PRODUCT_NOT_ON_SHELF": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NEGOTIATION_TURN": 409,
    "ERR_ESCROW_INSUFFICIENT": 422,
    "ERR_PERIOD_FINALIZED": 409,
    "ERR_GOAL_NOT_MET": 422,
    "ERR_PERIOD_NOT_LATEST": 409,
    "ERR_PERIOD_NOT_CLOSABLE": 422,
    "ERR_BRANCH_NOT_FULLY_STAFFED": 409,
    "ERR_ADVISOR_NOT_VALIDATED": 409,
    "ERR_TRANSFER_ACTIVE": 409,
}
