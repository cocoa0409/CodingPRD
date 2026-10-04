"""Error classes and error ID constants, per PRD section 5."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = ("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_STORE_NOT_FOUND = ("ERR_STORE_NOT_FOUND", 404)
ERR_ORDER_NOT_FOUND = ("ERR_ORDER_NOT_FOUND", 404)
ERR_MENU_ITEM_NOT_FOUND = ("ERR_MENU_ITEM_NOT_FOUND", 404)
ERR_BATCH_NOT_FOUND = ("ERR_BATCH_NOT_FOUND", 404)
ERR_DEPLOYMENT_NOT_FOUND = ("ERR_DEPLOYMENT_NOT_FOUND", 404)
ERR_SUPPRESSION_EVENT_NOT_FOUND = ("ERR_SUPPRESSION_EVENT_NOT_FOUND", 404)
ERR_CHANNEL_NOT_FOUND = ("ERR_CHANNEL_NOT_FOUND", 404)
ERR_INGREDIENT_NOT_FOUND = ("ERR_INGREDIENT_NOT_FOUND", 404)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_ALREADY_TERMINAL = ("ERR_ALREADY_TERMINAL", 409)
ERR_ACCURACY_UNVERIFIED = ("ERR_ACCURACY_UNVERIFIED", 409)
ERR_ITEM_SUPPRESSED = ("ERR_ITEM_SUPPRESSED", 409)
ERR_INSUFFICIENT_INGREDIENT = ("ERR_INSUFFICIENT_INGREDIENT", 409)
ERR_LINE_CAPACITY_EXCEEDED = ("ERR_LINE_CAPACITY_EXCEEDED", 409)
ERR_INVALID_DEPLOYMENT = ("ERR_INVALID_DEPLOYMENT", 422)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 403)
ERR_DAY_NOT_CLOSABLE = ("ERR_DAY_NOT_CLOSABLE", 409)
ERR_MARKETPLACE_REFERENCE_INVALID = ("ERR_MARKETPLACE_REFERENCE_INVALID", 422)
ERR_WASTE_EXCEEDS_BATCH = ("ERR_WASTE_EXCEEDS_BATCH", 422)
ERR_MANUAL_SUPPRESSION_ONLY = ("ERR_MANUAL_SUPPRESSION_ONLY", 409)
ERR_WINDOW_OVERLAP = ("ERR_WINDOW_OVERLAP", 409)
# Generic 404 for resources without a dedicated catalog entry
# (production windows, recipe components, order lines, verifications,
# waste events, day-close records).
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
# Referenced by the state machine (start-production precondition); not in the
# catalog table, so pinned here at 409 alongside the other state-gate errors.
ERR_DEPLOYMENT_MISSING = ("ERR_DEPLOYMENT_MISSING", 409)
# Referenced by the state machine (start-production precondition); not in the
# catalog table, so pinned here at 409 alongside the other state-gate errors.
ERR_DEPLOYMENT_MISSING = ("ERR_DEPLOYMENT_MISSING", 409)


def raise_error(err, message=None):
    error_id, http_status = err
    raise ApiError(error_id, message or error_id, http_status)
