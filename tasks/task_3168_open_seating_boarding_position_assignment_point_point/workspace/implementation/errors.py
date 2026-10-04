"""Error classes and HTTP status map."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or unrecognized X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted for endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_state(msg="Resource state precondition failed"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale_version(msg="Stale version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_validation(msg="Malformed body"):
    return ApiError("ERR_VALIDATION", 400, msg)
