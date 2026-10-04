"""Error identifiers and the API exception type.

Error ids and their HTTP statuses come from SCAFFOLD.yaml §1.6 (mirrored by
PRD §5).  Nothing here is inferred: every id below appears in the catalogue.
"""


class ApiError(Exception):
    """An error carrying the wire contract: error_id, message, http status."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- id -> HTTP status, straight from the catalogue -------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_MEMBER_STALE_VERSION": 412,
    "ERR_INSPECTION_STALE_VERSION": 412,
    "ERR_STORE_FROZEN": 409,
    "ERR_STORE_RESTRICTED": 409,
    "ERR_CUP_CAPACITY_EXCEEDED": 409,
    "ERR_SHRINKAGE_ALERT": 409,
    "ERR_INSPECTION_REQUIRED": 422,
    "ERR_COMPONENT_NOT_STOCKED": 422,
    "ERR_COMPONENTS_INCOMPLETE": 409,
    "ERR_ELEMENT_NOT_SOURCED": 422,
    "ERR_ELEMENT_BIN_OCCUPIED": 409,
    "ERR_QUEUE_NOT_READY": 422,
    "ERR_PURCHASE_LIMIT_EXCEEDED": 409,
    "ERR_EVENT_CAPACITY_EXCEEDED": 409,
    "ERR_WINDOW_EXPIRED": 422,
    "ERR_EVENT_WINDOW_CLOSED": 422,
    "ERR_LAUNCH_NOT_OPEN": 422,
    "ERR_REPLACEMENT_LIMIT_REACHED": 409,
    "ERR_MEMBER_FROZEN": 409,
    "ERR_EVENT_SLOT_OVERLAP": 409,
    "ERR_LAUNCH_WINDOW_INVALID": 409,
    "ERR_LAUNCH_WINDOW_OVERLAP": 409,
    "ERR_CONSTRAINT_VIOLATION": 409,
}


def fail(error_id, message):
    """Raise the registered error for `error_id`."""
    raise ApiError(error_id, message, ERROR_HTTP.get(error_id, 409))