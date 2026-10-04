"""Error classes and catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_CROSS_FAMILY_ACCESS": 403,
    "ERR_CROSS_DISTRICT_ACCESS": 403,
    "ERR_SEVERITY_VISIBILITY_DENIED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_FAMILY_SUSPENDED": 409,
    "ERR_CHILD_ARCHIVED": 409,
    "ERR_DEVICE_NOT_PAIRED": 409,
    "ERR_DEVICE_LIMIT_EXCEEDED": 409,
    "ERR_DEVICE_LOCKED_DOWN": 409,
    "ERR_CONNECTION_NOT_ACTIVE": 409,
    "ERR_DUPLICATE_CONNECTION": 409,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_GRANT_CONFLICT": 409,
    "ERR_ESCALATION_OPEN": 409,
    "ERR_INVALID_ESCALATION_STEP": 409,
    "ERR_LEGAL_REPORT_NOT_REQUIRED": 409,
    "ERR_LINK_WITHDRAW_BLOCKED": 409,
    "ERR_DISTRICT_SUSPENDED": 409,
}


def fail(error_id, message=None):
    status = ERR[error_id]
    raise ApiError(error_id, status, message or error_id)
