"""Error type carrying the PRD error catalogue identifiers."""


class ApiError(Exception):
    """Application error rendered through the standard error envelope.

    error_id: exact identifier from the PRD section 5 error catalogue.
    http_status: matching HTTP status from the same catalogue.
    message: human-readable explanation (free text).
    """

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message
