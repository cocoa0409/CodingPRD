"""Error classes and error ID constants."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_missing_user_context():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                    "X-User-ID or X-User-Role missing or empty", 400)


def err_insufficient_permissions():
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS",
                    "Role not permitted for endpoint", 403)


def err_not_found(what="resource"):
    return ApiError("ERR_NOT_FOUND", f"{what} does not exist", 404)


def err_invalid_request(msg="Required field missing, type mismatch, or enum value not in declared set"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_invalid_state(msg="Generic state precondition failure"):
    return ApiError("ERR_INVALID_STATE", msg, 409)
