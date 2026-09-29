"""Error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_COURSE_INSTRUCTOR": 403,
    "ERR_NOT_ASSIGNED_TUTOR": 403,
    "ERR_NOT_OWN_RECORD": 403,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    # existence
    "ERR_TERM_NOT_FOUND": 404,
    "ERR_DEGREE_PROGRAM_NOT_FOUND": 404,
    "ERR_COURSE_NOT_FOUND": 404,
    "ERR_APPLICABILITY_RULE_NOT_FOUND": 404,
    "ERR_STUDENT_ATHLETE_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_CERTIFICATION_NOT_FOUND": 404,
    "ERR_TUTOR_NOT_FOUND": 404,
    "ERR_TUTOR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_SUPPORT_SESSION_NOT_FOUND": 404,
    "ERR_COMPETITION_EVENT_NOT_FOUND": 404,
    "ERR_MISSED_CLASS_REQUEST_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_COMPLIANCE_INCIDENT_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_TIME_WINDOW": 422,
    # concurrency
    "ERR_STALE_STUDENT_VERSION": 412,
    # state
    "ERR_APR_TERM_CLOSED": 409,
    "ERR_APR_TERM_NOT_ENDED": 409,
    "ERR_APR_PRIOR_TERM_OPEN": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_EVENT_NOT_TRAVEL_APPROVED": 409,
    "ERR_APPEAL_NOT_ELIGIBLE": 422,
    # compliance / safety
    "ERR_TUTOR_NOT_TRAINED": 422,
    "ERR_TUTOR_TRAINING_EXPIRED": 422,
    "ERR_IMPERMISSIBLE_ASSISTANCE_BLOCK": 422,
    # referential
    "ERR_TUTOR_SUBJECT_MISMATCH": 422,
    "ERR_MAJOR_NOT_DECLARED": 422,
    "ERR_ENROLLMENT_NOT_NOTIFIABLE": 422,
    "ERR_TRANSFER_CREDIT_SOURCE_INVALID": 422,
    "ERR_CERTIFICATION_TYPE_TERM_MISMATCH": 422,
    # temporal
    "ERR_MAJOR_DECLARATION_DEADLINE_PASSED": 422,
    "ERR_NOTIFICATION_LEAD_TIME_VIOLATION": 422,
    "ERR_ACKNOWLEDGEMENT_WINDOW_CLOSED": 422,
    "ERR_SESSION_OUTSIDE_TERM": 422,
    "ERR_TRANSFER_RESIDENCY_NOT_MET": 422,
    # constraint
    "ERR_STUDENT_SESSION_OVERLAP": 409,
    "ERR_TUTOR_BUFFER_VIOLATION": 409,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    "ERR_DUPLICATE_APPLICABILITY_RULE": 409,
    "ERR_APPEAL_ROUNDS_EXHAUSTED": 409,
    # fiscal / capacity
    "ERR_MISSED_CLASS_ALLOWANCE_EXCEEDED": 422,
    "ERR_TUTOR_WEEKLY_HOURS_EXCEEDED": 422,
    "ERR_TIER_HOURS_CAP_EXCEEDED": 422,
    "ERR_RELIEF_EXCEEDS_REQUEST": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and must be non-empty.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorised for this endpoint.",
    "ERR_NOT_COURSE_INSTRUCTOR": "Only the instructor of record may respond to this missed-class request.",
    "ERR_NOT_ASSIGNED_TUTOR": "A tutor may only log sessions against its own assignments.",
    "ERR_NOT_OWN_RECORD": "A student-athlete may only read its own record.",
    "ERR_SEGREGATION_OF_DUTIES": "The requesting operator may not decide this record.",
    "ERR_INVALID_REQUEST": "The request body or query parameters are malformed.",
    "ERR_INVALID_TIME_WINDOW": "The opening instant must strictly precede the closing instant.",
    "ERR_STALE_STUDENT_VERSION": "expected_student_athlete_version does not match the student's current version.",
    "ERR_APR_TERM_CLOSED": "The governing term is closed for academic-progress-rate reporting.",
    "ERR_APR_TERM_NOT_ENDED": "The term has not ended yet.",
    "ERR_APR_PRIOR_TERM_OPEN": "An earlier reporting term is still open.",
    "ERR_INVALID_STATE_TRANSITION": "The requested action is not a declared transition out of the current state.",
    "ERR_EVENT_NOT_TRAVEL_APPROVED": "The competition event is not travel-approved.",
    "ERR_APPEAL_NOT_ELIGIBLE": "The linked certification is neither denied nor revoked.",
    "ERR_TUTOR_NOT_TRAINED": "The tutor is untrained.",
    "ERR_TUTOR_TRAINING_EXPIRED": "The tutor's training has lapsed or the tutor is suspended or terminated.",
    "ERR_IMPERMISSIBLE_ASSISTANCE_BLOCK": "Tutoring support is blocked for this student.",
    "ERR_TUTOR_SUBJECT_MISMATCH": "The tutor is not cleared for this course subject.",
    "ERR_MAJOR_NOT_DECLARED": "The student has no declared degree program.",
    "ERR_ENROLLMENT_NOT_NOTIFIABLE": "The enrollment cannot be notified for this event.",
    "ERR_TRANSFER_CREDIT_SOURCE_INVALID": "The transfer credit source requirement is not met.",
    "ERR_CERTIFICATION_TYPE_TERM_MISMATCH": "certification_type does not match the term and the student.",
    "ERR_MAJOR_DECLARATION_DEADLINE_PASSED": "The major declaration deadline has passed.",
    "ERR_NOTIFICATION_LEAD_TIME_VIOLATION": "Instructor notification requires at least 7 days of lead time.",
    "ERR_ACKNOWLEDGEMENT_WINDOW_CLOSED": "The acknowledgement window has closed.",
    "ERR_SESSION_OUTSIDE_TERM": "The session does not lie inside its term of record.",
    "ERR_TRANSFER_RESIDENCY_NOT_MET": "The transfer residency requirement is not met.",
    "ERR_STUDENT_SESSION_OVERLAP": "The session overlaps another session of the same student.",
    "ERR_TUTOR_BUFFER_VIOLATION": "Two sessions of the same tutor are less than 20 minutes apart.",
    "ERR_DUPLICATE_ENROLLMENT": "A non-terminal enrollment already exists for this student, course and term.",
    "ERR_DUPLICATE_APPLICABILITY_RULE": "A rule already exists for this program, course and catalog year.",
    "ERR_APPEAL_ROUNDS_EXHAUSTED": "The round limit for this chain has been reached.",
    "ERR_MISSED_CLASS_ALLOWANCE_EXCEEDED": "The computed missed units exceed the student's remaining allowance.",
    "ERR_TUTOR_WEEKLY_HOURS_EXCEEDED": "The tutor's weekly hour ceiling would be exceeded.",
    "ERR_TIER_HOURS_CAP_EXCEEDED": "The student's tier weekly hour ceiling would be exceeded.",
    "ERR_RELIEF_EXCEEDS_REQUEST": "granted_credit_relief exceeds the appeal's requested_credit_relief.",
}
