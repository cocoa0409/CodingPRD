class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def bad_request(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def not_found(msg="Resource not found"):
    raise ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg):
    raise ApiError("ERR_INVALID_STATE", 409, msg)
