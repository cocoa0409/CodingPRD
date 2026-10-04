"""Error catalog: error ids and their HTTP statuses (PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_VALIDATION": 400,
    "ERR_SEASON_NOT_FOUND": 404,
    "ERR_MODEL_NOT_FOUND": 404,
    "ERR_CHANNEL_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_ASSEMBLER_NOT_FOUND": 404,
    "ERR_JOB_NOT_FOUND": 404,
    "ERR_SALE_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_PART_NOT_FOUND": 404,
    "ERR_PARTS_ORDER_NOT_FOUND": 404,
    "ERR_DEVICE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_SEASON_POSTURE_FORBIDDEN": 409,
    "ERR_ALLOCATION_NOT_ACTIONABLE": 409,
    "ERR_JOB_NOT_SCHEDULABLE": 409,
    "ERR_CLAIM_NOT_ADJUDICATABLE": 409,
    "ERR_SALE_NOT_REGISTERED": 409,
    "ERR_SALE_RETURNED": 409,
    "ERR_ASSEMBLER_NOT_CERTIFIED": 409,
    "ERR_DEVICE_NOT_PAIRED": 409,
    "ERR_DEVICE_ALREADY_PAIRED": 409,
    "ERR_MODEL_NOT_SELLABLE": 409,
    "ERR_NO_ACTIVE_ALLOCATION": 409,
    "ERR_SEASON_OVERLAP": 409,
    "ERR_ASSEMBLY_WINDOW_CONFLICT": 409,
    "ERR_ASSEMBLER_BUFFER_CONFLICT": 409,
    "ERR_MAX_CONCURRENT_JOBS": 409,
    "ERR_DUPLICATE_SERIAL": 409,
    "ERR_ALLOCATION_CAPACITY_EXCEEDED": 409,
    "ERR_PART_UNAVAILABLE": 409,
    "ERR_REOPEN_WINDOW_EXPIRED": 409,
    "ERR_PART_INCOMPATIBLE": 422,
    "ERR_PARTS_OBLIGATION_EXPIRED": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 422,
    "ERR_GOODWILL_CAP_EXCEEDED": 422,
    "ERR_STALE_VERSION": 412,
}


def api_error(error_id, message):
    return ApiError(error_id, ERROR_HTTP[error_id], message)


def not_found(entity):
    """entity is the singular resource key, e.g. 'SEASON', 'MODEL', ..."""
    return api_error("ERR_%s_NOT_FOUND" % entity, "%s id does not exist" % entity.lower())


def validation(message):
    return api_error("ERR_VALIDATION", message)
