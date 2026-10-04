class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def raise_err(error_id, http_status, message):
    raise ApiError(error_id, message, http_status)
