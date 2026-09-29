"""Error catalogue (PRD section 5)."""

HTTP_STATUS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_FORBIDDEN": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # payload
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_ZONE_NOT_FOUND": 404,
    "ERR_SEGMENT_NOT_FOUND": 404,
    "ERR_CLOSURE_NOT_FOUND": 404,
    "ERR_MERCHANT_NOT_FOUND": 404,
    "ERR_ROBOT_NOT_FOUND": 404,
    "ERR_BAY_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_MISSION_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_INTERVENTION_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    # concurrency
    "ERR_STALE_MISSION_VERSION": 412,
    "ERR_STALE_BAY_VERSION": 412,
    "ERR_STALE_ORDER_VERSION": 412,
    # state
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_ZONE_NOT_PERMITTED": 409,
    "ERR_MERCHANT_NOT_ACTIVE": 409,
    "ERR_ROBOT_NOT_AVAILABLE": 409,
    "ERR_ROBOT_HEALTH_BLOCKED": 409,
    "ERR_SEGMENT_NOT_APPROVED": 409,
    "ERR_SEGMENT_BLOCKED": 409,
    "ERR_MISSION_ALREADY_TERMINAL": 409,
    "ERR_RESERVATION_NOT_ACTIVE": 409,
    "ERR_TAKEOVER_REQUIRED": 409,
    "ERR_REMEDY_ALREADY_ISSUED": 409,
    # safety / consistency
    "ERR_CLEARANCE_INSUFFICIENT": 422,
    "ERR_CROSSING_RISK_EXCEEDED": 422,
    "ERR_ORDINANCE_SPEED_EXCEEDED": 422,
    "ERR_CURFEW_WINDOW_VIOLATION": 422,
    "ERR_ROUTE_NOT_CONTIGUOUS": 422,
    "ERR_ROUTE_DROPOFF_MISMATCH": 422,
    "ERR_ZONE_MISMATCH": 422,
    # capacity / constraint
    "ERR_PAYLOAD_CAPACITY_EXCEEDED": 422,
    "ERR_LID_CODE_MISMATCH": 422,
    "ERR_NO_ELIGIBLE_ROBOT": 422,
    "ERR_BAY_TYPE_MISMATCH": 422,
    "ERR_ZONE_ROBOT_CAP_EXCEEDED": 409,
    "ERR_BAY_WINDOW_CONFLICT": 409,
    "ERR_HARD_CLOSURE_OVERLAP": 409,
    "ERR_REMEDY_BUDGET_EXCEEDED": 402,
    "ERR_MANDATORY_INCIDENT_UNFILED": 409,
    "ERR_BAY_OUT_OF_SERVICE": 409,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication role header is missing or empty.",
    "ERR_ROLE_FORBIDDEN": "The acting role may not perform this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The acting principal does not own this resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this action by the filer.",
    "ERR_INVALID_REQUEST": "The request payload is invalid.",
    "ERR_INVALID_STATE_TRANSITION": "The requested transition is not permitted from the current state.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGE.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)
