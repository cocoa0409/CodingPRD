"""Error catalogue (PRD section 5) and the ApiError exception carried by every rejection."""

ERROR_STATUS = {
    # ---- auth ----
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    # ---- schema ----
    "ERR_INVALID_REQUEST": 400,
    # ---- not-found family ----
    "ERR_STORAGE_FIELD_NOT_FOUND": 404,
    "ERR_WELL_NOT_FOUND": 404,
    "ERR_MIT_NOT_FOUND": 404,
    "ERR_REMEDIATION_PROGRAM_NOT_FOUND": 404,
    "ERR_COMPRESSOR_UNIT_NOT_FOUND": 404,
    "ERR_COMPRESSOR_RUN_NOT_FOUND": 404,
    "ERR_SHIPPER_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_NOMINATION_NOT_FOUND": 404,
    "ERR_TICKET_NOT_FOUND": 404,
    "ERR_EMERGENCY_EVENT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    # ---- ownership ----
    "ERR_CONTRACT_NOT_OWNED": 403,
    # ---- state ----
    "ERR_INVALID_TICKET_STATE": 409,
    "ERR_INVALID_NOMINATION_STATE": 409,
    "ERR_INVALID_CONTRACT_STATE": 409,
    "ERR_INVALID_MIT_STATE": 409,
    "ERR_INVALID_REMEDIATION_STATE": 409,
    "ERR_INVALID_RUN_STATE": 409,
    "ERR_INVALID_EMERGENCY_STATE": 409,
    "ERR_INVALID_REPORT_STATE": 409,
    "ERR_INVALID_WELL_STATE": 409,
    "ERR_STALE_CONTRACT_VERSION": 412,
    "ERR_STALE_FIELD_VERSION": 412,
    # ---- business safety ----
    "ERR_FIELD_FROZEN": 422,
    "ERR_INTERRUPTIBLE_RESTRICTED": 422,
    "ERR_WELL_NOT_IN_SERVICE": 422,
    "ERR_WELL_INTEGRITY_FAILED": 422,
    "ERR_CUSHION_GAS_BREACH": 422,
    "ERR_WORKING_GAS_CAPACITY_EXCEEDED": 422,
    "ERR_FIELD_PRESSURE_LIMIT": 422,
    "ERR_EVACUATION_RADIUS_INVALID": 422,
    # ---- business temporal ----
    "ERR_GAS_DAY_OUTSIDE_TERM": 422,
    "ERR_NOMINATION_WINDOW_CLOSED": 422,
    "ERR_SEASON_DIRECTION_MISMATCH": 422,
    "ERR_MIT_WINDOW_IN_PAST": 422,
    "ERR_MIT_WINDOW_NOT_ELAPSED": 409,
    "ERR_RUN_WINDOW_IN_PAST": 422,
    "ERR_RUN_WINDOW_NOT_ELAPSED": 409,
    # ---- business constraint ----
    "ERR_MIT_WINDOW_CONFLICT": 409,
    "ERR_HORSEPOWER_OVERSUBSCRIBED": 409,
    "ERR_SOD_REMEDIATION_SELF_VERIFICATION": 403,
    "ERR_DUPLICATE_FIELD_CODE": 409,
    "ERR_DUPLICATE_DUNS": 409,
    "ERR_DUPLICATE_CONTRACT_CODE": 409,
    "ERR_DUPLICATE_UNIT_CODE": 409,
    "ERR_DUPLICATE_REPORT_PERIOD": 409,
    "ERR_TICKET_ALREADY_EXISTS": 409,
    "ERR_TICKET_OVERRUN_EXCEEDED": 422,
    "ERR_NOMINATION_REVISION_LIMIT": 422,
    "ERR_REPORTING_PERIOD_LOCKED": 409,
    "ERR_REMEDIATION_ESCALATED": 409,
    # ---- business fiscal ----
    "ERR_CONTRACT_RIGHTS_EXCEEDED": 422,
    "ERR_CONTRACT_INVENTORY_INSUFFICIENT": 422,
    "ERR_SHIPPER_CREDIT_SUSPENDED": 402,
    "ERR_CASH_OUT_PERIOD_SETTLED": 409,
    "ERR_NOTHING_TO_CASH_OUT": 422,
    # ---- business referential ----
    "ERR_REPORT_VARIANCE_EXCEEDED": 422,
    "ERR_OPEN_INTEGRITY_FINDINGS": 422,
}

# Per-resource-type 404 codes (validation rungs 4 and 5).
NOT_FOUND_CODES = {
    "StorageField": "ERR_STORAGE_FIELD_NOT_FOUND",
    "Well": "ERR_WELL_NOT_FOUND",
    "MechanicalIntegrityTest": "ERR_MIT_NOT_FOUND",
    "RemediationProgram": "ERR_REMEDIATION_PROGRAM_NOT_FOUND",
    "CompressorUnit": "ERR_COMPRESSOR_UNIT_NOT_FOUND",
    "CompressorRun": "ERR_COMPRESSOR_RUN_NOT_FOUND",
    "Shipper": "ERR_SHIPPER_NOT_FOUND",
    "StorageContract": "ERR_CONTRACT_NOT_FOUND",
    "Nomination": "ERR_NOMINATION_NOT_FOUND",
    "GasMovementTicket": "ERR_TICKET_NOT_FOUND",
    "EmergencyEvent": "ERR_EMERGENCY_EVENT_NOT_FOUND",
    "RegulatoryReport": "ERR_REPORT_NOT_FOUND",
}


class ApiError(Exception):
    """Any rejected request raises this; the HTTP status comes from the catalogue."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def not_found(resource_type, message=None):
    code = NOT_FOUND_CODES[resource_type]
    return ApiError(code, message or ("%s does not exist." % resource_type))
