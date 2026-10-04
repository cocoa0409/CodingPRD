"""API error type. Carries the scaffold's error_id, HTTP status and message;
serialized by the envelope helper into the §2.2 error body."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message
