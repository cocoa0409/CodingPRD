"""Error catalogue for the Hospital Safety Grade Survey API."""

# --- Authentication / authorization ---
ERR_MISSING_USER_CONTEXT_HEADER = "ERR_MISSING_USER_CONTEXT_HEADER"
ERR_INSUFFICIENT_PERMISSIONS = "ERR_INSUFFICIENT_PERMISSIONS"

# --- Not found ---
ERR_HOSPITAL_NOT_FOUND = "ERR_HOSPITAL_NOT_FOUND"
ERR_SURVEY_NOT_FOUND = "ERR_SURVEY_NOT_FOUND"
ERR_SURVEY_MEASURE_NOT_FOUND = "ERR_SURVEY_MEASURE_NOT_FOUND"
ERR_METHODOLOGY_VERSION_NOT_FOUND = "ERR_METHODOLOGY_VERSION_NOT_FOUND"
ERR_HOSPITAL_METHODOLOGY_VERSION_NOT_FOUND = "ERR_HOSPITAL_METHODOLOGY_VERSION_NOT_FOUND"
ERR_PENDING_METHODOLOGY_CHANGE_NOT_FOUND = "ERR_PENDING_METHODOLOGY_CHANGE_NOT_FOUND"
ERR_MEASURE_SET_NOT_FOUND = "ERR_MEASURE_SET_NOT_FOUND"
ERR_SCORE_RUN_NOT_FOUND = "ERR_SCORE_RUN_NOT_FOUND"
ERR_RELEASE_CYCLE_NOT_FOUND = "ERR_RELEASE_CYCLE_NOT_FOUND"
ERR_GRADE_NOT_FOUND = "ERR_GRADE_NOT_FOUND"
ERR_REVIEW_NOT_FOUND = "ERR_REVIEW_NOT_FOUND"
ERR_CORRECTION_NOT_FOUND = "ERR_CORRECTION_NOT_FOUND"
ERR_REANALYSIS_REQUEST_NOT_FOUND = "ERR_REANALYSIS_REQUEST_NOT_FOUND"
ERR_EMPLOYER_NOT_FOUND = "ERR_EMPLOYER_NOT_FOUND"

# --- Required input / malformed ---
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_MINIMUM_LETTER = "ERR_INVALID_MINIMUM_LETTER"
ERR_REANALYSIS_SELECTOR_ARITY = "ERR_REANALYSIS_SELECTOR_ARITY"
ERR_REANALYSIS_SELECTOR_UNRESOLVED = "ERR_REANALYSIS_SELECTOR_UNRESOLVED"
ERR_INVALID_TEACHING_STATUS = "ERR_INVALID_TEACHING_STATUS"
ERR_INVALID_CORRECTION_TYPE = "ERR_INVALID_CORRECTION_TYPE"
ERR_DUPLICATE_CCN = "ERR_DUPLICATE_CCN"

# --- Concurrency ---
ERR_STALE_VERSION = "ERR_STALE_VERSION"

# --- Hospital-level state ---
ERR_HOSPITAL_NOT_ACTIVE = "ERR_HOSPITAL_NOT_ACTIVE"
ERR_METHODOLOGY_VERSION_REQUIRED = "ERR_METHODOLOGY_VERSION_REQUIRED"
ERR_SNAPSHOT_ALREADY_CURRENT = "ERR_SNAPSHOT_ALREADY_CURRENT"

# --- Survey state ---
ERR_SURVEY_ALREADY_SUBMITTED = "ERR_SURVEY_ALREADY_SUBMITTED"
ERR_SURVEY_RESPONSE_COUNT_INCONSISTENT = "ERR_SURVEY_RESPONSE_COUNT_INCONSISTENT"
ERR_SURVEY_SAMPLE_DENOMINATOR_INVALID = "ERR_SURVEY_SAMPLE_DENOMINATOR_INVALID"
ERR_SURVEY_HAS_NO_MEASURES = "ERR_SURVEY_HAS_NO_MEASURES"
ERR_SURVEY_OWNER_MISMATCH = "ERR_SURVEY_OWNER_MISMATCH"
ERR_SURVEY_NOT_IN_DISCREPANCY = "ERR_SURVEY_NOT_IN_DISCREPANCY"
ERR_SURVEY_VERIFICATION_ALREADY_OPEN = "ERR_SURVEY_VERIFICATION_ALREADY_OPEN"
ERR_SELF_VERIFICATION_FORBIDDEN = "ERR_SELF_VERIFICATION_FORBIDDEN"
ERR_SOURCE_DOCUMENTATION_REQUIRED = "ERR_SOURCE_DOCUMENTATION_REQUIRED"

