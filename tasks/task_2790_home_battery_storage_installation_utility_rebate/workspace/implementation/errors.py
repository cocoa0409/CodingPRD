"""Error catalogue (PRD section 5) and the exception type routes raise."""


ERROR_HTTP = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_INSTALLER_NOT_FOUND": 404,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_LOAD_CALCULATION_NOT_FOUND": 404,
    "ERR_BATTERY_SYSTEM_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_TEST_NOT_FOUND": 404,
    "ERR_ALERT_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_PERFORMANCE_NOT_FOUND": 404,
    # state preconditions
    "ERR_LOAD_CALC_STATE_INVALID": 409,
    "ERR_SYSTEM_BUILD_STATE_INVALID": 409,
    "ERR_SYSTEM_GRID_STATE_INVALID": 409,
    "ERR_PERMIT_STATE_INVALID": 409,
    "ERR_APPLICATION_STATE_INVALID": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    "ERR_ALERT_STATE_INVALID": 409,
    "ERR_ENROLLMENT_STATE_INVALID": 409,
    "ERR_EVENT_STATE_INVALID": 409,
    "ERR_PERFORMANCE_STATE_INVALID": 409,
    # optimistic concurrency
    "ERR_STALE_SYSTEM_VERSION": 412,
    "ERR_STALE_EVENT_VERSION": 412,
    # commissioning safety
    "ERR_COMMISSIONING_TESTS_INCOMPLETE": 422,
    "ERR_BACKUP_TRANSITION_NOT_VERIFIED": 422,
    "ERR_COMMISSIONING_TEST_FAILED": 422,
    # certification / coverage
    "ERR_INSTALLER_NOT_CERTIFIED": 422,
    "ERR_LOAD_CALC_NOT_APPROVED": 422,
    "ERR_CAPACITY_BELOW_REQUIRED": 422,
    "ERR_WARRANTY_NOT_ACTIVE": 422,
    # cross-entity workflow gating
    "ERR_PERMIT_NOT_PASSED": 422,
    "ERR_ENROLLMENT_REQUIRES_PTO": 422,
    # temporal / overlap
    "ERR_PERMIT_EXPIRED": 422,
    "ERR_TEST_WINDOW_CONFLICT": 409,
    "ERR_TERRITORY_CAPACITY_EXCEEDED": 409,
    # uniqueness / cardinality
    "ERR_DUPLICATE_PERMIT": 409,
    "ERR_DUPLICATE_APPLICATION": 409,
    "ERR_DUPLICATE_PROGRAM_CLAIM": 409,
    "ERR_DUPLICATE_TEST": 409,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    "ERR_PARTICIPATION_DUPLICATE": 409,
    "ERR_PERMIT_CORRECTION_LIMIT": 409,
    # incentive constraints
    "ERR_EXPORT_COMMITMENT_REQUIRED": 422,
    "ERR_CAPACITY_COMMITMENT_INVALID": 422,
    "ERR_STACK_CAP_EXCEEDED": 422,
    "ERR_INVERTER_INCOMPATIBLE": 422,
    "ERR_FIRMWARE_TOO_OLD": 422,
    "ERR_UNIT_LIMIT_EXCEEDED": 422,
    "ERR_PLEDGE_EXCEEDS_CAPACITY": 422,
    # fiscal
    "ERR_PROGRAM_BUDGET_EXHAUSTED": 422,
}


NOT_FOUND_FOR_KIND = {
    "installer": "ERR_INSTALLER_NOT_FOUND",
    "site": "ERR_SITE_NOT_FOUND",
    "load_calculation": "ERR_LOAD_CALCULATION_NOT_FOUND",
    "battery_system": "ERR_BATTERY_SYSTEM_NOT_FOUND",
    "permit": "ERR_PERMIT_NOT_FOUND",
    "application": "ERR_APPLICATION_NOT_FOUND",
    "program": "ERR_PROGRAM_NOT_FOUND",
    "claim": "ERR_CLAIM_NOT_FOUND",
    "test": "ERR_TEST_NOT_FOUND",
    "alert": "ERR_ALERT_NOT_FOUND",
    "enrollment": "ERR_ENROLLMENT_NOT_FOUND",
    "event": "ERR_EVENT_NOT_FOUND",
    "performance": "ERR_PERFORMANCE_NOT_FOUND",
}


class ApiError(Exception):
    """Domain rejection carrying the catalogue error id and its HTTP status."""

    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_HTTP.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)
