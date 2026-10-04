"""API error type. Carries the scaffold error_id, a human message, and the
HTTP status from the error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message, 400)


def not_found(error_id, resource_name):
    return ApiError(error_id, f"{resource_name} not found", 404)