# --- Measure set / scoring ---
ERR_MEASURE_SET_NOT_READY = "ERR_MEASURE_SET_NOT_READY"
ERR_MEASURE_SET_OMITTED = "ERR_MEASURE_SET_OMITTED"
ERR_CHAR_EXEMPTION_UNSUPPORTED = "ERR_CHAR_EXEMPTION_UNSUPPORTED"
ERR_METHODOLOGY_INCOMPLETE = "ERR_METHODOLOGY_INCOMPLETE"
ERR_MEASURE_CODE_NOT_IN_METHODOLOGY = "ERR_MEASURE_CODE_NOT_IN_METHODOLOGY"

# --- Methodology change management ---
ERR_METHODOLOGY_NOT_COMPARABLE = "ERR_METHODOLOGY_NOT_COMPARABLE"
ERR_METHODOLOGY_UNCHANGED = "ERR_METHODOLOGY_UNCHANGED"

# --- Reanalysis ---
ERR_REANALYSIS_NOT_UNDER_REVIEW = "ERR_REANALYSIS_NOT_UNDER_REVIEW"
ERR_REANALYSIS_SURVEY_MISMATCH = "ERR_REANALYSIS_SURVEY_MISMATCH"
ERR_REANALYSIS_REFERENCE_STALE = "ERR_REANALYSIS_REFERENCE_STALE"
ERR_REANALYSIS_DOCUMENTS_INSUFFICIENT = "ERR_REANALYSIS_DOCUMENTS_INSUFFICIENT"
ERR_REANALYSIS_REGRESSION_FORBIDDEN = "ERR_REANALYSIS_REGRESSION_FORBIDDEN"
ERR_HOSPITAL_OWNER_MISMATCH = "ERR_HOSPITAL_OWNER_MISMATCH"

# --- Release cycle / grades ---
ERR_CYCLE_NOT_DRAFT = "ERR_CYCLE_NOT_DRAFT"
ERR_CYCLE_HAS_NO_GRADES = "ERR_CYCLE_HAS_NO_GRADES"
ERR_CYCLE_NOT_OPEN_FOR_CORRECTIONS = "ERR_CYCLE_NOT_OPEN_FOR_CORRECTIONS"
ERR_CORRECTION_WINDOW_CLOSED = "ERR_CORRECTION_WINDOW_CLOSED"
ERR_CORRECTIONS_PENDING = "ERR_CORRECTIONS_PENDING"
ERR_REVIEWS_PENDING = "ERR_REVIEWS_PENDING"
ERR_CORRECTION_NOT_PENDING = "ERR_CORRECTION_NOT_PENDING"
ERR_CORRECTION_MEASURE_NOT_CHALLENGED = "ERR_CORRECTION_MEASURE_NOT_CHALLENGED"
ERR_CYCLE_PUBLICATION_WINDOW_TOO_CLOSE = "ERR_CYCLE_PUBLICATION_WINDOW_TOO_CLOSE"
ERR_BENEFIT_WINDOW_CONTAINMENT_CONFLICT = "ERR_BENEFIT_WINDOW_CONTAINMENT_CONFLICT"
ERR_BENEFIT_WINDOW_INVALID = "ERR_BENEFIT_WINDOW_INVALID"
ERR_EMBARGO_ACTIVE = "ERR_EMBARGO_ACTIVE"
ERR_CYCLE_ALREADY_PUBLISHED = "ERR_CYCLE_ALREADY_PUBLISHED"
ERR_CYCLE_GRADES_UNRESOLVED = "ERR_CYCLE_GRADES_UNRESOLVED"

# --- Additional derived-state codes named by the PRD prose ---
ERR_SCORE_RUN_UNRESOLVED = "ERR_SCORE_RUN_UNRESOLVED"
ERR_PRELIMINARY_WINDOW_NOT_OPEN = "ERR_PRELIMINARY_WINDOW_NOT_OPEN"

