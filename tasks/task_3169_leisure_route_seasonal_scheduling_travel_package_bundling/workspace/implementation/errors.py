"""Error classes and error ID constants per scaffold §1.6."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def missing_user_context():
    return ApiError(
        "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
        "X-User-ID or X-User-Role header missing or malformed",
        400,
    )


def insufficient_permissions():
    return ApiError(
        "ERR_INSUFFICIENT_PERMISSIONS",
        "Role not authorized for this endpoint",
        403,
    )


def stale_version():
    return ApiError(
        "ERR_STALE_VERSION",
        "expected_*_version does not match the parent entity's current version",
        412,
    )


def validation_error(message):
    return ApiError("ERR_VALIDATION", message, 422)
