"""Single source of truth for the 49-code error catalogue (PRD 5).

Every failure is raised as an ApiError; app.py turns it into the PRD 2.2 error
envelope.  The HTTP status is looked up from the catalogue so an error id can
never be returned with the wrong status.
"""

ERROR_STATUS = {
    # auth / access
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_DONOR_SCOPE_VIOLATION": 403,
    # existence
    "ERR_RESOURCE_NOT_FOUND": 404,
    # shape / range / uniqueness
    "ERR_INVALID_REQUEST": 422,
    "ERR_FIELD_OUT_OF_RANGE": 422,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_CLOCK_NOT_MONOTONIC": 409,
    # state gates
    "ERR_DONOR_STATE_INVALID": 409,
    "ERR_SHIPMENT_STATE_INVALID": 409,
    "ERR_DONATION_STATE_INVALID": 409,
    "ERR_POOL_STATE_INVALID": 409,
    "ERR_RUN_STATE_INVALID": 409,
    "ERR_LOT_STATE_INVALID": 409,
    "ERR_PRESCRIPTION_STATE_INVALID": 409,
    "ERR_DISPENSE_STATE_INVALID": 409,
    # optimistic concurrency
    "ERR_STALE_VERSION": 412,
    # clinical safety / compliance
    "ERR_HEALTH_HISTORY_INCOMPLETE": 409,
    "ERR_SEROLOGY_MISSING_OR_EXPIRED": 409,
    "ERR_PHYSICIAN_APPROVAL_MISSING": 409,
    "ERR_RISK_SCORE_TOO_HIGH": 409,
    "ERR_DONOR_NOT_QUALIFIED": 409,
    "ERR_DONATION_IN_DEFERRAL_WINDOW": 409,
    "ERR_RUN_NOT_RELEASE_ELIGIBLE": 409,
    "ERR_SOD_RELEASE_CONFLICT": 403,
    "ERR_SOD_DISPENSE_CONFLICT": 403,
    "ERR_LOT_MILK_CLASS_UNSUITABLE": 409,
    # temporal
    "ERR_PASTEURIZER_SLOT_CONFLICT": 409,
    "ERR_READING_SEQUENCE_INVALID": 409,
    "ERR_RUN_READINGS_INSUFFICIENT": 409,
    "ERR_DEFERRAL_STILL_ACTIVE": 409,
    "ERR_DONOR_MILK_AGE_EXCEEDED": 409,
    "ERR_LOT_EXPIRED": 409,
    "ERR_PRESCRIPTION_PAST_NEEDED_BY": 409,
    # capacity / quantity
    "ERR_MILK_CLASS_MISMATCH": 409,
    "ERR_COMPONENT_ALREADY_ALLOCATED": 409,
    "ERR_ALLOCATION_EXCEEDS_DONATION_REMAINING": 409,
    "ERR_POOL_DONOR_CAP_EXCEEDED": 409,
    "ERR_POOL_EMPTY": 409,
    "ERR_POOL_DONOR_COUNT_INSUFFICIENT": 409,
    "ERR_POOL_NUTRITION_OUT_OF_RANGE": 409,
    "ERR_POOL_VOLUME_OUT_OF_RANGE": 409,
    "ERR_BOTTLING_EXCEEDS_POOL_VOLUME": 409,
    "ERR_DISPENSE_EXCEEDS_PRESCRIPTION_REMAINING": 409,
    "ERR_DISPENSE_EXCEEDS_LOT_AVAILABLE": 409,
    "ERR_NICU_RESERVE_PROTECTED": 409,
    # fiscal
    "ERR_SUBSIDY_PROGRAM_EXHAUSTED": 402,
    "ERR_SUBSIDY_CAP_EXCEEDED": 402,
}


class ApiError(Exception):
    """A rejection carrying its catalogue error id, message and HTTP status."""

    def __init__(self, error_id, message=None, status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.status = status if status is not None else ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def not_found(what="Referenced resource does not exist."):
    raise ApiError("ERR_RESOURCE_NOT_FOUND", what)


def invalid(message="The request body is not shape-valid."):
    raise ApiError("ERR_INVALID_REQUEST", message)


def out_of_range(message="A field value is outside its declared range."):
    raise ApiError("ERR_FIELD_OUT_OF_RANGE", message)
