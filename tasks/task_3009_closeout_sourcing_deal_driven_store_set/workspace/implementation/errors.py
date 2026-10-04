"""Error classes and error ID constants."""


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def invalid_request(message: str) -> ApiError:
    return ApiError("ERR_INVALID_REQUEST", message, 400)


def unauthenticated(message: str) -> ApiError:
    return ApiError("ERR_UNAUTHENTICATED", message, 401)


def unauthorized(message: str) -> ApiError:
    return ApiError("ERR_UNAUTHORIZED", message, 403)


def not_found(message: str) -> ApiError:
    return ApiError("ERR_NOT_FOUND", message, 404)


def invalid_state(message: str) -> ApiError:
    return ApiError("ERR_INVALID_STATE", message, 409)


def stale_version(message: str) -> ApiError:
    return ApiError("ERR_STALE_VERSION", message, 412)
