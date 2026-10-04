"""Error type carrying the scaffold's error_id / http_status contract."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def unauthenticated(message="Missing or invalid authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, message)


def forbidden(message="Role not permitted for this operation"):
    return ApiError("ERR_FORBIDDEN", 403, message)


def not_found(message="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, message)


def invalid_request(message="Request body is invalid"):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def invalid_state(message="Operation is not valid for the resource's current state"):
    return ApiError("ERR_INVALID_STATE", 409, message)
