"""API error type carrying the scaffold-declared error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def fail(error_id, http_status, message):
    """Raise an ApiError. Every error_id literal raised in the codebase is
    greppable at a call site of this helper (or direct ApiError construction)."""
    raise ApiError(error_id, http_status, message)


def not_found(message="resource not found"):
    raise ApiError("ERR_NOT_FOUND", 404, message)
