"""Error types and catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_missing_context(msg="X-User-ID or X-User-Role header missing or empty"):
    return ApiError("ERR_MISSING_OR_INVALID_CONTEXT_HEADER", 400, msg)


def err_unauthorized(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def err_segregation(msg="Same operator may not open and adjudicate the same audit case"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_not_found(msg="Referenced resource id does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Missing/invalid field, bad enum member, numeric range violated"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg="Requested transition not valid from the resource's current state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale_version(msg="expected version does not match the parent's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)
