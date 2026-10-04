"""Error classes carrying error_id / http_status, plus constants."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_missing_ctx():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-ID or X-User-Role missing or malformed")


def err_forbidden_role():
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                    "Role not permitted for this endpoint")


def err_forbidden():
    return ApiError("ERR_FORBIDDEN", 403, "Ownership check failed")


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_state(msg="Invalid state for requested action"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_invalid_request(msg="Required field missing or malformed"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_enum(msg="Enum value outside declared set"):
    return ApiError("ERR_INVALID_ENUM", 400, msg)


def err_unknown_action(msg="Unknown transition action"):
    return ApiError("ERR_UNKNOWN_ACTION", 400, msg)
