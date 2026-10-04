"""Error types: every error carries the PRD-declared error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def bad_request(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def missing_context(msg="X-User-ID or X-User-Role header missing or role not declared"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def unauthorized_role(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def invalid_state(msg="Entity not in the state required for the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


NOT_FOUND = {
    "merchant": "ERR_MERCHANT_NOT_FOUND",
    "store": "ERR_STORE_NOT_FOUND",
    "policy": "ERR_PRICING_POLICY_NOT_FOUND",
    "quote": "ERR_QUOTE_NOT_FOUND",
    "order": "ERR_DELIVERY_ORDER_NOT_FOUND",
    "courier": "ERR_COURIER_NOT_FOUND",
    "batch": "ERR_BATCH_NOT_FOUND",
    "disposition": "ERR_DISPOSITION_NOT_FOUND",
    "claim": "ERR_CLAIM_NOT_FOUND",
    "report": "ERR_REPORT_NOT_FOUND",
    "credit": "ERR_CREDIT_NOT_FOUND",
}


def not_found(kind):
    return ApiError(NOT_FOUND[kind], 404, "%s id does not exist" % kind)
