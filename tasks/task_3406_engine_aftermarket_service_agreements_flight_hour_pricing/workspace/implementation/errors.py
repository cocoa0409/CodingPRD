"""Error catalog and API exception type. Error IDs and HTTP statuses are taken
verbatim from SCAFFOLD.yaml section 1.6 / PRD section 5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_OPERATOR_NOT_FOUND": 404,
    "ERR_ENGINE_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_SHOP_VISIT_NOT_FOUND": 404,
    "ERR_WORKSCOPE_NOT_FOUND": 404,
    "ERR_REQUISITION_NOT_FOUND": 404,
    "ERR_SPARE_ENGINE_NOT_FOUND": 404,
    "ERR_LEASE_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_WINDOW": 422,
    "ERR_FUTURE_PERIOD": 422,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_DUPLICATE_REPORT": 409,
    "ERR_DUPLICATE_STATEMENT": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_AGREEMENT_NOT_IN_RENEGOTIATION": 409,
    "ERR_ENGINE_NOT_ENROLLED": 409,
    "ERR_ENGINE_ALREADY_ENROLLED": 409,
    "ERR_ENGINE_IN_SHOP": 409,
    "ERR_VISIT_NOT_INDUCTED": 409,
    "ERR_NO_APPROVED_WORKSCOPE": 409,
    "ERR_WORKSCOPE_NOT_SUBMITTED": 409,
    "ERR_WORKSCOPE_NOT_APPROVED": 409,
    "ERR_ACTIVE_WORKSCOPE_EXISTS": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_MANDATORY_DIRECTIVE_OPEN": 409,
    "ERR_LEASE_WINDOW_OVERLAP": 409,
    "ERR_LEASE_NOT_IN_WINDOW": 409,
    "ERR_SHOP_CAPACITY_EXCEEDED": 409,
    "ERR_OPEN_REQUISITIONS": 409,
    "ERR_MODEL_MISMATCH": 422,
    "ERR_NO_ELIGIBLE_SOURCING_CLASS": 409,
    "ERR_WORKSCOPE_COST_CAP_EXCEEDED": 422,
    "ERR_INSUFFICIENT_LIFE_RESTORATION": 422,
}


def api_err(error_id, message):
    """Build an ApiError using the catalogued HTTP status for the error id."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
