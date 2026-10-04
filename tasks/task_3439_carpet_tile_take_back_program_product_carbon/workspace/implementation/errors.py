"""API error type. Carries the scaffold-declared error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super(ApiError, self).__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message
