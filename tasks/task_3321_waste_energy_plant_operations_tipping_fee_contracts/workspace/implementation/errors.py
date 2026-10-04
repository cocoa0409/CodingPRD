"""Error types and IDs per the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="X-User-Role header missing or not a declared role"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def err_not_found(msg="Referenced resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_state(msg="Resource not in a state permitting this transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale_version(msg="Expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_422(error_id, msg):
    return ApiError(error_id, 422, msg)
