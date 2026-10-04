"""API error type. error_id values come from the SCAFFOLD/PRD error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = status
        self.message = message or error_id
