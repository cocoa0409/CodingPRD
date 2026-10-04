"""API error type. Error ids and HTTP statuses come from the PRD section 5
error catalogue; nothing here is invented."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def raise_err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


# Short-named raisers for the most common cases.
def err_unauthenticated(msg="missing or unknown authentication headers"):
    raise ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized(msg="role is not permitted on this endpoint"):
    raise ApiError("ERR_UNAUTHORIZED", 403, msg)


def err_not_found(msg="path identifier does not resolve"):
    raise ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="request body is not well-formed"):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg="state machine does not permit this transition"):
    raise ApiError("ERR_INVALID_STATE", 409, msg)


def err_forbidden_ownership(msg="acting identity does not own this resource"):
    raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, msg)
