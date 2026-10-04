"""Error types and the error catalog (error_id -> HTTP status)."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def unauthenticated(message="X-User-ID or X-User-Role header missing or role not declared"):
    return ApiError("ERR_UNAUTHENTICATED", 401, message)


def forbidden(message="Role not permitted on this endpoint or ownership violated"):
    return ApiError("ERR_FORBIDDEN", 403, message)


def not_found(message="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, message)


def stale(message="Expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", 412, message)


def invalid_state(message="Entity is in a state that forbids the operation"):
    return ApiError("ERR_INVALID_STATE", 409, message)


def conflict(error_id, message):
    return ApiError(error_id, 409, message)


def unprocessable(error_id, message):
    return ApiError(error_id, 422, message)
