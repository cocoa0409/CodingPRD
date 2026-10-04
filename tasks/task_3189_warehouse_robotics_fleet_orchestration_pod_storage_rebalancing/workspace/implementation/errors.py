"""Error types and identifiers."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_SAFETY_INTERLOCK = "ERR_SAFETY_INTERLOCK"
ERR_REFERENTIAL_MISMATCH = "ERR_REFERENTIAL_MISMATCH"
ERR_TEMPORAL_CONFLICT = "ERR_TEMPORAL_CONFLICT"
ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"
ERR_INSUFFICIENT_INVENTORY = "ERR_INSUFFICIENT_INVENTORY"
ERR_NO_ELIGIBLE_DRIVE_UNIT = "ERR_NO_ELIGIBLE_DRIVE_UNIT"
ERR_NO_ELIGIBLE_POD = "ERR_NO_ELIGIBLE_POD"
ERR_VALIDATION = "ERR_VALIDATION"


def unauthenticated(msg="missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden(msg="role not permitted for this endpoint"):
    return ApiError(ERR_FORBIDDEN, msg, 403)


def not_found(msg="resource not found"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def invalid_state(msg="invalid state for requested transition"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def stale_version(msg="expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)


def safety_interlock(msg="safety interlock engaged"):
    return ApiError(ERR_SAFETY_INTERLOCK, msg, 422)


def referential_mismatch(msg="foreign key reference shape mismatch"):
    return ApiError(ERR_REFERENTIAL_MISMATCH, msg, 422)


def temporal_conflict(msg="temporal interval invalid or violates buffer rules"):
    return ApiError(ERR_TEMPORAL_CONFLICT, msg, 422)


def capacity_exceeded(msg="resource capacity exceeded"):
    return ApiError(ERR_CAPACITY_EXCEEDED, msg, 422)


def insufficient_inventory(msg="available units below requested quantity"):
    return ApiError(ERR_INSUFFICIENT_INVENTORY, msg, 422)


def no_eligible_drive_unit(msg="fleet selector candidate pool empty"):
    return ApiError(ERR_NO_ELIGIBLE_DRIVE_UNIT, msg, 422)


def no_eligible_pod(msg="stow-placement selector candidate pool empty"):
    return ApiError(ERR_NO_ELIGIBLE_POD, msg, 422)


def validation(msg="request shape error"):
    return ApiError(ERR_VALIDATION, msg, 400)
