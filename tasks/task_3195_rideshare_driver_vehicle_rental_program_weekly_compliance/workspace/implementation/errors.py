"""Error catalogue and exception type for the rideshare rental programme API."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


E_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
E_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
E_PAYMENT_BELOW_AMOUNT_DUE = ("ERR_PAYMENT_BELOW_AMOUNT_DUE", 402)
E_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
E_NOT_FOUND = ("ERR_NOT_FOUND", 404)
E_REFERENCED_ENTITY_NOT_FOUND = ("ERR_REFERENCED_ENTITY_NOT_FOUND", 404)
E_INVALID_STATE = ("ERR_INVALID_STATE", 409)
E_AGREEMENT_FROZEN = ("ERR_AGREEMENT_FROZEN", 409)
E_POSTURE_NOT_OPEN = ("ERR_POSTURE_NOT_OPEN", 409)
E_ENROLLMENT_NOT_ACTIVE = ("ERR_ENROLLMENT_NOT_ACTIVE", 409)
E_DRIVER_VEHICLE_CONFLICT = ("ERR_DRIVER_VEHICLE_CONFLICT", 409)
E_VEHICLE_NOT_AVAILABLE = ("ERR_VEHICLE_NOT_AVAILABLE", 409)
E_MODEL_NOT_QUALIFIED = ("ERR_MODEL_NOT_QUALIFIED", 409)
E_WEEK_OVERLAP = ("ERR_WEEK_OVERLAP", 409)
E_VEHICLE_INTERVAL_OVERLAP = ("ERR_VEHICLE_INTERVAL_OVERLAP", 409)
E_MAINTENANCE_WINDOW_CONFLICT = ("ERR_MAINTENANCE_WINDOW_CONFLICT", 409)
E_PURCHASE_BLOCKED_BY_DELINQUENCY = ("ERR_PURCHASE_BLOCKED_BY_DELINQUENCY", 409)
E_RECOVERY_ALREADY_CLOSED = ("ERR_RECOVERY_ALREADY_CLOSED", 409)
E_LOANER_UNAVAILABLE = ("ERR_LOANER_UNAVAILABLE", 409)
E_STALE_AGREEMENT_VERSION = ("ERR_STALE_AGREEMENT_VERSION", 412)
E_STALE_VEHICLE_VERSION = ("ERR_STALE_VEHICLE_VERSION", 412)
E_DRIVING_RECORD_INELIGIBLE = ("ERR_DRIVING_RECORD_INELIGIBLE", 422)
E_PLATFORM_ACTIVITY_INSUFFICIENT = ("ERR_PLATFORM_ACTIVITY_INSUFFICIENT", 422)
E_DRIVER_NOT_ELIGIBLE = ("ERR_DRIVER_NOT_ELIGIBLE", 422)
E_WEEK_OUTSIDE_AGREEMENT_TERM = ("ERR_WEEK_OUTSIDE_AGREEMENT_TERM", 422)
E_GRACE_NOT_LAPSED = ("ERR_GRACE_NOT_LAPSED", 422)
E_ESCROW_INCOMPLETE = ("ERR_ESCROW_INCOMPLETE", 422)

MESSAGES = {
    "ERR_INVALID_REQUEST": "The request body failed schema validation.",
    "ERR_UNAUTHENTICATED": "The caller could not be authenticated.",
    "ERR_PAYMENT_BELOW_AMOUNT_DUE": "The tendered amount is below the outstanding amount due.",
    "ERR_UNAUTHORIZED": "The caller is not permitted to perform this operation.",
    "ERR_NOT_FOUND": "The resource named by the path does not exist.",
    "ERR_REFERENCED_ENTITY_NOT_FOUND": "A foreign key in the request body does not name an existing row.",
    "ERR_INVALID_STATE": "The target resource is not in a state from which the requested operation is declared.",
    "ERR_AGREEMENT_FROZEN": "The agreement's compliance posture is FROZEN.",
    "ERR_POSTURE_NOT_OPEN": "The purchase stream requires an OPEN compliance posture.",
    "ERR_ENROLLMENT_NOT_ACTIVE": "The enrolment authorising this agreement is not ACTIVE.",
    "ERR_DRIVER_VEHICLE_CONFLICT": "The driver already holds a program vehicle in ASSIGNED status.",
    "ERR_VEHICLE_NOT_AVAILABLE": "The requested program vehicle is not AVAILABLE.",
    "ERR_MODEL_NOT_QUALIFIED": "The program vehicle's class is not permitted for the required activity.",
    "ERR_WEEK_OVERLAP": "Two weekly periods of the agreement would share one week number.",
    "ERR_VEHICLE_INTERVAL_OVERLAP": "The requested rental interval collides with an existing occupancy interval.",
    "ERR_MAINTENANCE_WINDOW_CONFLICT": "The unit's recovery interval is still open.",
    "ERR_PURCHASE_BLOCKED_BY_DELINQUENCY": "A week of the agreement is delinquent.",
    "ERR_RECOVERY_ALREADY_CLOSED": "The agreement's recovered-week set is already closed.",
    "ERR_LOANER_UNAVAILABLE": "No conforming loaner unit is available.",
    "ERR_STALE_AGREEMENT_VERSION": "expected_agreement_version does not match the agreement's version.",
    "ERR_STALE_VEHICLE_VERSION": "expected_vehicle_version does not match the vehicle's version.",
    "ERR_DRIVING_RECORD_INELIGIBLE": "The driver's driving record points exceed the programme ceiling.",
    "ERR_PLATFORM_ACTIVITY_INSUFFICIENT": "The driver's platform activity score is below the programme floor.",
    "ERR_DRIVER_NOT_ELIGIBLE": "The driver is not in good standing for this operation.",
    "ERR_WEEK_OUTSIDE_AGREEMENT_TERM": "The weekly period would extend past the agreement's period_end.",
    "ERR_GRACE_NOT_LAPSED": "The logical clock is before the week's grace deadline.",
    "ERR_ESCROW_INCOMPLETE": "The purchase option has not funded the required number of escrow weeks.",
}


def raise_error(pair, message=None):
    error_id, http_status = pair
    raise ApiError(error_id, message or MESSAGES.get(error_id, error_id), http_status)