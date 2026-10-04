"""API error type. error_id and http status come from the PRD error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def raise_err(error_id, status, message):
    raise ApiError(error_id, status, message)


def invalid_request(message):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)


def invalid_state(message):
    raise ApiError("ERR_INVALID_STATE", 409, message)
