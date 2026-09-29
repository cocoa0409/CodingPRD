"""Error catalogue (PRD section 5) and the ApiError signal."""

ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_FORBIDDEN_ACTION_FOR_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_SUPERVISOR_CERTIFICATION_REQUIRED": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_CHECKPOINT_NOT_FOUND": 404,
    "ERR_LANE_NOT_FOUND": 404,
    "ERR_EQUIPMENT_UNIT_NOT_FOUND": 404,
    "ERR_OFFICER_NOT_FOUND": 404,
    "ERR_SHOW_UP_CURVE_NOT_FOUND": 404,
    "ERR_FLIGHT_SCHEDULE_ENTRY_NOT_FOUND": 404,
    "ERR_TIME_BAND_NOT_FOUND": 404,
    "ERR_STAFFING_PLAN_NOT_FOUND": 404,
    "ERR_LANE_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_WAIT_TIME_OBSERVATION_NOT_FOUND": 404,
    "ERR_ESCALATION_TICKET_NOT_FOUND": 404,
    "ERR_SCREENING_REFERRAL_NOT_FOUND": 404,
    "ERR_SURGE_DETAIL_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_CHECKPOINT_VERSION": 412,
    "ERR_STALE_OFFICER_VERSION": 412,
    # state preconditions
    "ERR_CHECKPOINT_SUSPENDED": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_PLAN_NOT_ACTIVATED": 409,
    "ERR_LANE_NOT_OPEN": 409,
    "ERR_BREAK_NOT_DUE": 409,
    # safety / regulatory
    "ERR_OFFICER_NOT_CERTIFIED": 422,
    "ERR_LANE_EQUIPMENT_UNAVAILABLE": 422,
    "ERR_CALIBRATION_OVERDUE": 422,
    # referential coherence
    "ERR_LANE_CHECKPOINT_MISMATCH": 422,
    "ERR_TIME_BAND_CHECKPOINT_MISMATCH": 422,
    "ERR_RESOLUTION_LANE_INVALID": 422,
    # temporal
    "ERR_BAND_OUTSIDE_OPERATIONAL_DATE": 422,
    "ERR_OFFICER_DOUBLE_BOOKED": 409,
    "ERR_OFFICER_REST_BUFFER_REQUIRED": 409,
    "ERR_DETAIL_WINDOW_OUTSIDE_PLAN": 422,
    # capacity / aggregate
    "ERR_LANE_POSITION_CAPACITY_EXCEEDED": 409,
    "ERR_LANE_POSITIONS_EXHAUSTED": 409,
    "ERR_SECONDARY_CAPACITY_EXHAUSTED": 409,
    "ERR_MIN_LANES_NOT_MET": 422,
    # fiscal
    "ERR_OVERTIME_CAP_EXCEEDED": 422,
    "ERR_PLAN_COST_CAP_EXCEEDED": 422,
    # uniqueness / data integrity
    "ERR_DUPLICATE_LANE_POSITION": 409,
    "ERR_DUPLICATE_TIME_BAND": 409,
    "ERR_DUPLICATE_BADGE_NUMBER": 409,
    "ERR_CURVE_BUCKETS_INVALID": 422,
    "ERR_BAND_NOT_FORECAST": 422,
}

NOT_FOUND_BY_ENTITY = {
    "checkpoint": "ERR_CHECKPOINT_NOT_FOUND",
    "lane": "ERR_LANE_NOT_FOUND",
    "equipment_unit": "ERR_EQUIPMENT_UNIT_NOT_FOUND",
    "officer": "ERR_OFFICER_NOT_FOUND",
    "show_up_curve": "ERR_SHOW_UP_CURVE_NOT_FOUND",
    "flight_schedule_entry": "ERR_FLIGHT_SCHEDULE_ENTRY_NOT_FOUND",
    "time_band": "ERR_TIME_BAND_NOT_FOUND",
    "staffing_plan": "ERR_STAFFING_PLAN_NOT_FOUND",
    "lane_assignment": "ERR_LANE_ASSIGNMENT_NOT_FOUND",
    "wait_time_observation": "ERR_WAIT_TIME_OBSERVATION_NOT_FOUND",
    "escalation_ticket": "ERR_ESCALATION_TICKET_NOT_FOUND",
    "screening_referral": "ERR_SCREENING_REFERRAL_NOT_FOUND",
    "surge_detail": "ERR_SURGE_DETAIL_NOT_FOUND",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def bad_request(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def not_found(entity, ident=None):
    raise ApiError(
        NOT_FOUND_BY_ENTITY[entity],
        "%s '%s' does not exist" % (entity, ident) if ident else "%s not found" % entity,
    )
