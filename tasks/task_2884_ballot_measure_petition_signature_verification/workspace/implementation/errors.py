"""Error catalogue — every error_id from PRD section 5 with its HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


ERROR_STATUS = {
    # --- authentication (401) ---
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_INVALID_ROLE": 401,
    # --- authorisation / ownership (403) ---
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_CHALLENGE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- request shape (400) ---
    "ERR_INVALID_REQUEST": 400,
    # --- existence (404) ---
    "ERR_VERIFICATION_STANDARD_NOT_FOUND": 404,
    "ERR_COUNTY_NOT_FOUND": 404,
    "ERR_VOTER_RECORD_NOT_FOUND": 404,
    "ERR_PETITION_NOT_FOUND": 404,
    "ERR_CIRCULATOR_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_SIGNATURE_RECORD_NOT_FOUND": 404,
    "ERR_ROUND_NOT_FOUND": 404,
    "ERR_CURE_PERIOD_NOT_FOUND": 404,
    "ERR_CHALLENGE_NOT_FOUND": 404,
    "ERR_FRAUD_REFERRAL_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    # --- optimistic concurrency (412) ---
    "ERR_STALE_PETITION_VERSION": 412,
    "ERR_STALE_CIRCULATOR_VERSION": 412,
    # --- state preconditions (409) ---
    "ERR_INVALID_PETITION_STATE": 409,
    "ERR_INVALID_BATCH_STATE": 409,
    "ERR_BATCH_ALREADY_TERMINAL": 409,
    "ERR_INVALID_ROUND_STATE": 409,
    "ERR_ROUND_ALREADY_OPEN": 409,
    "ERR_INVALID_CIRCULATOR_STATE": 409,
    "ERR_INVALID_CHALLENGE_STATE": 409,
    "ERR_REFERRAL_NOT_WITH_AG": 409,
    "ERR_CHALLENGE_ALREADY_FILED": 409,
    # --- uniqueness (409) ---
    "ERR_DUPLICATE_JURISDICTION_CODE": 409,
    "ERR_DUPLICATE_COUNTY_CODE": 409,
    "ERR_DUPLICATE_VOTER_ID_NUMBER": 409,
    "ERR_DUPLICATE_LINE_NUMBER": 409,
    # --- statutory eligibility (422) ---
    "ERR_SINGLE_SUBJECT_VIOLATION": 422,
    "ERR_TITLE_SUMMARY_MISSING": 422,
    "ERR_TRAINING_COURSE_NOT_APPROVED": 422,
    "ERR_TRAINING_NOT_COMPLETE": 422,
    "ERR_PAID_DISCLOSURE_MISSING": 422,
    "ERR_AFFIDAVIT_NOT_SWORN": 422,
    "ERR_CIRCULATOR_NOT_REGISTERED": 422,
    "ERR_CIRCULATOR_REVOKED": 422,
    "ERR_CIRCULATOR_REINSTATEMENT_BARRED": 422,
    # --- cross-entity linkage (409) ---
    "ERR_NO_ACTIVE_ASSIGNMENT": 409,
    "ERR_COUNTY_NOT_IN_ASSIGNMENT": 409,
    "ERR_SUPPLEMENTAL_WITHOUT_CURE_PERIOD": 409,
    "ERR_CURE_PERIOD_NOT_OPEN": 409,
    "ERR_SIGNATURE_NOT_IN_OPEN_ROUND": 409,
    "ERR_LINE_NUMBER_NOT_FOUND": 409,
    "ERR_FRAUD_SUBSTANTIATED_BATCH": 409,
    # --- windows / intervals (409) ---
    "ERR_CIRCULATION_DEADLINE_PASSED": 409,
    "ERR_SIGNED_OUTSIDE_WINDOW": 409,
    "ERR_ASSIGNMENT_WINDOW_CONFLICT": 409,
    "ERR_CURE_PERIOD_OVERLAP": 409,
    "ERR_CURE_PERIOD_NOT_EXPIRED": 409,
    "ERR_CHALLENGE_REVIEW_WINDOW_EXPIRED": 409,
    "ERR_CHALLENGE_WINDOW_CLOSED": 409,
    # --- counting / quota gates (409) ---
    "ERR_FORMAT_REVIEW_ROUNDS_EXHAUSTED": 409,
    "ERR_CURE_LIMIT_REACHED": 409,
    "ERR_CURE_NOT_ELIGIBLE": 409,
    "ERR_EMPTY_ELIGIBLE_POOL": 409,
    "ERR_ROUND_HAS_PENDING_SIGNATURES": 409,
    "ERR_NO_VERIFIED_BATCHES": 409,
    "ERR_BATCH_EMPTY": 409,
    "ERR_COUNTY_DISTRIBUTION_UNMET": 409,
    "ERR_CHALLENGE_PENDING": 409,
    "ERR_FRAUD_REFERRAL_OPEN": 409,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_AUTH_HEADERS": "X-User-ID and X-User-Role headers are required",
    "ERR_INVALID_ROLE": "X-User-Role is not a recognised role",
    "ERR_UNAUTHORIZED": "Role is not permitted to call this endpoint",
    "ERR_NOT_RESOURCE_OWNER": "Caller does not own the target resource",
    "ERR_NOT_CHALLENGE_OWNER": "Caller did not file this challenge",
    "ERR_SEGREGATION_OF_DUTIES": "The same actor may not perform both steps",
    "ERR_INVALID_REQUEST": "The request body or query string is malformed",
}


def raise_error(error_id, message=None):
    raise ApiError(error_id, message)
