"""Error type carrying the scaffold's exact (error_id, http_status) pairs."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def fail(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


def bad_request(message):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)
