# errors.py — API exception carrying the scaffold error id + HTTP status.
from constants import ERRORS


class ApiError(Exception):
    """Raised anywhere in a request path; app.py renders the error envelope."""

    def __init__(self, error_id, message=None, http_status=None):
        if http_status is None:
            http_status = ERRORS[error_id]
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, message=None):
    """Convenience raiser."""
    raise ApiError(error_id, message)