HTTP_STATUS = {
    ERR_MISSING_USER_CONTEXT_HEADER: 400,
    ERR_INSUFFICIENT_PERMISSIONS: 403,
    ERR_HOSPITAL_NOT_FOUND: 404,
    ERR_SURVEY_NOT_FOUND: 404,
    ERR_SURVEY_MEASURE_NOT_FOUND: 404,
    ERR_METHODOLOGY_VERSION_NOT_FOUND: 404,
    ERR_HOSPITAL_METHODOLOGY_VERSION_NOT_FOUND: 404,
    ERR_PENDING_METHODOLOGY_CHANGE_NOT_FOUND: 404,
    ERR_MEASURE_SET_NOT_FOUND: 404,
    ERR_SCORE_RUN_NOT_FOUND: 404,
    ERR_RELEASE_CYCLE_NOT_FOUND: 404,
    ERR_GRADE_NOT_FOUND: 404,
    ERR_REVIEW_NOT_FOUND: 404,
    ERR_CORRECTION_NOT_FOUND: 404,
    ERR_REANALYSIS_REQUEST_NOT_FOUND: 404,
    ERR_EMPLOYER_NOT_FOUND: 404,
    ERR_INVALID_REQUEST: 400,
    ERR_INVALID_MINIMUM_LETTER: 400,
    ERR_REANALYSIS_SELECTOR_ARITY: 400,
    ERR_REANALYSIS_SELECTOR_UNRESOLVED: 400,
    ERR_INVALID_TEACHING_STATUS: 400,
    ERR_INVALID_CORRECTION_TYPE: 400,
    ERR_BENEFIT_WINDOW_INVALID: 400,
    ERR_DUPLICATE_CCN: 409,
    ERR_STALE_VERSION: 412,
    ERR_HOSPITAL_NOT_ACTIVE: 409,
    ERR_METHODOLOGY_VERSION_REQUIRED: 409,
    ERR_SNAPSHOT_ALREADY_CURRENT: 409,
    ERR_SURVEY_ALREADY_SUBMITTED: 409,
    ERR_SURVEY_RESPONSE_COUNT_INCONSISTENT: 409,
    ERR_SURVEY_SAMPLE_DENOMINATOR_INVALID: 409,
    ERR_SURVEY_HAS_NO_MEASURES: 409,
    ERR_SURVEY_OWNER_MISMATCH: 403,
    ERR_SURVEY_NOT_IN_DISCREPANCY: 409,
    ERR_SURVEY_VERIFICATION_ALREADY_OPEN: 409,
    ERR_SELF_VERIFICATION_FORBIDDEN: 403,
    ERR_SOURCE_DOCUMENTATION_REQUIRED: 409,
    ERR_MEASURE_SET_NOT_READY: 409,
    ERR_MEASURE_SET_OMITTED: 409,
    ERR_CHAR_EXEMPTION_UNSUPPORTED: 409,
    ERR_METHODOLOGY_INCOMPLETE: 409,
    ERR_MEASURE_CODE_NOT_IN_METHODOLOGY: 409,
    ERR_METHODOLOGY_NOT_COMPARABLE: 409,
    ERR_METHODOLOGY_UNCHANGED: 409,
    ERR_REANALYSIS_NOT_UNDER_REVIEW: 409,
    ERR_REANALYSIS_SURVEY_MISMATCH: 409,
    ERR_REANALYSIS_REFERENCE_STALE: 409,
    ERR_REANALYSIS_DOCUMENTS_INSUFFICIENT: 409,
    ERR_REANALYSIS_REGRESSION_FORBIDDEN: 403,
    ERR_HOSPITAL_OWNER_MISMATCH: 403,
    ERR_CYCLE_NOT_DRAFT: 409,
    ERR_CYCLE_HAS_NO_GRADES: 409,
    ERR_CYCLE_NOT_OPEN_FOR_CORRECTIONS: 409,
    ERR_CORRECTION_WINDOW_CLOSED: 409,
    ERR_CORRECTIONS_PENDING: 409,
    ERR_REVIEWS_PENDING: 409,
    ERR_CORRECTION_NOT_PENDING: 409,
    ERR_CORRECTION_MEASURE_NOT_CHALLENGED: 409,
    ERR_CYCLE_PUBLICATION_WINDOW_TOO_CLOSE: 409,
    ERR_BENEFIT_WINDOW_CONTAINMENT_CONFLICT: 409,
    ERR_EMBARGO_ACTIVE: 409,
    ERR_CYCLE_ALREADY_PUBLISHED: 409,
    ERR_CYCLE_GRADES_UNRESOLVED: 409,
    ERR_SCORE_RUN_UNRESOLVED: 409,
    ERR_PRELIMINARY_WINDOW_NOT_OPEN: 409,
}

