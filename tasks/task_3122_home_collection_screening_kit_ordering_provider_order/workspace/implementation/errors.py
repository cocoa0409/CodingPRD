class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def missing_context():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-ID or X-User-Role header missing or empty")


def forbidden():
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                    "Role not permitted for this endpoint")


def not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def validation(msg="Malformed request body"):
    return ApiError("ERR_VALIDATION", 400, msg)


def biz(error_id, status, message):
    return ApiError(error_id, status, message)
