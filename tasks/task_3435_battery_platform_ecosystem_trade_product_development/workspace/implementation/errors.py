"""API error type. Carries the scaffold error_id and its HTTP status."""
from constants import ERROR_HTTP


class ApiError(Exception):
    def __init__(self, error_id, message, http_status=None):
        if http_status is None:
            http_status = ERROR_HTTP[error_id]
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def fail(error_id, message):
    raise ApiError(error_id, message)
