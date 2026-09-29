"""Error catalogue (PRD section 5). error_id -> HTTP status."""

ERROR_STATUS = {
    # Authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_INVALID_REQUEST": 400,
    # Existence
    "ERR_SPEC_PROFILE_NOT_FOUND": 404,
    "ERR_BUS_MODEL_NOT_FOUND": 404,
    "ERR_PROPULSION_PACKAGE_NOT_FOUND": 404,
    "ERR_SOLICITATION_NOT_FOUND": 404,
    "ERR_BID_NOT_FOUND": 404,
    "ERR_CONTRACT_ORDER_NOT_FOUND": 404,
    "ERR_PRODUCTION_LINE_NOT_FOUND": 404,
    "ERR_BUILD_SLOT_NOT_FOUND": 404,
    "ERR_BUS_UNIT_NOT_FOUND": 404,
    "ERR_TEST_BAY_NOT_FOUND": 404,
    "ERR_QUALITY_TEST_NOT_FOUND": 404,
    "ERR_DEALER_NOT_FOUND": 404,
    "ERR_RECALL_CAMPAIGN_NOT_FOUND": 404,
    "ERR_REMEDY_TASK_NOT_FOUND": 404,
    # Ownership
    "ERR_NOT_ASSIGNED_DEALER": 403,
    # Optimistic concurrency
    "ERR_STALE_BID_VERSION": 412,
    "ERR_STALE_LINE_VERSION": 412,
    # State preconditions
    "ERR_PROFILE_NOT_DRAFT": 409,
    "ERR_SOLICITATION_NOT_OPEN": 409,
    "ERR_SOLICITATION_NOT_CLOSED": 409,
    "ERR_BID_STATE_INVALID": 409,
    "ERR_UNIT_PHASE_INVALID": 409,
    "ERR_SLOT_STATE_INVALID": 409,
    "ERR_TEST_NOT_SCHEDULED": 409,
    "ERR_CAMPAIGN_NOT_DRAFT": 409,
    "ERR_TASK_STATE_INVALID": 409,
    "ERR_LINE_DOWN_FOR_MAINTENANCE": 409,
    "ERR_ORDER_NOT_ACTIVE": 409,
    # Business rules
    "ERR_SPEC_NONCONFORMING": 422,
    "ERR_ROUTE_RANGE_INSUFFICIENT": 422,
    "ERR_JOINT_STRENGTH_INSUFFICIENT": 422,
    "ERR_MEASURED_VALUE_BELOW_MINIMUM": 422,
    "ERR_REQUIRED_TEST_MISSING": 422,
    "ERR_OPEN_TEST_FAILURE": 422,
    "ERR_WAIVER_NOT_PERMITTED": 422,
    "ERR_UNIT_NOT_CERTIFIED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_REVISION_ROUND_LIMIT": 409,
    "ERR_DRIVER_TRAINING_INCOMPLETE": 409,
    "ERR_DEALER_STANDING_RESTRICTED": 409,
    "ERR_NO_AFFECTED_UNITS": 422,
    "ERR_INVALID_SLOT_WINDOW": 422,
    "ERR_SLOT_WINDOW_OVERLAP": 409,
    "ERR_CHANGEOVER_BUFFER_VIOLATION": 409,
    "ERR_SLOT_MISSES_DEADLINE": 409,
    "ERR_INVALID_TEST_WINDOW": 422,
    "ERR_TEST_BAY_CONFLICT": 409,
    "ERR_PROMISE_EXCEEDS_REQUIRED_DATE": 422,
    "ERR_INVALID_BUILD_WINDOW": 422,
    "ERR_SPEC_PROFILE_NOT_PUBLISHED": 409,
    "ERR_PROPULSION_MODEL_INCOMPATIBLE": 422,
    "ERR_BATTERY_BAY_CAPACITY_EXCEEDED": 422,
    "ERR_BODY_CLASS_UNSUPPORTED": 422,
    "ERR_TEST_TYPE_UNSUPPORTED": 422,
    "ERR_DEALER_NOT_LICENSED_IN_STATE": 422,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_VIN_ALREADY_EXISTS": 409,
    "ERR_PRICE_CAP_EXCEEDED": 422,
    "ERR_LINE_CAPACITY_EXCEEDED": 409,
    "ERR_ORDER_UNIT_COUNT_EXCEEDED": 409,
    "ERR_INSUFFICIENT_REMEDY_KITS": 422,
    "ERR_BAY_CONCURRENCY_LIMIT": 409,
    # Clock
    "ERR_CLOCK_REWIND_FORBIDDEN": 422,
}


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").lower().capitalize() + "."


class ApiError(Exception):
    """Raised anywhere in request handling; converted to the error envelope."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def invalid(message=None):
    raise ApiError("ERR_INVALID_REQUEST", message)
