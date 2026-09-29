"""Error catalogue and the single exception type every validation raises.

Every entry traces to PRD section 5 (Error Code Catalogue).
"""

ERROR_STATUS = {
    # auth / authz
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_MARKET_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_MARKET_NOT_FOUND": 404,
    "ERR_SEGMENT_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_CHANNEL_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_FLEET_PLAN_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_VEHICLE_NOT_FOUND": 404,
    "ERR_TASK_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_DAMAGE_EVENT_NOT_FOUND": 404,
    "ERR_CONSIGNMENT_NOT_FOUND": 404,
    "ERR_LEDGER_ENTRY_NOT_FOUND": 404,
    # schema
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_INVALID_UNIT_COUNT": 422,
    # optimistic concurrency
    "ERR_STALE_PLAN_VERSION": 412,
    "ERR_STALE_VEHICLE_VERSION": 412,
    # uniqueness
    "ERR_DUPLICATE_MARKET_CODE": 409,
    "ERR_DUPLICATE_SEGMENT_CODE": 409,
    "ERR_DUPLICATE_CHANNEL_CODE": 409,
    "ERR_DUPLICATE_VIN": 409,
    "ERR_DUPLICATE_FLEET_PLAN": 409,
    "ERR_DUPLICATE_TASK_TYPE": 409,
    # state preconditions
    "ERR_PLAN_NOT_DRAFT": 409,
    "ERR_PLAN_NOT_LOCKED": 409,
    "ERR_ALLOCATION_NOT_CANCELLABLE": 409,
    "ERR_VEHICLE_INVALID_FLEET_STATE": 409,
    "ERR_VEHICLE_INVALID_CONDITION_STATE": 409,
    "ERR_TASK_ALREADY_RESOLVED": 409,
    "ERR_ORDER_INVALID_STATE": 409,
    "ERR_DAMAGE_EVENT_INVALID_STATE": 409,
    "ERR_CONSIGNMENT_INVALID_STATE": 409,
    "ERR_POLICY_NOT_DRAFT": 409,
    "ERR_PROGRAM_CLOSED": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    # total-loss routing safety
    "ERR_TOTAL_LOSS_DETERMINATION_REQUIRED": 422,
    "ERR_TOTAL_LOSS_NOT_APPLICABLE": 422,
    # open damage
    "ERR_OPEN_DAMAGE_BLOCKS_LISTING": 422,
    # temporal
    "ERR_PREP_BEFORE_REGISTRATION": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_TRANSFER_WINDOW_INVALID": 422,
    "ERR_MIN_HOLDING_PERIOD_NOT_MET": 422,
    "ERR_VEHICLE_TRANSFER_OVERLAP": 409,
    "ERR_PREP_BAY_CONFLICT": 409,
    # referential / configuration
    "ERR_CHANNEL_NOT_ELIGIBLE": 422,
    "ERR_SUPERSEDE_TARGET_MISMATCH": 422,
    "ERR_MARKET_SUSPENDED": 422,
    "ERR_SAME_MARKET_TRANSFER": 422,
    "ERR_NO_ACTIVE_DEPRECIATION_POLICY": 422,
    "ERR_MILEAGE_BAND_EXCLUDES_CHANNEL": 422,
    # capacity / constraint
    "ERR_ALLOCATION_UNIT_LIMIT_REACHED": 422,
    "ERR_PREP_CAPACITY_EXCEEDED": 422,
    "ERR_ODOMETER_REGRESSION": 422,
    "ERR_RECONDITION_CAP_EXCEEDED": 422,
    "ERR_RECONDITION_OVERRUN": 422,
    "ERR_RECOVERY_EXCEEDS_CAP": 422,
    "ERR_NO_ELIGIBLE_CHANNEL": 422,
    # fiscal
    "ERR_PLAN_POSTURE_RESTRICTED": 422,
    "ERR_PLAN_POSTURE_FROZEN": 422,
    "ERR_TRANSPORT_COST_EXCEEDS_BENEFIT": 422,
    "ERR_PROCEEDS_BELOW_FLOOR": 422,
    # non-catalogue fallback for unrouted requests
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    """Raised anywhere in a request to terminate it with a catalogue error."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_STATUS.get(error_id, 422)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request refused: %s." % words
