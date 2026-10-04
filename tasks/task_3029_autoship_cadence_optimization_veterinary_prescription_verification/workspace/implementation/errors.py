"""Error identifiers, HTTP statuses and the API exception type.

Every error_id and status below is transcribed verbatim from the task scaffold
(SS1.6 Error Code Catalog) and PRD SS5.
"""


class ApiError(Exception):
    """Carries an error_id (scaffold/PRD catalogue) plus its HTTP status."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status

    def to_body(self):
        return {"error_id": self.error_id, "message": self.message}


# --- error id -> http status, transcribed from SCAFFOLD.yaml SS1.6 / PRD SS5 ---
ERROR_STATUS = {
    "ERR_MISSING_USER_CONTEXT": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_CADENCE": 400,
    "ERR_STALE_PLAN_VERSION": 412,
    "ERR_STALE_ITEM_VERSION": 412,
    "ERR_PLAN_PAUSED": 409,
    "ERR_PET_INACTIVE": 409,
    "ERR_RX_NOT_VERIFIED": 422,
    "ERR_RX_EXPIRED": 422,
    "ERR_REFILL_LIMIT_EXCEEDED": 422,
    "ERR_RX_QUANTITY_LIMIT_EXCEEDED": 422,
    "ERR_PRESCRIBER_NOT_FOUND": 422,
    "ERR_PRESCRIBER_MISMATCH": 422,
    "ERR_PRESCRIBER_NOT_VERIFIED": 422,
    "ERR_CSR_AUTH_BLOCKED": 422,
    "ERR_SITE_NOT_LICENSED": 422,
    "ERR_SITE_RESTRICTED": 409,
    "ERR_COLD_PACK_CAPACITY_EXCEEDED": 422,
    "ERR_TEMPERATURE_CHAIN_RISK": 422,
    "ERR_CADENCE_WINDOW_OVERLAP": 409,
    "ERR_PRICE_PROTECTION_CONFLICT": 422,
    "ERR_PROMO_STACKING_NOT_ALLOWED": 422,
    "ERR_ORDER_ALREADY_SHIPPED": 409,
    "ERR_SUBMITTER_CANNOT_AUTHORIZE": 403,
    "ERR_NO_ELIGIBLE_SITE": 409,
}


def fail(error_id, message):
    """Raise an ApiError using the catalogue status for that error_id."""
    raise ApiError(error_id, message, ERROR_STATUS.get(error_id, 400))