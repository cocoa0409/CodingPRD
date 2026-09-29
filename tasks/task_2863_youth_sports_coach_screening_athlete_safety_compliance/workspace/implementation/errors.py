"""Error catalog and the ApiError exception.

Every error_id / HTTP status pair below is taken from PRD.md section 5
(the authoritative catalogue) - where SCAFFOLD.yaml's validations table
disagreed with the PRD table (escrow 402, renewal window 422, body scope
422) the PRD table wins.
"""

ERROR_STATUS = {
    # ---- auth / authorization ----
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_CLUB_SCOPE_VIOLATION": 403,
    "ERR_DECISION_ROLE_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # ---- shape ----
    "ERR_VALIDATION": 422,
    # ---- not found ----
    "ERR_CLUB_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_SCREENING_ORDER_NOT_FOUND": 404,
    "ERR_TRAINING_COURSE_NOT_FOUND": 404,
    "ERR_TRAINING_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_COACH_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_INVESTIGATING_BODY_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_INTERIM_MEASURE_NOT_FOUND": 404,
    "ERR_CLUB_AUDIT_NOT_FOUND": 404,
    "ERR_AUDIT_FINDING_NOT_FOUND": 404,
    "ERR_ROOM_STAY_NOT_FOUND": 404,
    # ---- uniqueness ----
    "ERR_DUPLICATE_MEMBER_EMAIL": 409,
    "ERR_DUPLICATE_COURSE_CODE": 409,
    # ---- optimistic concurrency ----
    "ERR_STALE_CLUB_VERSION": 412,
    "ERR_STALE_MEMBER_VERSION": 412,
    # ---- state ----
    "ERR_MEMBER_INVALID_STATE": 409,
    "ERR_SCREENING_ORDER_INVALID_STATE": 409,
    "ERR_TRAINING_ASSIGNMENT_INVALID_STATE": 409,
    "ERR_COACH_ASSIGNMENT_INVALID_STATE": 409,
    "ERR_CASE_INVALID_STATE": 409,
    "ERR_INTERIM_MEASURE_INVALID_STATE": 409,
    "ERR_AUDIT_INVALID_STATE": 409,
    "ERR_FINDING_INVALID_STATE": 409,
    "ERR_ROOM_STAY_INVALID_STATE": 409,
    # ---- domain gates ----
    "ERR_CLUB_POSTURE_FROZEN": 409,
    "ERR_MEMBER_DISQUALIFIED": 409,
    "ERR_CONTACT_NOT_PERMITTED": 409,
    "ERR_MINOR_ADULT_LODGING_PROHIBITED": 409,
    "ERR_ELECTRONIC_COMM_NOT_PERMITTED": 409,
    "ERR_SCREENING_NOT_CURRENT": 409,
    "ERR_TRAINING_NOT_CURRENT": 409,
    "ERR_MEASURE_WINDOW_CONFLICT": 409,
    "ERR_RENEWAL_WINDOW_NOT_OPEN": 409,
    "ERR_BODY_SCOPE_MISMATCH": 409,
    "ERR_BODY_INTAKE_PAUSED": 409,
    "ERR_BODY_CASELOAD_EXCEEDED": 409,
    "ERR_ROOM_OCCUPANCY_CONFLICT": 409,
    "ERR_ESCROW_INSUFFICIENT": 409,
    # ---- routing fallback ----
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
