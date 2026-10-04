"""Error classes and error-id constants.

Every error id and HTTP status here traces to PRD.md §5 (Error Code Catalogue)
and the per-operation narratives in PRD §3.
"""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


E = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_NOT_FOUND": 404,
    "ERR_POD_NOT_FOUND": 404,
    "ERR_VEHICLE_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_MAINTENANCE_ORDER_NOT_FOUND": 404,
    "ERR_ACCESS_EVENT_NOT_FOUND": 404,
    "ERR_FUEL_TRANSACTION_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_ALREADY_RELEASED": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_APPLICATION_NOT_APPROVED": 409,
    "ERR_SCREENING_NOT_CLEAR": 422,
    "ERR_MEMBERSHIP_NOT_ACTIVE": 409,
    "ERR_MEMBERSHIP_FROZEN": 409,
    "ERR_VEHICLE_NOT_AVAILABLE": 409,
    "ERR_DRIVING_RECORD_PENDING": 409,
    "ERR_DUPLICATE_PRIMARY_MEMBERSHIP": 409,
    "ERR_MEMBER_EMAIL_TAKEN": 409,
    "ERR_WRONG_RETURN_POD": 422,
    "ERR_ODOMETER_REGRESSION": 422,
    "ERR_VEHICLE_DOUBLE_BOOKED": 409,
    "ERR_MAINTENANCE_WINDOW_CONFLICT": 409,
    "ERR_BUNDLE_WINDOW_CONFLICT": 409,
    "ERR_POD_CAPACITY_EXCEEDED": 409,
    "ERR_INCIDENT_REFERENCE_MISMATCH": 422,
    "ERR_INSUFFICIENT_WALLET_CREDIT": 422,
    "ERR_WALLET_ADJUSTMENT_INVALID": 422,
    "ERR_REOPEN_WINDOW_CLOSED": 409,
    "ERR_INCIDENT_IN_FUTURE": 422,
    "ERR_CITATION_SIGNATURE_INVALID": 422,
    "ERR_LOSS_EXCEEDS_REPAIR_COST": 422,
}


def fail(error_id, message=None):
    raise ApiError(error_id, message or error_id, E[error_id])