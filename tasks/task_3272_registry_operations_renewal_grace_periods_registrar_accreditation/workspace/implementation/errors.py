class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_invalid_request(msg="Malformed request body or missing required input field"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_unauthenticated(msg="X-User-Role / X-User-ID headers missing or invalid"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg="Path id does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_state(msg="Target resource is in a state from which the requested transition does not exist"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_stale_version(msg="Expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)
