"""Error catalog: error ids, HTTP statuses, and default messages (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# id -> (http_status, default message)
CATALOG = {
    # auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": (400, "X-User-ID and X-User-Role headers must be present and non-empty"),
    "ERR_FORBIDDEN_ROLE": (403, "Caller role is not permitted on this endpoint, or ownership check failed"),
    # request shape / existence / OCC
    "ERR_INVALID_REQUEST": (400, "Request body is malformed: missing required field, type mismatch, or invalid enum value"),
    "ERR_CE_HOURS_INCREMENT": (400, "CE hours must be a positive multiple of 0.5"),
    "ERR_CE_ENTRY_OUTSIDE_CYCLE": (422, "CE entry course_date falls outside the pinned cycle window"),
    "ERR_NOT_FOUND": (404, "Referenced resource does not exist"),
    "ERR_STALE_VERSION": (412, "expected version does not match the resource's current version"),
    # state
    "ERR_INVALID_STATE": (409, "The resource's current state does not allow this transition"),
    "ERR_COMPLETION_NOT_PENDING": (409, "Completion record is not PENDING_VERIFICATION"),
    "ERR_APPLICATION_NOT_SUBMITTED": (409, "Exam application is not SUBMITTED"),
    "ERR_APPLICATION_NOT_DENIED": (409, "Exam application is not DENIED"),
    "ERR_ATT_NOT_ISSUABLE": (409, "Authorization to test is not ISSUED, is expired, or is already referenced by an attempt"),
    "ERR_ATTEMPT_NOT_SCHEDULED": (409, "Attempt is not SCHEDULED"),
    "ERR_DELIVERY_WINDOW_NOT_OPEN": (409, "Current time is outside the attempt's delivery window"),
    "ERR_RECERT_NOT_DRAFT": (409, "Recertification application is not DRAFT"),
    "ERR_RECERT_NOT_SUBMITTED": (409, "Recertification application is not SUBMITTED"),
    "ERR_RECERT_NOT_AUDIT_PENDING": (409, "Recertification application is not AUDIT_PENDING"),
    "ERR_RECERT_NOT_REOPENABLE": (409, "Recertification application is not DENIED or AUDIT_FAILED"),
    "ERR_CERTIFICATION_NOT_ACTIVE": (409, "Certification is not ACTIVE"),
    "ERR_CERTIFICATION_NOT_LAPSED": (409, "Certification is not LAPSED"),
    "ERR_LICENSE_NOT_ACTIONABLE": (409, "License application is not UNDER_REVIEW"),
    "ERR_LICENSE_NOT_AWAITING_RESPONSE": (409, "License application is not MORE_INFO_REQUIRED"),
    "ERR_PSYCHOMOTOR_NOT_SUBMITTED": (409, "Psychomotor verification is not SUBMITTED"),
    "ERR_PSYCHOMOTOR_REQUIREMENTS_UNMET": (422, "Verification requires all stations passed and documentation attached"),
    "ERR_CASE_STAGE_MISMATCH": (409, "Disciplinary case is not in the stage this action requires"),
    "ERR_REENTRY_NOT_SUBMITTED": (409, "Reentry application is not SUBMITTED"),
    # business safety
    "ERR_DISCIPLINARY_HOLD": (403, "Candidate is under a non-final HOLD_NEW_APPLICATIONS interim action"),
    "ERR_PERMANENTLY_BARRED": (403, "Candidate is BARRED"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The same user may not perform both sides of a segregated duty"),
    "ERR_PROGRAM_NOT_ACCREDITED_AT_COMPLETION": (422, "Program accreditation at the completion date was not ACCREDITED or PROVISIONAL"),
    # referential
    "ERR_CROSS_REFERENCE_MISMATCH": (422, "Referenced records disagree on candidate or level"),
    "ERR_LEVEL_NOT_ACCEPTED_IN_STATE": (422, "Certification level is not accepted by the state policy on the national path"),
    "ERR_STATE_EXAM_NOT_PASSING": (422, "State exam record is not usable: not passing or not VALID"),
    # temporal
    "ERR_EDUCATION_VALIDITY_EXPIRED": (409, "Completion record is outside its 24-month education-validity window"),
    "ERR_RETAKE_WAIT_ACTIVE": (409, "The 15-day retake wait after the last scored attempt has not elapsed"),
    "ERR_RECERT_WINDOW_NOT_OPEN": (409, "Current time is outside the recertification cycle window"),
    "ERR_CREDENTIAL_STALE": (409, "An examination credential is older than 24 months"),
    "ERR_REENTRY_NOT_AVAILABLE": (409, "Lapse exceeds 24 months; the reentry pathway is closed"),
    "ERR_CLOCK_REGRESSION": (409, "The logical clock may not be moved backwards"),
    # constraint
    "ERR_ATTEMPT_SLOT_OVERLAP": (409, "The new attempt window conflicts with an existing SCHEDULED attempt"),
    "ERR_DUPLICATE_ACTIVE_CERTIFICATION": (409, "An ACTIVE certification already exists for this candidate and level"),
    "ERR_ACTIVE_VERIFICATION_EXISTS": (409, "exam_date falls inside an existing VERIFIED psychomotor validity window"),
    "ERR_DUPLICATE_COURSE_IN_CYCLE": (409, "course_code is already present on this recertification application"),
    "ERR_DUPLICATE_STATE_POLICY": (409, "A StateAdoptionPolicy for this state_code already exists"),
    "ERR_DUPLICATE_LEVEL_CODE": (409, "A LevelDefinition for this code already exists"),
    "ERR_RECERT_IN_PROGRESS_CONFLICT": (409, "Another recertification application for this certification is SUBMITTED or AUDIT_PENDING"),
    # quota / fiscal
    "ERR_ATTEMPT_LIMIT_REACHED": (409, "The attempt budget of 6 on this basis is exhausted"),
    "ERR_REMEDIAL_REQUIRED": (422, "Three or more attempts consumed without a qualifying remedial education record"),
    "ERR_CE_COMPONENT_SHORTFALL": (422, "A continuing-education component minimum is unmet"),
    "ERR_CE_TOTAL_SHORTFALL": (422, "Total credited continuing-education hours are below the required total"),
    "ERR_JURISPRUDENCE_REQUIRED": (422, "The state policy requires a jurisprudence exam attestation"),
    "ERR_REENTRY_REQUIREMENTS_UNMET": (422, "Tier hours claimed are below the level minimum"),
}


def raise_err(error_id, message=None):
    http_status, default_message = CATALOG[error_id]
    raise ApiError(error_id, http_status, message or default_message)
