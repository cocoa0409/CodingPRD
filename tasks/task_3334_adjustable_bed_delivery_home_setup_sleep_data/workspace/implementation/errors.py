"""Error classes and error ID constants (from SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or unknown role / identity headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted, or customer ownership mismatch"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_validation(msg="Request failed schema/type/enum validation"):
    return ApiError("ERR_VALIDATION", 400, msg)


def not_found(error_id, msg):
    return ApiError(error_id, 404, msg)
