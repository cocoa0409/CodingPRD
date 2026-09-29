"""Error catalogue and the single exception type every refusal travels through.

PRD section 5 fixes the (error_id -> HTTP status) mapping; nothing else in this
module invents a code.
"""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_HATCHERY_SCOPE_VIOLATION": 403,
    "ERR_NOT_REQUEST_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_HATCHERY_NOT_FOUND": 404,
    "ERR_WATER_NOT_FOUND": 404,
    "ERR_BROOD_STOCK_NOT_FOUND": 404,
    "ERR_SPAWN_EVENT_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_REQUEST_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_TRANSPORT_UNIT_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_DUPLICATE_STATION_CODE": 409,
    "ERR_STALE_LOT_VERSION": 412,
    "ERR_STALE_PLAN_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_SPAWN_WINDOW_CLOSED": 409,
    "ERR_BROOD_STOCK_NOT_SPAWNING": 409,
    "ERR_WATER_CLOSED": 409,
    "ERR_HATCHERY_FROZEN": 409,
    "ERR_HATCHERY_RESTRICTED": 409,
    "ERR_TRANSPORT_UNIT_UNAVAILABLE": 409,
    "ERR_WATER_REST_BUFFER": 409,
    "ERR_LOT_NOT_CERTIFIED": 422,
    "ERR_LOT_QUARANTINED": 422,
    "ERR_HEALTH_CERTIFICATE_EXPIRED": 422,
    "ERR_WITHDRAWAL_PERIOD_ACTIVE": 422,
    "ERR_PATHOGEN_NOT_TREATABLE": 422,
    "ERR_TEMP_DELTA_EXCEEDED": 422,
    "ERR_ACCLIMATION_INSUFFICIENT": 422,
    "ERR_OXYGEN_SUPPLY_EXCEEDED": 422,
    "ERR_DENSITY_CAP_EXCEEDED": 422,
    "ERR_TRANSPORT_CAPACITY_EXCEEDED": 422,
    "ERR_LOT_INSUFFICIENT_FISH": 422,
    "ERR_BROOD_FEMALES_INSUFFICIENT": 422,
    "ERR_ALLOCATION_EXCEEDED": 422,
    "ERR_STAGE_WEIGHT_NOT_MET": 422,
    "ERR_SPECIES_MISMATCH": 422,
    "ERR_SIZE_CLASS_MISMATCH": 422,
    "ERR_NO_ELIGIBLE_REQUESTS": 422,
    "ERR_WATER_RIGHT_EXCEEDED": 422,
    "ERR_BUDGET_EXCEEDED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)
