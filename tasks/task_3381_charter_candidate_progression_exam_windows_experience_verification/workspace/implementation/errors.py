"""Error catalog: error_id -> (HTTP status, default message).

Statuses are the normative ones from PRD section 5 (ERR_WINDOW_NOT_CONCLUDED
and ERR_OPEN_MISCONDUCT_CASE are 409; ERR_INCORRECT_DUES_AMOUNT is 422).
"""


class ApiError(Exception):
    def __init__(self, error_id, status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = status
        self.message = message or error_id


CATALOG = {
    'ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER': (400, 'X-User-ID or X-User-Role header missing, or role name not declared'),
    'ERR_FORBIDDEN_ROLE': (403, 'Acting role is not authorized for this endpoint'),
    'ERR_OWNERSHIP_MISMATCH': (403, 'Caller does not own the target resource'),
    'ERR_CANDIDATE_NOT_FOUND': (404, 'Candidate id does not exist'),
    'ERR_ENROLLMENT_NOT_FOUND': (404, 'ProgramEnrollment id does not exist'),
    'ERR_EXAM_LEVEL_NOT_FOUND': (404, 'ExamLevel id does not exist'),
    'ERR_EXAM_WINDOW_NOT_FOUND': (404, 'ExamWindow id does not exist'),
    'ERR_TEST_CENTER_NOT_FOUND': (404, 'TestCenter id does not exist'),
    'ERR_APPOINTMENT_NOT_FOUND': (404, 'ExamAppointment id does not exist'),
    'ERR_ATTEMPT_NOT_FOUND': (404, 'ExamAttempt id does not exist'),
    'ERR_SUBMISSION_NOT_FOUND': (404, 'WorkExperienceSubmission id does not exist'),
    'ERR_REFERENCE_NOT_FOUND': (404, 'ReferenceContact id does not exist'),
    'ERR_CASE_NOT_FOUND': (404, 'MisconductCase id does not exist'),
    'ERR_SOCIETY_NOT_FOUND': (404, 'Society id does not exist'),
    'ERR_MEMBERSHIP_NOT_FOUND': (404, 'SocietyMembership id does not exist'),
    'ERR_INVALID_REQUEST': (400, 'Request payload is malformed'),
    'ERR_SCORE_OUT_OF_RANGE': (400, 'scaled_score outside 0..1000'),
    'ERR_INVALID_PAYMENT_AMOUNT': (400, 'Payment amount_cents must be positive'),
    'ERR_DUPLICATE_CANDIDATE_EMAIL': (409, 'Email already registered'),
    'ERR_DUPLICATE_ENROLLMENT': (409, 'Candidate already holds a program enrollment'),
    'ERR_DUPLICATE_EXAM_LEVEL': (409, 'level_code already exists'),
    'ERR_DUPLICATE_CURRICULUM_YEAR': (409, 'cycle_year already exists for the level'),
    'ERR_DUPLICATE_SOCIETY_CODE': (409, 'society_code already exists'),
    'ERR_DUPLICATE_MEMBERSHIP': (409, 'An ACTIVE membership already exists for (candidate, society)'),
    'ERR_DUPLICATE_CONDUCT_STATEMENT': (409, 'A statement is already filed for (candidate, disclosure_year)'),
    'ERR_STALE_VERSION': (412, 'Expected version does not match the current version'),
    'ERR_ELIGIBILITY_NOT_MET': (422, 'Pathway eligibility thresholds not met'),
    'ERR_ENROLLMENT_NOT_ENROLLED': (409, 'Enrollment is not ENROLLED'),
    'ERR_WINDOW_NOT_OPEN': (409, 'Exam window is not OPEN'),
    'ERR_WINDOW_NOT_CANCELLABLE': (409, 'Window is already RESULTS_PUBLISHED or CANCELLED'),
    'ERR_APPOINTMENT_NOT_SCHEDULED': (409, 'Appointment booking_status is not SCHEDULED'),
    'ERR_ATTEMPT_ALREADY_SCORED': (409, 'Attempt is already SCORED'),
    'ERR_INVALID_SUBMISSION_STATE': (409, 'Submission is not in the required state'),
    'ERR_SUBMISSION_NOT_EDITABLE': (409, 'Submission is not RETURNED_FOR_REVISION'),
    'ERR_REFERENCE_NOT_PENDING': (409, 'Reference is not PENDING'),
    'ERR_INVALID_CASE_STATE': (409, 'Case is not in the required state'),
    'ERR_INVALID_MEMBERSHIP_STATE': (409, 'Membership is not ACTIVE'),
    'ERR_WINDOW_SCHEDULING_CLOSED': (422, 'Clock is past the window scheduling deadline'),
    'ERR_EXAM_DATE_OUTSIDE_WINDOW': (422, 'exam_date lies outside [window_opens_at, window_closes_at)'),
    'ERR_RESCHEDULE_DEADLINE_PASSED': (422, 'Clock is past the original window reschedule deadline'),
    'ERR_CHECKIN_NOT_ON_EXAM_DATE': (422, 'Check-in clock date does not equal exam_date'),
    'ERR_WINDOW_NOT_CONCLUDED': (409, 'Window has not concluded yet'),
    'ERR_APPEAL_WINDOW_EXPIRED': (422, 'Clock is past sanctioned_at + 30 days'),
    'ERR_IDENTITY_VERIFICATION_FAILED': (422, 'identity_document_number does not match gov_id_number'),
    'ERR_CALCULATOR_POLICY_VIOLATION': (422, 'Calculator presented is not the declared approved model'),
    'ERR_WINDOW_OVERLAP': (409, 'Same-level window overlaps an existing window'),
    'ERR_CENTER_BLACKOUT_CONFLICT': (409, 'exam_date falls inside a blackout range or its 1-day buffers'),
    'ERR_NO_SEAT_CAPACITY': (409, 'No seat available at the center on that date'),
    'ERR_DOUBLE_BOOKING_LEVEL': (409, 'Candidate already holds an active appointment for the level'),
    'ERR_CASE_ALREADY_OPEN_FOR_APPOINTMENT': (409, 'A case in OPENED, SANCTIONED or APPEALED already exists for the appointment'),
    'ERR_LEVEL_ALREADY_PASSED': (422, 'Target level already passed'),
    'ERR_PREREQUISITE_LEVEL_NOT_PASSED': (422, 'Predecessor level not passed'),
    'ERR_MAX_ATTEMPTS_REACHED': (422, 'Attempt cap reached for the level'),
    'ERR_RETAKE_WINDOW_TOO_SOON': (422, 'Target window does not open strictly after the latest failed window closed'),
    'ERR_WINDOW_LEVEL_MISMATCH': (422, 'Reschedule target window belongs to a different level'),
    'ERR_INSUFFICIENT_REFERENCES': (422, 'At least two non-expired references are required'),
    'ERR_INSUFFICIENT_VERIFIED_REFERENCES': (422, 'At least two VERIFIED references are required'),
    'ERR_LEVELS_NOT_ALL_PASSED': (422, 'Some exam level lacks a passing attempt'),
    'ERR_EXPERIENCE_REQUIREMENT_UNMET': (422, 'Approved committee months below 36'),
    'ERR_MISSING_CONDUCT_STATEMENT': (422, 'No conduct statement for the current calendar year'),
    'ERR_OPEN_MISCONDUCT_CASE': (409, 'A misconduct case in OPENED or APPEALED exists for the candidate'),
    'ERR_CHARTER_REQUIRED': (422, 'Membership join requires charter_awarded'),
    'ERR_CE_REQUIREMENT_NOT_MET': (422, 'Calendar-year CE credits below the society requirement'),
    'ERR_SEGREGATION_OF_DUTIES': (403, 'Adjudicator must differ from the case investigator'),
    'ERR_OUTSTANDING_BALANCE': (402, 'Enrollment outstanding balance must be zero'),
    'ERR_INCORRECT_DUES_AMOUNT': (422, 'dues_payment_cents must equal the society annual dues exactly'),
}


def fail(error_id, message=None):
    status, default = CATALOG[error_id]
    raise ApiError(error_id, status, message or default)
