"""API error type. Error IDs and HTTP statuses are used verbatim from the
PRD section 5 catalogue at each raise site."""


class ApiError(Exception):
    """Carries the catalogue error_id, HTTP status, and human message."""

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def raise_err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)