MESSAGES = {
    ERR_MISSING_USER_CONTEXT_HEADER: "X-User-ID or X-User-Role header is absent or empty.",
    ERR_INSUFFICIENT_PERMISSIONS: "The supplied role is not permitted on this operation.",
    ERR_HOSPITAL_NOT_FOUND: "No Hospital exists with the supplied id.",
    ERR_SURVEY_NOT_FOUND: "No Survey exists with the supplied id.",
    ERR_SURVEY_MEASURE_NOT_FOUND: "No SurveyMeasure exists with the supplied id.",
    ERR_METHODOLOGY_VERSION_NOT_FOUND: "No MethodologyVersion exists with the supplied id.",
    ERR_HOSPITAL_METHODOLOGY_VERSION_NOT_FOUND: "No HospitalMethodologyVersion exists with the supplied id.",
    ERR_PENDING_METHODOLOGY_CHANGE_NOT_FOUND: "No PendingMethodologyChange exists with the supplied id.",
    ERR_MEASURE_SET_NOT_FOUND: "No HospitalMeasureSet exists for the hospital and methodology version.",
    ERR_SCORE_RUN_NOT_FOUND: "No ScoreRun exists with the supplied id.",
    ERR_RELEASE_CYCLE_NOT_FOUND: "No ReleaseCycle exists with the supplied id.",
    ERR_GRADE_NOT_FOUND: "No Grade exists with the supplied id.",
    ERR_REVIEW_NOT_FOUND: "No HospitalReview exists with the supplied id for this hospital.",
    ERR_CORRECTION_NOT_FOUND: "No CorrectionRequest exists with the supplied id for this review.",
    ERR_REANALYSIS_REQUEST_NOT_FOUND: "No ReanalysisRequest exists with the supplied id for this hospital.",
    ERR_EMPLOYER_NOT_FOUND: "No Employer exists with the supplied id.",
    ERR_INVALID_REQUEST: "A required input field is absent, has the wrong type, or fails a declared constraint.",
    ERR_INVALID_MINIMUM_LETTER: "minimum_acceptable_letter is not one of A | B | C | D.",
    ERR_REANALYSIS_SELECTOR_ARITY: "subset_selector carries fewer than 1 or more than 20 entries.",
    ERR_REANALYSIS_SELECTOR_UNRESOLVED: "A subset_selector entry names a measure_code or domain absent from the pinned methodology version.",
    ERR_INVALID_TEACHING_STATUS: "teaching_status is not TEACHING or NON_TEACHING.",
    ERR_INVALID_CORRECTION_TYPE: "correction_type is not one of MEASURE_VALUE_ERROR | MEASURE_OMISSION | SOURCE_PROGRAM_MISMATCH.",
    ERR_BENEFIT_WINDOW_INVALID: "benefit_window_to is not strictly greater than benefit_window_from.",
    ERR_DUPLICATE_CCN: "ccn already belongs to another Hospital.",
    ERR_STALE_VERSION: "expected_hospital_version does not equal the parent Hospital's current version.",
    ERR_HOSPITAL_NOT_ACTIVE: "Hospital.status is SUSPENDED; submissions, scoring and refresh are refused.",
    ERR_METHODOLOGY_VERSION_REQUIRED: "The hospital has no pinned methodology version.",
    ERR_SNAPSHOT_ALREADY_CURRENT: "The logical clock instant equals the measure set's source_snapshot_at.",
    ERR_SURVEY_ALREADY_SUBMITTED: "survey.af_status is not AWAITING_SUBMISSION at submit time.",
    ERR_SURVEY_RESPONSE_COUNT_INCONSISTENT: "completed_survey_count exceeds started_survey_count, or started_survey_count is zero.",
    ERR_SURVEY_SAMPLE_DENOMINATOR_INVALID: "entity_annual_discharges is less than 1.",
    ERR_SURVEY_HAS_NO_MEASURES: "The survey has no SurveyMeasure rows at submit time.",
    ERR_SURVEY_OWNER_MISMATCH: "The acting X-User-ID is not survey.submitted_by_user_id.",
    ERR_SURVEY_NOT_IN_DISCREPANCY: "survey.af_status is not DISCREPANCY_OPEN at resolve time.",
    ERR_SURVEY_VERIFICATION_ALREADY_OPEN: "A verification decision is already recorded on this survey in its current state.",
    ERR_SELF_VERIFICATION_FORBIDDEN: "The verifying X-User-ID equals survey.submitted_by_user_id.",
    ERR_SOURCE_DOCUMENTATION_REQUIRED: "A measure lacks source_program_id and the survey carries no adopted supporting documentation.",
    ERR_MEASURE_SET_NOT_READY: "HospitalMeasureSet.readiness_state is not READY.",
    ERR_MEASURE_SET_OMITTED: "HospitalMeasureSet.readiness_state is OMITTED_FROM_CYCLE because four or more measures were substituted.",
    ERR_CHAR_EXEMPTION_UNSUPPORTED: "A CHAR_EXEMPT run was requested for a hospital that does have verified or publicly sourced measures.",
    ERR_METHODOLOGY_INCOMPLETE: "The pinned methodology version's measure_definitions do not cover all five domains with positive weights.",
    ERR_MEASURE_CODE_NOT_IN_METHODOLOGY: "A measure_code in the payload is absent from the pinned methodology version's measure_definitions.",
    ERR_METHODOLOGY_NOT_COMPARABLE: "methodology_comparability_index for the requested change is below 0.80.",
    ERR_METHODOLOGY_UNCHANGED: "The requested methodology version equals the version already in scope for the operation.",
    ERR_REANALYSIS_NOT_UNDER_REVIEW: "The reanalysis request is not in UNDER_REVIEW.",
    ERR_REANALYSIS_SURVEY_MISMATCH: "The reanalysis request does not reference the survey named in the operation.",
    ERR_REANALYSIS_REFERENCE_STALE: "The survey's pinned methodology version differs from the hospital's currently pinned version.",
    ERR_REANALYSIS_DOCUMENTS_INSUFFICIENT: "Fewer than six distinct document codes were supplied to support the grant.",
    ERR_REANALYSIS_REGRESSION_FORBIDDEN: "The requested adjusted_delta would lower the hospital's composite score.",
    ERR_HOSPITAL_OWNER_MISMATCH: "The acting X-User-ID does not correspond to the hospital named in the path.",
    ERR_CYCLE_NOT_DRAFT: "The release cycle is not DRAFT.",
    ERR_CYCLE_HAS_NO_GRADES: "The release cycle has zero Grade rows.",
    ERR_CYCLE_NOT_OPEN_FOR_CORRECTIONS: "The release cycle's state is not OPEN_REVIEW.",
    ERR_CORRECTION_WINDOW_CLOSED: "The logical clock instant is at or after the cycle's correction_window_ends_at.",
    ERR_CORRECTIONS_PENDING: "A CorrectionRequest in the cycle is still PENDING.",
    ERR_REVIEWS_PENDING: "A HospitalReview in the cycle is still PENDING.",
    ERR_CORRECTION_NOT_PENDING: "The CorrectionRequest is not PENDING.",
    ERR_CORRECTION_MEASURE_NOT_CHALLENGED: "corrected_measure_codes includes a measure the parent review never challenged.",
    ERR_CYCLE_PUBLICATION_WINDOW_TOO_CLOSE: "The publication_date sits less than 30 days from a cycle bound to a different methodology version.",
    ERR_BENEFIT_WINDOW_CONTAINMENT_CONFLICT: "The submitted benefit-design window strictly contains another Employer's window in the same scope.",
    ERR_EMBARGO_ACTIVE: "The logical clock instant is strictly before the cycle's publication_date.",
    ERR_CYCLE_ALREADY_PUBLISHED: "The release cycle is already PUBLISHED.",
    ERR_CYCLE_GRADES_UNRESOLVED: "A Grade in the cycle is WITHHELD with no recorded reason, or is still unresolved.",
    ERR_SCORE_RUN_UNRESOLVED: "A score run feeding the cycle has not returned SCORED or CHAR_EXEMPT.",
    ERR_PRELIMINARY_WINDOW_NOT_OPEN: "The logical clock instant is before the cycle's preliminary_release_date.",
}


class ApiError(Exception):
    """Carries an error id, a human message and the HTTP status to return."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)
        super().__init__(self.message)