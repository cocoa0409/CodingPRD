"""Error type carrying the scaffold's error_id, HTTP status and message."""


class ApiError(Exception):
    def __init__(self, status, error_id, message):
        super().__init__(message)
        self.status = status
        self.error_id = error_id
        self.message = message


def not_found(error_id, message):
    return ApiError(404, error_id, message)
